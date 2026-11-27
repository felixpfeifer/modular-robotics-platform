// Lean GenICam camera driver built on Aravis (libaravis-0.8, LGPL). Opens GigE
// Vision (LAN) and USB3 Vision cameras of any vendor without a vendor SDK, and
// publishes JPEG on image/compressed: a drop-in replacement for camera_opencv,
// camera_realsense and camera_ids.

#include <camera_genicam/genicam_utils.hpp>

#include <mrp_camera_common/camera_node.hpp>
#include <mrp_camera_common/image.hpp>
#include <mrp_camera_common/parameters.hpp>

#include <arv.h>

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

using mrp_camera_common::MAX_IMAGE_DIMENSION;
using mrp_camera_common::read_only;
using mrp_camera_common::read_only_int;

constexpr int DEFAULT_WIDTH = 640;
constexpr int DEFAULT_HEIGHT = 480;
constexpr double DEFAULT_FPS = 30.0;
constexpr int BUFFER_COUNT = 16;
constexpr guint64 POP_TIMEOUT_US = 1000000;

std::string text(const char *s) { return s != nullptr ? std::string(s) : std::string(); }

// Throws on a set GError, freeing it.
void check(GError *&error, const std::string &what) {
  if (error != nullptr) {
    const std::string message = what + " failed: " + error->message;
    g_clear_error(&error);
    throw std::runtime_error(message);
  }
}

// Returns the GError message (empty = success), freeing it.
std::string take(GError *&error) {
  if (error == nullptr) {
    return {};
  }
  std::string message = error->message;
  g_clear_error(&error);
  return message;
}

} // namespace

class GenicamCameraNode : public mrp_camera_common::CameraNode {
public:
  GenicamCameraNode() : CameraNode("camera_node") {
    // Parameter names match the other MRP camera drivers where they overlap.
    serial_ = declare_parameter<std::string>("serial_number", "", read_only());
    device_id_ = declare_parameter<std::string>("device_id", "",
                                                read_only("Aravis device id or IP address"));
    transport_ =
        declare_parameter<std::string>("transport", "any", read_only("any, gige, usb3 or fake"));
    width_ = static_cast<int>(declare_parameter<int64_t>(
        "image_width", DEFAULT_WIDTH,
        read_only_int(0, MAX_IMAGE_DIMENSION,
                      "output width; 0 with image_height 0 = camera size")));
    height_ = static_cast<int>(declare_parameter<int64_t>(
        "image_height", DEFAULT_HEIGHT,
        read_only_int(0, MAX_IMAGE_DIMENSION,
                      "output height; 0 with image_width 0 = camera size")));
    fps_ = declare_parameter<double>("fps", DEFAULT_FPS, read_only());
    pixel_format_ = declare_parameter<std::string>("pixel_format", "", read_only());
    exposure_ms_ = declare_parameter<double>("exposure_ms", 0.0, read_only("0 = automatic"));
    auto_exposure_ = declare_parameter<bool>("auto_exposure", true, read_only());
    gain_db_ = declare_parameter<double>("gain_db", -1.0, read_only("negative = automatic"));
    auto_gain_ = declare_parameter<bool>("auto_gain", false, read_only());
    auto_white_balance_ = declare_parameter<bool>("auto_white_balance", true, read_only());
    user_set_ = declare_parameter<std::string>("user_set", "", read_only());
    features_ = declare_parameter<std::vector<std::string>>(
        "features", std::vector<std::string>{}, read_only("GenICam Name=Value, applied last"));
    packet_size_ = static_cast<int>(declare_parameter<int64_t>(
        "packet_size", 0, read_only_int(0, 65535, "GigE packet size; 0 = negotiate")));
    packet_delay_ns_ = declare_parameter<int64_t>(
        "packet_delay_ns", 0, read_only_int(0, std::numeric_limits<int32_t>::max()));
    frame_id_ = declare_parameter<std::string>("frame_id", "camera_link", read_only());
    jpeg_quality_ = static_cast<int>(declare_parameter<int64_t>(
        "jpeg_quality", mrp_camera_common::DEFAULT_JPEG_QUALITY, read_only_int(1, 100)));
    startup_timeout_s_ = declare_parameter<double>("startup_timeout_s", 30.0, read_only());

    if (!std::isfinite(fps_) || fps_ <= 0.0) {
      throw std::invalid_argument("fps must be finite and positive");
    }
    if ((width_ == 0) != (height_ == 0)) {
      throw std::invalid_argument("set both image_width and image_height, or both to 0 (keep)");
    }
    if (!camera_genicam::transport_protocol(transport_, protocol_)) {
      throw std::invalid_argument("transport must be any, gige, usb3 or fake");
    }
    if (!std::isfinite(startup_timeout_s_) || startup_timeout_s_ < 0.0) {
      throw std::invalid_argument("startup_timeout_s must be finite and nonnegative");
    }
    if (!std::isfinite(exposure_ms_ * 1000.0) || exposure_ms_ < 0.0) {
      throw std::invalid_argument(
          "exposure_ms must be finite, nonnegative and fit in microseconds");
    }
    if (!std::isfinite(gain_db_)) {
      throw std::invalid_argument("gain_db must be finite");
    }
    std::vector<camera_genicam::FeatureSetting> parsed;
    for (const auto &entry : features_) {
      camera_genicam::FeatureSetting setting;
      const std::string error = camera_genicam::parse_feature(entry, setting);
      if (!error.empty()) {
        throw std::invalid_argument(error);
      }
      parsed.push_back(setting);
    }

    if (protocol_ == "Fake") {
      arv_enable_interface("Fake"); // in-process simulated GigE camera, for tests and demos
    }
    publisher_ = create_publisher<sensor_msgs::msg::CompressedImage>(
        "image/compressed", mrp_camera_common::image_qos());
    try {
      open_camera();
      configure(parsed);
      start_stream();
      stream_id_ = add_stream("color", fps_);
      start_capture([this]() { capture_loop(); });
    } catch (...) {
      close_camera(); // release control of the camera for the next start
      throw;
    }
  }

  ~GenicamCameraNode() override {
    stop_capture();
    close_camera();
  }

  GenicamCameraNode(const GenicamCameraNode &) = delete;
  GenicamCameraNode &operator=(const GenicamCameraNode &) = delete;
  GenicamCameraNode(GenicamCameraNode &&) = delete;
  GenicamCameraNode &operator=(GenicamCameraNode &&) = delete;

private:
  std::vector<camera_genicam::CameraEntry> list_cameras() {
    arv_update_device_list();
    std::vector<camera_genicam::CameraEntry> result;
    const unsigned int n = arv_get_n_devices();
    for (unsigned int i = 0; i < n; ++i) {
      result.push_back({text(arv_get_device_id(i)), text(arv_get_device_vendor(i)),
                        text(arv_get_device_model(i)), text(arv_get_device_serial_nbr(i)),
                        text(arv_get_device_address(i)), text(arv_get_device_protocol(i))});
    }
    return result;
  }

  void open_camera() {
    // GigE discovery is a broadcast; a camera that just powered up needs a few
    // seconds (DHCP/LLA) before it answers, so keep looking until the timeout.
    const auto started = std::chrono::steady_clock::now();
    const auto timeout = std::chrono::duration<double>(startup_timeout_s_);
    std::vector<camera_genicam::CameraEntry> cameras;
    std::string error;
    int index = -1;
    while (true) {
      cameras = list_cameras();
      index = camera_genicam::select_camera(cameras, protocol_, serial_, device_id_, error);
      if (index >= 0 || std::chrono::steady_clock::now() - started >= timeout || !rclcpp::ok()) {
        break;
      }
      RCLCPP_INFO_THROTTLE(get_logger(), *get_clock(), 5000, "Waiting for camera: %s",
                           error.c_str());
      std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }
    for (const auto &cam : cameras) {
      RCLCPP_INFO(get_logger(), "Found %s %s (serial %s, %s %s, id '%s')", cam.vendor.c_str(),
                  cam.model.c_str(), cam.serial.c_str(), cam.protocol.c_str(), cam.address.c_str(),
                  cam.id.c_str());
    }
    if (index < 0) {
      throw std::runtime_error(error +
                               ". GigE: is the camera powered, in the subnet of a host network "
                               "card, and does the container use "
                               "host networking? Check with `arv-tool-0.8` in the container.");
    }

    const auto &chosen = cameras[static_cast<size_t>(index)];
    GError *gerror = nullptr;
    camera_ = arv_camera_new(chosen.id.c_str(), &gerror);
    if (camera_ == nullptr || gerror != nullptr) {
      const std::string reason = take(gerror);
      if (camera_ != nullptr) {
        g_object_unref(camera_);
        camera_ = nullptr;
      }
      throw std::runtime_error("Opening " + chosen.id + " failed: " + reason +
                               (chosen.protocol == "GigEVision"
                                    ? ". Another application or host may control the camera."
                                    : ""));
    }
    opened_ = chosen;
    set_hardware_id(chosen.serial.empty() ? chosen.id : chosen.serial);
    // GigE: the heartbeat thread reports when the camera stops answering or
    // another host takes control; exit so the container restarts cleanly.
    control_lost_handler_ = g_signal_connect(arv_camera_get_device(camera_), "control-lost",
                                             G_CALLBACK(&GenicamCameraNode::on_control_lost), this);
    RCLCPP_INFO(get_logger(), "Opened %s %s (serial %s, %s %s)", chosen.vendor.c_str(),
                chosen.model.c_str(), chosen.serial.c_str(), chosen.protocol.c_str(),
                chosen.address.c_str());
  }

  static void on_control_lost(ArvDevice * /*device*/, gpointer self) {
    static_cast<GenicamCameraNode *>(self)->control_lost_ = true;
  }

  void warn_unless_ok(GError *&error, const std::string &what) {
    const std::string reason = take(error);
    if (!reason.empty()) {
      RCLCPP_WARN(get_logger(), "%s: %s", what.c_str(), reason.c_str());
    }
  }

  bool available(const char *feature) {
    GError *error = nullptr;
    const bool yes = arv_camera_is_feature_available(camera_, feature, &error) != FALSE;
    g_clear_error(&error);
    return yes;
  }

  void configure(const std::vector<camera_genicam::FeatureSetting> &features) {
    GError *error = nullptr;

    // Order: stored user set, then this node's parameters, then `features`, so
    // free-form features can override anything.
    if (!user_set_.empty()) {
      arv_camera_set_string(camera_, "UserSetSelector", user_set_.c_str(), &error);
      check(error, "UserSetSelector=" + user_set_);
      arv_camera_execute_command(camera_, "UserSetLoad", &error);
      check(error, "UserSetLoad of " + user_set_);
      RCLCPP_INFO(get_logger(), "Loaded camera user set %s", user_set_.c_str());
    }

    // A camera left in trigger mode (by another tool) would never send a frame.
    arv_camera_clear_triggers(camera_, &error);
    warn_unless_ok(error, "Switching triggers off");
    arv_camera_set_acquisition_mode(camera_, ARV_ACQUISITION_MODE_CONTINUOUS, &error);
    check(error, "AcquisitionMode=Continuous");

    guint n_formats = 0;
    const std::unique_ptr<const char *, decltype(&g_free)> formats(
        arv_camera_dup_available_pixel_formats_as_strings(camera_, &n_formats, &error), g_free);
    check(error, "Reading the pixel formats");
    std::vector<std::string> offered;
    for (guint i = 0; i < n_formats; ++i) {
      offered.push_back(text(formats.get()[i]));
    }
    std::string reason;
    const std::string chosen = camera_genicam::choose_pixel_format(offered, pixel_format_, reason);
    if (chosen.empty()) {
      throw std::runtime_error(reason);
    }

    if (arv_camera_is_gv_device(camera_) != FALSE) {
      // Largest packet the network path carries (jumbo frames when the NIC MTU
      // allows), or a fixed size; a packet delay spreads bursts of several cameras.
      if (packet_size_ > 0) {
        arv_camera_gv_set_packet_size(camera_, packet_size_, &error);
        check(error, "GevSCPSPacketSize=" + std::to_string(packet_size_));
      } else {
        const guint size = arv_camera_gv_auto_packet_size(camera_, &error);
        warn_unless_ok(error, "Negotiating the GigE packet size");
        RCLCPP_INFO(get_logger(), "GigE packet size %u bytes", size);
      }
      if (packet_delay_ns_ > 0) {
        arv_camera_gv_set_packet_delay(camera_, packet_delay_ns_, &error);
        warn_unless_ok(error, "Setting the GigE packet delay");
      }
    }

    // Keep the camera's current region (full sensor by default, or what the user
    // set / features choose); the output is resized to image_width x image_height.
    arv_camera_set_pixel_format_from_string(camera_, chosen.c_str(), &error);
    check(error, "PixelFormat=" + chosen);

    if (arv_camera_is_frame_rate_available(camera_, &error) != FALSE) {
      double min = 0.0;
      double max = 0.0;
      arv_camera_get_frame_rate_bounds(camera_, &min, &max, &error);
      g_clear_error(&error);
      arv_camera_set_frame_rate(camera_, fps_, &error);
      warn_unless_ok(error, "Setting the frame rate");
      if (max > 0.0 && fps_ > max) {
        RCLCPP_WARN(get_logger(),
                    "Requested %.2f FPS, the camera allows at most %.2f at this exposure and "
                    "region",
                    fps_, max);
      }
    } else {
      g_clear_error(&error);
      RCLCPP_WARN(get_logger(), "The camera has no frame rate control; it runs at its own rate");
    }

    bool exposure_auto_active = false;
    if (exposure_ms_ > 0.0) {
      if (arv_camera_is_exposure_auto_available(camera_, &error) != FALSE) {
        arv_camera_set_exposure_time_auto(camera_, ARV_AUTO_OFF, &error);
        warn_unless_ok(error, "ExposureAuto=Off");
      }
      g_clear_error(&error);
      arv_camera_set_exposure_time(camera_, exposure_ms_ * 1000.0, &error);
      check(error, "Setting the exposure time");
    } else if (arv_camera_is_exposure_auto_available(camera_, &error) != FALSE) {
      arv_camera_set_exposure_time_auto(
          camera_, auto_exposure_ ? ARV_AUTO_CONTINUOUS : ARV_AUTO_OFF, &error);
      const std::string failed = take(error);
      if (failed.empty()) {
        exposure_auto_active = auto_exposure_;
      } else {
        RCLCPP_WARN(get_logger(), "auto_exposure: %s", failed.c_str());
      }
    } else {
      g_clear_error(&error);
      if (auto_exposure_) {
        RCLCPP_WARN(get_logger(), "The camera has no automatic exposure; set exposure_ms");
      }
    }

    if (gain_db_ >= 0.0) {
      if (arv_camera_is_gain_auto_available(camera_, &error) != FALSE) {
        arv_camera_set_gain_auto(camera_, ARV_AUTO_OFF, &error);
        warn_unless_ok(error, "GainAuto=Off");
      }
      g_clear_error(&error);
      arv_camera_set_gain(camera_, gain_db_, &error);
      check(error, "Setting the gain");
    } else if (arv_camera_is_gain_auto_available(camera_, &error) != FALSE) {
      arv_camera_set_gain_auto(camera_, auto_gain_ ? ARV_AUTO_CONTINUOUS : ARV_AUTO_OFF, &error);
      warn_unless_ok(error, "auto_gain");
    } else {
      g_clear_error(&error);
    }

    const bool color = chosen.rfind("Mono", 0) != 0;
    if (color && available("BalanceWhiteAuto")) {
      arv_camera_set_string(camera_, "BalanceWhiteAuto", auto_white_balance_ ? "Continuous" : "Off",
                            &error);
      warn_unless_ok(error, "auto_white_balance");
    }

    for (const auto &feature : features) {
      apply_feature(feature); // last, so free-form features win over the parameters above
    }

    const char *active_format = arv_camera_get_pixel_format_as_string(camera_, &error);
    check(error, "Reading the active PixelFormat name");
    pixel_format_set_ = text(active_format);
    if (!camera_genicam::is_supported_pixel_format(pixel_format_set_)) {
      throw std::runtime_error("Unsupported active PixelFormat: '" + pixel_format_set_ + "'");
    }
    pixel_format_id_ = arv_camera_get_pixel_format(camera_, &error);
    check(error, "Reading the active PixelFormat value");

    gint x = 0;
    gint y = 0;
    arv_camera_get_region(camera_, &x, &y, &sensor_width_, &sensor_height_, &error);
    check(error, "Reading the image region");
    const double rate = arv_camera_get_frame_rate(camera_, &error);
    g_clear_error(&error);
    const double exposure_us = arv_camera_get_exposure_time(camera_, &error);
    g_clear_error(&error);
    RCLCPP_INFO(get_logger(),
                "Camera image %dx%d at (%d,%d) %s, output %dx%d @ %.2f FPS (camera %.2f), exposure "
                "%.2f ms%s, JPEG q=%d",
                sensor_width_, sensor_height_, x, y, pixel_format_set_.c_str(),
                width_ > 0 ? width_ : sensor_width_, height_ > 0 ? height_ : sensor_height_, fps_,
                rate, exposure_us / 1000.0, exposure_auto_active ? " (auto)" : "", jpeg_quality_);
  }

  void apply_feature(const camera_genicam::FeatureSetting &feature) {
    GError *error = nullptr;
    ArvDevice *device = arv_camera_get_device(camera_);
    if (feature.is_command) {
      arv_device_execute_command(device, feature.name.c_str(), &error);
      check(error, "Executing feature " + feature.name);
      return;
    }
    ArvGcNode *node = arv_device_get_feature(device, feature.name.c_str());
    if (node == nullptr || ARV_IS_GC_FEATURE_NODE(node) == FALSE) {
      throw std::runtime_error("The camera has no feature '" + feature.name +
                               "' (list them with `arv-tool-0.8 "
                               "features`)");
    }
    arv_gc_feature_node_set_value_from_string(ARV_GC_FEATURE_NODE(node), feature.value.c_str(),
                                              &error);
    check(error, "Setting feature " + feature.name + "=" + feature.value);
  }

  void start_stream() {
    GError *error = nullptr;
    stream_ = arv_camera_create_stream(camera_, nullptr, nullptr, &error);
    if (stream_ == nullptr || error != nullptr) {
      throw std::runtime_error("Creating the stream failed: " + take(error));
    }
    const guint payload = arv_camera_get_payload(camera_, &error);
    check(error, "Reading the payload size");
    for (int i = 0; i < BUFFER_COUNT; ++i) {
      arv_stream_push_buffer(stream_, arv_buffer_new(payload, nullptr));
    }
    arv_camera_start_acquisition(camera_, &error);
    check(error, "AcquisitionStart");
    acquiring_ = true;
  }

  void close_camera() {
    GError *error = nullptr;
    if (camera_ != nullptr && acquiring_) {
      arv_camera_stop_acquisition(camera_, &error);
      g_clear_error(&error);
      acquiring_ = false;
    }
    if (stream_ != nullptr) {
      g_object_unref(stream_); // also frees the buffers still queued in the stream
      stream_ = nullptr;
    }
    if (camera_ != nullptr && control_lost_handler_ != 0) {
      // The device can outlive camera_ (Aravis holds references); never call back
      // into a destroyed node.
      g_signal_handler_disconnect(arv_camera_get_device(camera_), control_lost_handler_);
      control_lost_handler_ = 0;
    }
    if (camera_ != nullptr) {
      g_object_unref(camera_); // releases GigE control so the next start can take it
      camera_ = nullptr;
    }
  }

  // Host time of the frame: Aravis' system timestamp (taken when the frame starts
  // arriving, CLOCK_REALTIME like ROS system time), else the time it was popped.
  builtin_interfaces::msg::Time frame_stamp(ArvBuffer *buffer) {
    const guint64 system_ns = arv_buffer_get_system_timestamp(buffer);
    if (system_ns > 0 && !get_clock()->ros_time_is_active() &&
        system_ns < static_cast<guint64>(std::numeric_limits<int64_t>::max())) {
      return rclcpp::Time(static_cast<int64_t>(system_ns), RCL_SYSTEM_TIME);
    }
    return now();
  }

  void capture_loop() {
    const cv::Size output(width_, height_);
    while (capture_running()) {
      report_stats([this]() {
        guint64 completed = 0;
        guint64 failures = 0;
        guint64 underruns = 0;
        arv_stream_get_statistics(stream_, &completed, &failures, &underruns);
        return "stream failures " + std::to_string(failures) + ", underruns " +
               std::to_string(underruns) + " (total)";
      });
      if (control_lost_) {
        throw std::runtime_error("Lost control of the camera " + opened_.id);
      }
      const auto recycle = [this](ArvBuffer *buffer) { arv_stream_push_buffer(stream_, buffer); };
      std::unique_ptr<ArvBuffer, decltype(recycle)> buffer(
          arv_stream_timeout_pop_buffer(stream_, POP_TIMEOUT_US), recycle);
      if (buffer == nullptr) {
        RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "Waiting for frames");
        continue;
      }

      if (arv_buffer_get_status(buffer.get()) != ARV_BUFFER_STATUS_SUCCESS ||
          arv_buffer_get_payload_type(buffer.get()) != ARV_BUFFER_PAYLOAD_TYPE_IMAGE) {
        frame_dropped(stream_id_); // missing packets or a non-image payload
        continue;
      }

      sensor_msgs::msg::CompressedImage msg;
      msg.header.stamp = frame_stamp(buffer.get());
      size_t size = 0;
      const void *data = arv_buffer_get_image_data(buffer.get(), &size);
      const int w = arv_buffer_get_image_width(buffer.get());
      const int h = arv_buffer_get_image_height(buffer.get());
      std::string error;
      cv::Mat image;
      if (arv_buffer_get_image_pixel_format(buffer.get()) != pixel_format_id_) {
        error = "frame has an unexpected pixel format";
      } else {
        error = camera_genicam::to_8bit_image(data, size, w, h, pixel_format_set_, image);
      }
      if (error.empty()) {
        // Crop to the output aspect ratio, then scale: never distort the image.
        const cv::Mat out = width_ > 0 ? mrp_camera_common::fit_to_size(image, output) : image;
        if (!mrp_camera_common::encode_jpeg(out, jpeg_quality_, msg.data)) {
          error = "JPEG encoding failed";
        }
      }
      buffer.reset(); // image may reference the buffer until encoding finishes
      if (!error.empty()) {
        frame_dropped(stream_id_);
        RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "Dropping frame: %s", error.c_str());
        continue;
      }
      msg.header.frame_id = frame_id_;
      msg.format = mrp_camera_common::JPEG_FORMAT;
      const auto bytes = msg.data.size();
      publisher_->publish(msg);
      frame_published(stream_id_, bytes);
    }
  }

  // Parameters
  std::string serial_;
  std::string device_id_;
  std::string transport_;
  std::string protocol_;
  int width_;
  int height_;
  double fps_;
  std::string pixel_format_;
  double exposure_ms_;
  bool auto_exposure_;
  double gain_db_;
  bool auto_gain_;
  bool auto_white_balance_;
  std::string user_set_;
  std::vector<std::string> features_;
  int packet_size_;
  int64_t packet_delay_ns_;
  std::string frame_id_;
  int jpeg_quality_;
  double startup_timeout_s_;

  // Camera state
  ArvCamera *camera_ = nullptr;
  ArvStream *stream_ = nullptr;
  bool acquiring_ = false;
  camera_genicam::CameraEntry opened_;
  std::string pixel_format_set_;
  ArvPixelFormat pixel_format_id_ = 0;
  gulong control_lost_handler_ = 0;
  gint sensor_width_ = 0;
  gint sensor_height_ = 0;

  rclcpp::Publisher<sensor_msgs::msg::CompressedImage>::SharedPtr publisher_;
  StreamId stream_id_{};
  std::atomic<bool> control_lost_{false};
};

int main(int argc, char **argv) {
  return mrp_camera_common::run_camera_node<GenicamCameraNode>(argc, argv, [] { arv_shutdown(); });
}
