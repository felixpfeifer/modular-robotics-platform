// Lean RealSense driver: publishes JPEG color (drop-in for camera_opencv) and,
// optionally, lossless PNG depth aligned to the color image. Everything goes out
// as sensor_msgs/CompressedImage so the streams are cheap to record and easy to
// decode for VLA training (cv2.imdecode on the bytes).

#include <camera_realsense/image_utils.hpp>

#include <mrp_camera_common/camera_node.hpp>
#include <mrp_camera_common/image.hpp>
#include <mrp_camera_common/parameters.hpp>

#include <librealsense2/rs.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/camera_info.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>

#include <chrono>
#include <future>
#include <memory>
#include <optional>
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
constexpr int DEFAULT_FPS = 30;
constexpr int WAIT_TIMEOUT_MS = 1000;

std::string device_info(const rs2::device &dev, rs2_camera_info key) {
  return dev.supports(key) ? dev.get_info(key) : "unknown";
}

int declare_int(rclcpp::Node &node, const std::string &name, int default_value, int64_t from,
                int64_t to, const std::string &description = {}) {
  return static_cast<int>(
      node.declare_parameter<int64_t>(name, default_value, read_only_int(from, to, description)));
}

} // namespace

class RealSenseNode : public mrp_camera_common::CameraNode {
public:
  RealSenseNode() : CameraNode("camera_node") {
    // Parameter names match camera_opencv so compose overlays work with either driver.
    serial_ = declare_parameter<std::string>("serial_number", "", read_only());
    width_ = declare_int(*this, "image_width", DEFAULT_WIDTH, 1, MAX_IMAGE_DIMENSION);
    height_ = declare_int(*this, "image_height", DEFAULT_HEIGHT, 1, MAX_IMAGE_DIMENSION);
    fps_ = declare_int(*this, "fps", DEFAULT_FPS, 1, 1000);
    frame_id_ = declare_parameter<std::string>("frame_id", "camera_link", read_only());
    jpeg_quality_ =
        declare_int(*this, "jpeg_quality", mrp_camera_common::DEFAULT_JPEG_QUALITY, 1, 100);

    enable_depth_ = declare_parameter<bool>("enable_depth", false, read_only());
    depth_width_ = declare_int(*this, "depth_width", DEFAULT_WIDTH, 1, MAX_IMAGE_DIMENSION);
    depth_height_ = declare_int(*this, "depth_height", DEFAULT_HEIGHT, 1, MAX_IMAGE_DIMENSION);
    align_depth_ = declare_parameter<bool>("align_depth", true, read_only());
    depth_frame_id_ =
        declare_parameter<std::string>("depth_frame_id", "camera_depth_frame", read_only());
    png_compression_ = declare_int(*this, "png_compression", 1, 0, 9);
    max_depth_mm_ =
        declare_int(*this, "max_depth_mm", 0, 0, 65535, "depth beyond this is set to 0; 0 = off");

    publish_camera_info_ = declare_parameter<bool>("publish_camera_info", true, read_only());
    hardware_timestamps_ = declare_parameter<bool>("hardware_timestamps", true, read_only());

    const auto qos = mrp_camera_common::image_qos();
    color_pub_ = create_publisher<sensor_msgs::msg::CompressedImage>("image/compressed", qos);
    if (publish_camera_info_) {
      color_info_pub_ = create_publisher<sensor_msgs::msg::CameraInfo>("camera_info", qos);
    }
    if (enable_depth_) {
      depth_pub_ = create_publisher<sensor_msgs::msg::CompressedImage>("depth/compressed", qos);
      if (publish_camera_info_) {
        depth_info_pub_ = create_publisher<sensor_msgs::msg::CameraInfo>("depth/camera_info", qos);
      }
    }

    start_pipeline();
    color_stream_ = add_stream("color", fps_);
    if (enable_depth_) {
      depth_stream_ = add_stream("depth", fps_);
    }
    start_capture([this]() { capture_loop(); });
  }

  ~RealSenseNode() override {
    stop_capture();
    if (pipe_) {
      try {
        pipe_->stop();
      } catch (const rs2::error &error) {
        // Already stopped or device gone; nothing left to release.
        RCLCPP_DEBUG(get_logger(), "Stopping the pipeline: %s", error.what());
      }
    }
  }

  RealSenseNode(const RealSenseNode &) = delete;
  RealSenseNode &operator=(const RealSenseNode &) = delete;
  RealSenseNode(RealSenseNode &&) = delete;
  RealSenseNode &operator=(RealSenseNode &&) = delete;

private:
  rs2::device select_device(const rs2::context &ctx) {
    rs2::device_list devices = ctx.query_devices();
    if (devices.size() == 0) {
      throw std::runtime_error("No RealSense device found. Is it plugged in (USB3 port) and is "
                               "/dev/bus/usb accessible?");
    }
    rs2::device chosen;
    for (auto &&dev : devices) {
      const std::string serial = device_info(dev, RS2_CAMERA_INFO_SERIAL_NUMBER);
      RCLCPP_INFO(get_logger(), "Found %s (serial %s, firmware %s, USB %s)",
                  device_info(dev, RS2_CAMERA_INFO_NAME).c_str(), serial.c_str(),
                  device_info(dev, RS2_CAMERA_INFO_FIRMWARE_VERSION).c_str(),
                  device_info(dev, RS2_CAMERA_INFO_USB_TYPE_DESCRIPTOR).c_str());
      if (!chosen && (serial_.empty() || serial == serial_)) {
        chosen = dev;
      }
    }
    if (!chosen) {
      throw std::runtime_error("No RealSense device with serial_number '" + serial_ + "'");
    }
    return chosen;
  }

  void start_pipeline() {
    const rs2::context context;
    rs2::device dev = select_device(context);
    const std::string serial = device_info(dev, RS2_CAMERA_INFO_SERIAL_NUMBER);
    set_hardware_id(serial);
    const std::string usb = device_info(dev, RS2_CAMERA_INFO_USB_TYPE_DESCRIPTOR);
    if (!usb.empty() && usb[0] == '2') {
      RCLCPP_WARN(get_logger(),
                  "Camera is on USB %s: bandwidth is limited, high resolutions/FPS (especially "
                  "with depth) may fail",
                  usb.c_str());
    }

    // Host-synchronised frame timestamps: librealsense maps the sensor clock to
    // the host system clock, which is what ROS time uses (without sim time).
    if (hardware_timestamps_) {
      for (auto &&sensor : dev.query_sensors()) {
        if (sensor.supports(RS2_OPTION_GLOBAL_TIME_ENABLED)) {
          sensor.set_option(RS2_OPTION_GLOBAL_TIME_ENABLED, 1.0F);
        }
      }
    }

    rs2::config cfg;
    cfg.enable_device(serial);
    cfg.enable_stream(RS2_STREAM_COLOR, width_, height_, RS2_FORMAT_BGR8, fps_);
    if (enable_depth_) {
      cfg.enable_stream(RS2_STREAM_DEPTH, depth_width_, depth_height_, RS2_FORMAT_Z16, fps_);
    }
    pipe_ = std::make_unique<rs2::pipeline>(context);
    if (!cfg.can_resolve(*pipe_)) {
      throw std::runtime_error("Camera cannot provide the requested profile (color " +
                               std::to_string(width_) + "x" + std::to_string(height_) +
                               (enable_depth_ ? ", depth " + std::to_string(depth_width_) + "x" +
                                                    std::to_string(depth_height_)
                                              : std::string()) +
                               " @ " + std::to_string(fps_) +
                               " FPS); refusing to resize training data. List supported modes with "
                               "`rs-enumerate-devices`.");
    }

    rs2::pipeline_profile profile = pipe_->start(cfg);
    auto color_profile = profile.get_stream(RS2_STREAM_COLOR).as<rs2::video_stream_profile>();
    color_info_ = make_camera_info(color_profile.get_intrinsics(), frame_id_);
    RCLCPP_INFO(get_logger(), "Color stream: %dx%d @ %d FPS (JPEG q=%d) on %s",
                color_profile.width(), color_profile.height(), color_profile.fps(), jpeg_quality_,
                serial.c_str());

    if (enable_depth_) {
      auto depth_sensor = profile.get_device().first<rs2::depth_sensor>();
      depth_scale_ = depth_sensor.get_depth_scale();
      auto depth_profile = profile.get_stream(RS2_STREAM_DEPTH).as<rs2::video_stream_profile>();
      if (align_depth_) {
        // Aligned depth lives in the color image's geometry and frame.
        depth_info_ = color_info_;
        align_ = std::make_unique<rs2::align>(RS2_STREAM_COLOR);
      } else {
        depth_info_ = make_camera_info(depth_profile.get_intrinsics(), depth_frame_id_);
      }
      RCLCPP_INFO(get_logger(),
                  "Depth stream: %dx%d @ %d FPS, scale %.6f m/unit, published as uint16 mm PNG%s",
                  depth_profile.width(), depth_profile.height(), depth_profile.fps(), depth_scale_,
                  align_depth_ ? " aligned to color" : "");
    } else {
      RCLCPP_INFO(get_logger(),
                  "Depth disabled (set enable_depth:=true to publish depth/compressed)");
    }
  }

  static sensor_msgs::msg::CameraInfo make_camera_info(const rs2_intrinsics &in,
                                                       const std::string &frame_id) {
    sensor_msgs::msg::CameraInfo info;
    info.header.frame_id = frame_id;
    info.width = static_cast<uint32_t>(in.width);
    info.height = static_cast<uint32_t>(in.height);
    if (in.model == RS2_DISTORTION_KANNALA_BRANDT4) {
      info.distortion_model = "equidistant";
      info.d.assign(in.coeffs, in.coeffs + 4);
    } else {
      // Brown-Conrady variants (and "none" with all-zero coefficients).
      info.distortion_model = "plumb_bob";
      info.d.assign(in.coeffs, in.coeffs + 5);
    }
    info.k = {in.fx, 0.0, in.ppx, 0.0, in.fy, in.ppy, 0.0, 0.0, 1.0};
    info.r = {1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0};
    info.p = {in.fx, 0.0, in.ppx, 0.0, 0.0, in.fy, in.ppy, 0.0, 0.0, 0.0, 1.0, 0.0};
    return info;
  }

  builtin_interfaces::msg::Time stamp_for(const rs2::frame &frame,
                                          const builtin_interfaces::msg::Time &arrival) {
    if (hardware_timestamps_ && !get_clock()->ros_time_is_active() &&
        frame.get_frame_timestamp_domain() == RS2_TIMESTAMP_DOMAIN_GLOBAL_TIME) {
      const auto stamp = camera_realsense::stamp_from_milliseconds(frame.get_timestamp());
      if (stamp) {
        return builtin_interfaces::msg::Time{}.set__sec(stamp->sec).set__nanosec(stamp->nanosec);
      }
    }
    return arrival;
  }

  void capture_loop() {
    rs2::pipeline &pipe = *pipe_; // started in the constructor
    while (capture_running()) {
      report_stats();
      rs2::frameset frames;
      builtin_interfaces::msg::Time arrival;
      try {
        if (!pipe.try_wait_for_frames(&frames, WAIT_TIMEOUT_MS)) {
          RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "Timed out waiting for frames");
          continue;
        }
        arrival = now();
        if (align_) {
          frames = align_->process(frames);
        }
      } catch (const rs2::error &e) {
        RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 2000, "librealsense error: %s", e.what());
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        continue;
      }

      rs2::video_frame color = frames.get_color_frame();
      rs2::depth_frame depth =
          enable_depth_ ? frames.get_depth_frame() : rs2::depth_frame(rs2::frame());

      // Encode depth (PNG is the slower codec) in parallel with color. One short-lived
      // thread per frame costs microseconds, far below the PNG encoding time.
      std::vector<uchar> depth_buf;
      // The future waits on scope exit, so its output buffer must outlive it.
      std::future<bool> depth_job;
      if (depth) {
        depth_job = std::async(std::launch::async, [this, &depth, &depth_buf]() {
          const cv::Mat raw(depth.get_height(), depth.get_width(), CV_16UC1,
                            const_cast<void *>(depth.get_data()),
                            static_cast<size_t>(depth.get_stride_in_bytes()));
          const cv::Mat mm =
              camera_realsense::depth_to_millimetres(raw, depth_scale_, max_depth_mm_);
          return camera_realsense::encode_depth_png(mm, png_compression_, depth_buf);
        });
      }

      if (color) {
        const cv::Mat bgr(color.get_height(), color.get_width(), CV_8UC3,
                          const_cast<void *>(color.get_data()),
                          static_cast<size_t>(color.get_stride_in_bytes()));
        sensor_msgs::msg::CompressedImage msg;
        if (mrp_camera_common::encode_jpeg(bgr, jpeg_quality_, msg.data)) {
          msg.header.stamp = stamp_for(color, arrival);
          msg.header.frame_id = frame_id_;
          msg.format = mrp_camera_common::JPEG_FORMAT;
          publish_info(color_info_pub_, color_info_, msg.header.stamp);
          const auto bytes = msg.data.size();
          color_pub_->publish(msg);
          frame_published(color_stream_, bytes);
        } else {
          frame_dropped(color_stream_);
          RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "Failed to encode color frame");
        }
      }

      if (depth_job.valid()) {
        if (depth_job.get()) {
          sensor_msgs::msg::CompressedImage msg;
          msg.header.stamp = stamp_for(depth, arrival);
          msg.header.frame_id = depth_info_.header.frame_id;
          msg.format = camera_realsense::DEPTH_FORMAT;
          msg.data = std::move(depth_buf);
          publish_info(depth_info_pub_, depth_info_, msg.header.stamp);
          const auto bytes = msg.data.size();
          depth_pub_->publish(msg);
          frame_published(depth_stream_, bytes);
        } else {
          frame_dropped(depth_stream_);
          RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "Failed to encode depth frame");
        }
      }
    }
  }

  static void publish_info(const rclcpp::Publisher<sensor_msgs::msg::CameraInfo>::SharedPtr &pub,
                           const sensor_msgs::msg::CameraInfo &info,
                           const builtin_interfaces::msg::Time &stamp) {
    if (!pub) {
      return;
    }
    auto msg = info;
    msg.header.stamp = stamp;
    pub->publish(msg);
  }

  // Parameters
  std::string serial_;
  int width_ = DEFAULT_WIDTH;
  int height_ = DEFAULT_HEIGHT;
  int fps_ = DEFAULT_FPS;
  std::string frame_id_;
  int jpeg_quality_ = mrp_camera_common::DEFAULT_JPEG_QUALITY;
  bool enable_depth_ = false;
  int depth_width_ = DEFAULT_WIDTH;
  int depth_height_ = DEFAULT_HEIGHT;
  bool align_depth_ = true;
  std::string depth_frame_id_;
  int png_compression_ = 1;
  int max_depth_mm_ = 0;
  bool publish_camera_info_ = true;
  bool hardware_timestamps_ = true;

  // RealSense state
  std::unique_ptr<rs2::pipeline> pipe_; // created in start_pipeline()
  std::unique_ptr<rs2::align> align_;
  float depth_scale_ = 0.001F;
  sensor_msgs::msg::CameraInfo color_info_;
  sensor_msgs::msg::CameraInfo depth_info_;
  StreamId color_stream_{};
  StreamId depth_stream_{};

  // ROS interfaces
  rclcpp::Publisher<sensor_msgs::msg::CompressedImage>::SharedPtr color_pub_;
  rclcpp::Publisher<sensor_msgs::msg::CompressedImage>::SharedPtr depth_pub_;
  rclcpp::Publisher<sensor_msgs::msg::CameraInfo>::SharedPtr color_info_pub_;
  rclcpp::Publisher<sensor_msgs::msg::CameraInfo>::SharedPtr depth_info_pub_;
};

int main(int argc, char **argv) {
  return mrp_camera_common::run_camera_node<RealSenseNode>(argc, argv);
}
