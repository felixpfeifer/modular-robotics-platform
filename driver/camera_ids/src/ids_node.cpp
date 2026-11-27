// Lean IDS uEye driver (IDS Software Suite / uEye API). Works for uEye "UI"
// cameras on USB 2, USB 3 and GigE: they are not USB3 Vision / GigE Vision
// devices and need the uEye daemons (ueyeusbd, ueyeethd), which also upload the
// camera firmware. Publishes JPEG on image/compressed, a drop-in replacement
// for camera_opencv / camera_realsense.

#include <camera_ids/ids_utils.hpp>

#include <mrp_camera_common/camera_node.hpp>
#include <mrp_camera_common/image.hpp>
#include <mrp_camera_common/parameters.hpp>

#include <ueye.h>

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
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
constexpr int DEFAULT_FPS = 30;
constexpr int BUFFER_COUNT = 8;
constexpr UINT WAIT_TIMEOUT_MS = 1000;

std::string field(const IS_CHAR *text, size_t size) {
  return std::string(text, strnlen(text, size));
}

int declare_int(rclcpp::Node &node, const std::string &name, int default_value, int64_t from,
                int64_t to, const std::string &description = {}) {
  return static_cast<int>(
      node.declare_parameter<int64_t>(name, default_value, read_only_int(from, to, description)));
}

} // namespace

class IdsCameraNode : public mrp_camera_common::CameraNode {
public:
  IdsCameraNode() : CameraNode("camera_node") {
    // Parameter names match camera_opencv/camera_realsense where they overlap.
    serial_ = declare_parameter<std::string>("serial_number", "", read_only());
    camera_id_ = declare_int(*this, "camera_id", 0, 0, 255, "0 = any");
    width_ = declare_int(*this, "image_width", DEFAULT_WIDTH, 0, MAX_IMAGE_DIMENSION,
                         "output width; 0 with image_height 0 = sensor size");
    height_ = declare_int(*this, "image_height", DEFAULT_HEIGHT, 0, MAX_IMAGE_DIMENSION,
                          "output height; 0 with image_width 0 = sensor size");
    fps_ = declare_parameter<double>("fps", DEFAULT_FPS, read_only());
    frame_id_ = declare_parameter<std::string>("frame_id", "camera_link", read_only());
    jpeg_quality_ =
        declare_int(*this, "jpeg_quality", mrp_camera_common::DEFAULT_JPEG_QUALITY, 1, 100);
    parameter_file_ = declare_parameter<std::string>("parameter_file", "",
                                                     read_only("uEye Cockpit .ini, loaded first"));
    pixel_clock_mhz_ = declare_int(*this, "pixel_clock_mhz", 0, 0, 1000, "0 = camera default");
    exposure_ms_ = declare_parameter<double>("exposure_ms", 0.0, read_only("0 = automatic"));
    auto_exposure_ = declare_parameter<bool>("auto_exposure", true, read_only());
    gain_ = declare_int(*this, "gain", -1, -1, 100, "hardware gain 0-100; -1 = automatic");
    auto_gain_ = declare_parameter<bool>("auto_gain", false, read_only());
    auto_white_balance_ = declare_parameter<bool>("auto_white_balance", true, read_only());
    startup_timeout_s_ = declare_parameter<double>("startup_timeout_s", 30.0, read_only());

    if (!std::isfinite(fps_) || fps_ <= 0.0) {
      throw std::invalid_argument("fps must be finite and positive");
    }
    if ((width_ == 0) != (height_ == 0)) {
      throw std::invalid_argument("set both image_width and image_height, or both to 0 (keep)");
    }
    if (!std::isfinite(startup_timeout_s_) || startup_timeout_s_ < 0.0) {
      throw std::invalid_argument("startup_timeout_s must be finite and nonnegative");
    }
    if (!std::isfinite(exposure_ms_) || exposure_ms_ < 0.0) {
      throw std::invalid_argument("exposure_ms must be finite and nonnegative");
    }

    publisher_ = create_publisher<sensor_msgs::msg::CompressedImage>(
        "image/compressed", mrp_camera_common::image_qos());
    try {
      open_camera();
      configure();
      start_queue();
      stream_id_ = add_stream("color", fps_);
      start_capture([this]() { capture_loop(); });
    } catch (...) {
      close_camera(); // release the camera for the next start
      throw;
    }
  }

  ~IdsCameraNode() override {
    stop_capture();
    close_camera();
  }

  IdsCameraNode(const IdsCameraNode &) = delete;
  IdsCameraNode &operator=(const IdsCameraNode &) = delete;
  IdsCameraNode(IdsCameraNode &&) = delete;
  IdsCameraNode &operator=(IdsCameraNode &&) = delete;

private:
  std::string error_text(INT rc) {
    if (cam_ != 0) {
      INT code = 0;
      IS_CHAR *text = nullptr;
      if (is_GetError(cam_, &code, &text) == IS_SUCCESS && text != nullptr && code != IS_SUCCESS) {
        return std::string(text) + " (code " + std::to_string(code) + ")";
      }
    }
    return "uEye error code " + std::to_string(rc);
  }

  void check(INT rc, const std::string &what) {
    if (rc != IS_SUCCESS) {
      throw std::runtime_error(what + " failed: " + error_text(rc));
    }
  }

  std::vector<camera_ids::CameraEntry> list_cameras() {
    std::vector<camera_ids::CameraEntry> result;
    INT count = 0;
    if (is_GetNumberOfCameras(&count) != IS_SUCCESS || count <= 0) {
      return result;
    }
    // UEYE_CAMERA_LIST ends in a variable-length array; allocate room for `count` entries.
    const size_t bytes =
        sizeof(UEYE_CAMERA_LIST) + static_cast<size_t>(count) * sizeof(UEYE_CAMERA_INFO);
    std::vector<std::max_align_t> storage(bytes / sizeof(std::max_align_t) + 1);
    auto *list = reinterpret_cast<UEYE_CAMERA_LIST *>(storage.data());
    list->dwCount = static_cast<decltype(list->dwCount)>(count);
    if (is_GetCameraList(list) != IS_SUCCESS) {
      return result;
    }
    const auto n = std::min<size_t>(static_cast<size_t>(list->dwCount), static_cast<size_t>(count));
    for (size_t i = 0; i < n; ++i) {
      const UEYE_CAMERA_INFO &info = list->uci[i];
      camera_ids::CameraEntry entry;
      entry.serial = field(info.SerNo, sizeof(info.SerNo));
      entry.model = field(info.Model, sizeof(info.Model));
      entry.camera_id = static_cast<int>(info.dwCameraID);
      entry.device_id = static_cast<int>(info.dwDeviceID);
      entry.in_use = info.dwInUse != 0;
      result.push_back(entry);
    }
    return result;
  }

  void open_camera() {
    // The daemons need a few seconds to upload the firmware after they (or the
    // camera) start; the camera re-enumerates with its real USB ID meanwhile.
    const auto started = std::chrono::steady_clock::now();
    const auto timeout = std::chrono::duration<double>(startup_timeout_s_);
    std::vector<camera_ids::CameraEntry> cameras;
    std::string error;
    int index = -1;
    while (true) {
      cameras = list_cameras();
      index = camera_ids::select_camera(cameras, serial_, camera_id_, error);
      if (index >= 0 || std::chrono::steady_clock::now() - started >= timeout || !rclcpp::ok()) {
        break;
      }
      RCLCPP_INFO_THROTTLE(get_logger(), *get_clock(), 5000, "Waiting for IDS camera: %s",
                           error.c_str());
      std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }
    for (const auto &cam : cameras) {
      RCLCPP_INFO(get_logger(), "Found %s (serial %s, camera ID %d, device ID %d%s)",
                  cam.model.c_str(), cam.serial.c_str(), cam.camera_id, cam.device_id,
                  cam.in_use ? ", in use" : "");
    }
    if (index < 0) {
      throw std::runtime_error(error + ". Is the camera connected, is the uEye USB/ETH daemon "
                                       "running, and (GigE) does the camera "
                                       "have a valid IP address?");
    }

    const auto &chosen = cameras[static_cast<size_t>(index)];
    HIDS handle = static_cast<HIDS>(static_cast<uint32_t>(chosen.device_id) | IS_USE_DEVICE_ID);
    const INT rc = is_InitCamera(&handle, nullptr);
    if (rc != IS_SUCCESS) {
      throw std::runtime_error(
          "is_InitCamera for " + chosen.serial + " failed with code " + std::to_string(rc) +
          (rc == IS_STARTER_FW_UPLOAD_NEEDED ? " (camera needs a newer starter firmware; update it "
                                               "with IDS Camera Manager)"
                                             : ""));
    }
    cam_ = handle;
    serial_open_ = chosen.serial;
    set_hardware_id(chosen.serial);
    RCLCPP_INFO(get_logger(), "Opened %s (serial %s)", chosen.model.c_str(), chosen.serial.c_str());
  }

  void configure() {
    if (!parameter_file_.empty()) {
      // Camera settings saved from IDS uEye Cockpit (.ini): exposure, binning, AOI, ...
      std::wstring path;
      if (!camera_ids::ascii_to_wide(parameter_file_, path)) {
        throw std::invalid_argument("parameter_file must be an ASCII path");
      }
      check(is_ParameterSet(cam_, IS_PARAMETERSET_CMD_LOAD_FILE, path.data(), 0),
            "Loading parameter_file " + parameter_file_);
      RCLCPP_INFO(get_logger(), "Loaded camera parameters from %s", parameter_file_.c_str());
    }

    SENSORINFO sensor{};
    check(is_GetSensorInfo(cam_, &sensor), "is_GetSensorInfo");
    mono_ = sensor.nColorMode == IS_COLORMODE_MONOCHROME;
    check(is_SetColorMode(cam_, mono_ ? IS_CM_MONO8 : IS_CM_BGR8_PACKED), "is_SetColorMode");
    bits_per_pixel_ = mono_ ? 8 : 24;
    RCLCPP_INFO(get_logger(), "Sensor %s: %ux%u, %s",
                field(sensor.strSensorName, sizeof(sensor.strSensorName)).c_str(),
                static_cast<unsigned>(sensor.nMaxWidth), static_cast<unsigned>(sensor.nMaxHeight),
                mono_ ? "monochrome" : "color");

    // Keep the complete sensor view (or the AOI loaded from parameter_file).
    IS_RECT current{};
    check(is_AOI(cam_, IS_AOI_IMAGE_GET_AOI, &current, sizeof(current)), "is_AOI get");
    image_width_ = current.s32Width;
    image_height_ = current.s32Height;

    // The pixel clock bounds the frame rate; IDS defaults are often low.
    UINT clock_range[3] = {0, 0, 0};
    if (is_PixelClock(cam_, IS_PIXELCLOCK_CMD_GET_RANGE, clock_range, sizeof(clock_range)) ==
        IS_SUCCESS) {
      if (pixel_clock_mhz_ > 0) {
        auto clock = static_cast<UINT>(pixel_clock_mhz_);
        if (clock < clock_range[0] || clock > clock_range[1]) {
          throw std::runtime_error("pixel_clock_mhz must be in [" + std::to_string(clock_range[0]) +
                                   ", " + std::to_string(clock_range[1]) + "] for this camera");
        }
        check(is_PixelClock(cam_, IS_PIXELCLOCK_CMD_SET, &clock, sizeof(clock)),
              "is_PixelClock set");
      }
    }
    UINT clock = 0;
    warn_unless_ok(is_PixelClock(cam_, IS_PIXELCLOCK_CMD_GET, &clock, sizeof(clock)),
                   "Reading the pixel clock");

    double actual_fps = 0.0;
    check(is_SetFrameRate(cam_, fps_, &actual_fps), "is_SetFrameRate");
    if (std::abs(actual_fps - fps_) > 0.5) {
      RCLCPP_WARN(get_logger(),
                  "Camera runs at %.2f FPS instead of %.2f (pixel clock %u MHz, range %u-%u). "
                  "Raise pixel_clock_mhz "
                  "or lower the resolution/fps.",
                  actual_fps, fps_, clock, clock_range[0], clock_range[1]);
    }

    double off = 0.0;
    double on = 1.0;
    double unused = 0.0;
    if (exposure_ms_ > 0.0) {
      warn_unless_ok(is_SetAutoParameter(cam_, IS_SET_ENABLE_AUTO_SHUTTER, &off, &unused),
                     "Switching auto exposure off");
      double exposure = exposure_ms_;
      check(is_Exposure(cam_, IS_EXPOSURE_CMD_SET_EXPOSURE, &exposure, sizeof(exposure)),
            "is_Exposure");
    } else {
      warn_unless_ok(is_SetAutoParameter(cam_, IS_SET_ENABLE_AUTO_SHUTTER,
                                         auto_exposure_ ? &on : &off, &unused),
                     "auto_exposure");
    }
    if (gain_ >= 0) {
      warn_unless_ok(is_SetAutoParameter(cam_, IS_SET_ENABLE_AUTO_GAIN, &off, &unused),
                     "Switching auto gain off");
      check(is_SetHardwareGain(cam_, gain_, IS_IGNORE_PARAMETER, IS_IGNORE_PARAMETER,
                               IS_IGNORE_PARAMETER),
            "is_SetHardwareGain");
    } else {
      warn_unless_ok(
          is_SetAutoParameter(cam_, IS_SET_ENABLE_AUTO_GAIN, auto_gain_ ? &on : &off, &unused),
          "auto_gain");
    }
    if (!mono_) {
      warn_unless_ok(is_SetAutoParameter(cam_, IS_SET_ENABLE_AUTO_WHITEBALANCE,
                                         auto_white_balance_ ? &on : &off, &unused),
                     "auto_white_balance");
    }

    double exposure = 0.0;
    warn_unless_ok(is_Exposure(cam_, IS_EXPOSURE_CMD_GET_EXPOSURE, &exposure, sizeof(exposure)),
                   "Reading the exposure time");
    RCLCPP_INFO(get_logger(),
                "Sensor image %dx%d, output %dx%d @ %.2f FPS, pixel clock %u MHz, exposure %.2f "
                "ms%s (JPEG q=%d)",
                image_width_, image_height_, width_ > 0 ? width_ : image_width_,
                height_ > 0 ? height_ : image_height_, actual_fps, clock, exposure,
                exposure_ms_ > 0.0 ? "" : (auto_exposure_ ? " auto" : ""), jpeg_quality_);
  }

  void warn_unless_ok(INT rc, const char *what) {
    if (rc != IS_SUCCESS) {
      RCLCPP_WARN(get_logger(), "%s failed (not supported by this camera?): %s", what,
                  error_text(rc).c_str());
    }
  }

  void start_queue() {
    buffers_.reserve(BUFFER_COUNT);
    for (int i = 0; i < BUFFER_COUNT; ++i) {
      char *memory = nullptr;
      INT id = 0;
      check(is_AllocImageMem(cam_, image_width_, image_height_, bits_per_pixel_, &memory, &id),
            "is_AllocImageMem");
      buffers_.push_back({memory, id});
      check(is_AddToSequence(cam_, memory, id), "is_AddToSequence");
    }
    INT pitch = 0;
    check(is_GetImageMemPitch(cam_, &pitch), "is_GetImageMemPitch");
    pitch_ = pitch;
    check(is_ImageQueue(cam_, IS_IMAGE_QUEUE_CMD_INIT, nullptr, 0), "Initializing the image queue");
    queue_initialized_ = true;
    check(is_CaptureVideo(cam_, IS_DONT_WAIT), "is_CaptureVideo");
  }

  void close_camera() {
    if (cam_ == 0) {
      return;
    }
    is_StopLiveVideo(cam_, IS_FORCE_VIDEO_STOP);
    if (queue_initialized_) {
      is_ImageQueue(cam_, IS_IMAGE_QUEUE_CMD_EXIT, nullptr, 0);
      queue_initialized_ = false;
    }
    is_ClearSequence(cam_);
    for (const auto &buffer : buffers_) {
      is_FreeImageMem(cam_, buffer.memory, buffer.id);
    }
    buffers_.clear();
    is_ExitCamera(cam_);
    cam_ = 0;
  }

  void capture_loop() {
    const int type = mono_ ? CV_8UC1 : CV_8UC3;
    const cv::Size output(width_, height_);
    int transfer_errors = 0;

    while (capture_running()) {
      report_stats([&transfer_errors]() {
        const std::string text = std::to_string(transfer_errors) + " transfer errors";
        transfer_errors = 0;
        return text;
      });
      char *memory = nullptr;
      INT id = 0;
      IMAGEQUEUEWAITBUFFER frame{};
      frame.timeout = WAIT_TIMEOUT_MS;
      frame.ppcMem = &memory;
      frame.pnMemId = &id;
      const INT rc = is_ImageQueue(cam_, IS_IMAGE_QUEUE_CMD_WAIT, &frame, sizeof(frame));
      if (rc != IS_SUCCESS) {
        if (memory != nullptr) {
          // Whether the SDK hands out (and locks) a buffer together with an error is
          // not documented clearly; return it so the queue cannot run dry.
          is_UnlockSeqBuf(cam_, id, memory);
        }
        if (rc == IS_CAPTURE_STATUS) {
          ++transfer_errors; // dropped/incomplete transfer; the next frame usually arrives
          frame_dropped(stream_id_);
        } else {
          RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "Waiting for frames (%s)",
                               error_text(rc).c_str());
        }
        continue;
      }

      const auto unlock = [this, id](char *data) { is_UnlockSeqBuf(cam_, id, data); };
      std::unique_ptr<char, decltype(unlock)> buffer(memory, unlock);

      sensor_msgs::msg::CompressedImage msg;
      msg.header.stamp = now();
      const cv::Mat image(image_height_, image_width_, type, memory, static_cast<size_t>(pitch_));
      // Crop to the output aspect ratio, then scale: never distort the image.
      const cv::Mat out = width_ > 0 ? mrp_camera_common::fit_to_size(image, output) : image;
      const bool ok = mrp_camera_common::encode_jpeg(out, jpeg_quality_, msg.data);
      buffer.reset(); // `out` may reference the buffer until encoding finishes
      if (!ok) {
        frame_dropped(stream_id_);
        RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "Failed to encode frame");
        continue;
      }
      msg.header.frame_id = frame_id_;
      msg.format = mrp_camera_common::JPEG_FORMAT;
      const auto bytes = msg.data.size();
      publisher_->publish(msg);
      frame_published(stream_id_, bytes);
    }
  }

  struct Buffer {
    char *memory;
    INT id;
  };

  // Parameters
  std::string serial_;
  int camera_id_;
  int width_;
  int height_;
  double fps_;
  std::string frame_id_;
  int jpeg_quality_;
  std::string parameter_file_;
  int pixel_clock_mhz_;
  double exposure_ms_;
  bool auto_exposure_;
  int gain_;
  bool auto_gain_;
  bool auto_white_balance_;
  double startup_timeout_s_;

  // Camera state
  HIDS cam_ = 0;
  bool queue_initialized_ = false;
  std::string serial_open_;
  bool mono_ = false;
  int bits_per_pixel_ = 24;
  int image_width_ = 0;
  int image_height_ = 0;
  int pitch_ = 0;
  std::vector<Buffer> buffers_;

  rclcpp::Publisher<sensor_msgs::msg::CompressedImage>::SharedPtr publisher_;
  StreamId stream_id_{};
};

int main(int argc, char **argv) {
  return mrp_camera_common::run_camera_node<IdsCameraNode>(argc, argv);
}
