// V4L2 camera driver (OpenCV videoio): publishes JPEG on image/compressed. Opens a
// RealSense color node or any external USB webcam; built-in laptop cameras are
// skipped by the automatic selection.

#include <camera_opencv/camera_utils.hpp>

#include <mrp_camera_common/camera_node.hpp>
#include <mrp_camera_common/image.hpp>
#include <mrp_camera_common/parameters.hpp>

#include <opencv2/videoio.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>

#include <chrono>
#include <climits>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include <fcntl.h>
#include <glob.h>
#include <sys/ioctl.h>
#include <unistd.h>

namespace {

using mrp_camera_common::MAX_IMAGE_DIMENSION;
using mrp_camera_common::read_only;
using mrp_camera_common::read_only_int;

// True if the V4L2 device advertises a human-viewable color pixel format, which
// tells the RealSense color node apart from its depth/IR nodes.
bool has_color_format(int fd) {
  v4l2_fmtdesc desc{};
  desc.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  for (desc.index = 0; ioctl(fd, VIDIOC_ENUM_FMT, &desc) == 0; ++desc.index) {
    if (camera_opencv::is_color_pixel_format(desc.pixelformat)) {
      return true;
    }
  }
  return false;
}

// Walks up from /sys/class/video4linux/<name>/device to the first node with a
// `removable` attribute (the USB device). Unknown counts as external.
bool is_builtin_device(const std::string &dev_path) {
  const std::string name = dev_path.substr(dev_path.rfind('/') + 1);
  const std::string sysfs_device = "/sys/class/video4linux/" + name + "/device";
  char resolved[PATH_MAX];
  if (realpath(sysfs_device.c_str(), resolved) == nullptr) {
    return false;
  }
  std::string path(resolved);
  while (!path.empty() && path != "/") {
    std::ifstream file(path + "/removable");
    if (file.is_open()) {
      std::string value;
      std::getline(file, value);
      return camera_opencv::is_builtin_removable_value(value);
    }
    const auto pos = path.rfind('/');
    if (pos == std::string::npos || pos == 0) {
      break;
    }
    path.resize(pos);
  }
  return false;
}

std::vector<camera_opencv::DeviceCandidate> scan_color_devices() {
  glob_t globbuf{};
  const std::unique_ptr<glob_t, decltype(&globfree)> paths(&globbuf, globfree);
  std::vector<camera_opencv::DeviceCandidate> devices;
  if (glob("/dev/video*", 0, nullptr, &globbuf) != 0) {
    return devices;
  }
  for (std::size_t i = 0; i < globbuf.gl_pathc; ++i) {
    const char *path = globbuf.gl_pathv[i];
    const int fd = ::open(path, O_RDWR | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) {
      continue;
    }
    v4l2_capability cap{};
    const bool color_camera = ioctl(fd, VIDIOC_QUERYCAP, &cap) == 0 &&
                              camera_opencv::is_video_capture_device(cap) && has_color_format(fd);
    ::close(fd);
    if (color_camera) {
      devices.push_back({path, reinterpret_cast<const char *>(cap.card), is_builtin_device(path)});
    }
  }
  return devices;
}

} // namespace

class OpenCvCameraNode : public mrp_camera_common::CameraNode {
public:
  OpenCvCameraNode() : CameraNode("camera_node") {
    // "auto" -> scan V4L2 nodes; an explicit path (e.g. /dev/video0) bypasses detection.
    auto video_device = declare_parameter<std::string>("video_device", "auto",
                                                       read_only("'auto' or a V4L2 device path"));
    width_ = static_cast<int>(declare_parameter<int64_t>(
        "image_width", 640, read_only_int(1, MAX_IMAGE_DIMENSION, "capture width")));
    height_ = static_cast<int>(declare_parameter<int64_t>(
        "image_height", 480, read_only_int(1, MAX_IMAGE_DIMENSION, "capture height")));
    const auto fps = static_cast<int>(
        declare_parameter<int64_t>("fps", 30, read_only_int(1, 1000, "capture frame rate")));
    frame_id_ = declare_parameter<std::string>("frame_id", "camera_link", read_only());
    jpeg_quality_ = static_cast<int>(declare_parameter<int64_t>(
        "jpeg_quality", mrp_camera_common::DEFAULT_JPEG_QUALITY, read_only_int(1, 100)));
    const auto pixel_format = declare_parameter<std::string>(
        "pixel_format", "",
        read_only("V4L2 FOURCC to request, e.g. MJPG or YUYV; empty = OpenCV's choice"));

    std::optional<int> fourcc;
    if (!pixel_format.empty()) {
      fourcc = camera_opencv::fourcc_code(pixel_format);
      if (!fourcc) {
        throw std::invalid_argument("pixel_format must be a 4-character FOURCC such as MJPG");
      }
    }
    if (video_device.empty()) {
      throw std::invalid_argument("video_device must be 'auto' or a device path");
    }
    if (video_device == "auto") {
      video_device = find_camera_device();
    }

    publisher_ = create_publisher<sensor_msgs::msg::CompressedImage>(
        "image/compressed", mrp_camera_common::image_qos());

    if (!cap_.open(video_device, cv::CAP_V4L2)) {
      throw std::runtime_error("Failed to open video device: " + video_device);
    }
    if (fourcc && !cap_.set(cv::CAP_PROP_FOURCC, *fourcc)) {
      RCLCPP_WARN(get_logger(), "The device did not accept pixel_format %s", pixel_format.c_str());
    }
    cap_.set(cv::CAP_PROP_FRAME_WIDTH, width_);
    cap_.set(cv::CAP_PROP_FRAME_HEIGHT, height_);
    cap_.set(cv::CAP_PROP_FPS, fps);

    const double actual_width = cap_.get(cv::CAP_PROP_FRAME_WIDTH);
    const double actual_height = cap_.get(cv::CAP_PROP_FRAME_HEIGHT);
    const double actual_fps = cap_.get(cv::CAP_PROP_FPS);
    const std::string actual_format =
        camera_opencv::fourcc_text(static_cast<int>(cap_.get(cv::CAP_PROP_FOURCC)));
    RCLCPP_INFO(get_logger(),
                "Opened %s: requested %dx%d @ %d FPS, actual %.0fx%.0f @ %.3f FPS %s, JPEG q=%d",
                video_device.c_str(), width_, height_, fps, actual_width, actual_height, actual_fps,
                actual_format.c_str(), jpeg_quality_);
    if (static_cast<int>(actual_width) != width_ || static_cast<int>(actual_height) != height_) {
      throw std::runtime_error(
          "Camera cannot provide the requested dimensions; refusing to resize training data");
    }
    if (!std::isfinite(actual_fps) || std::abs(actual_fps - fps) > 0.1) {
      RCLCPP_WARN(get_logger(), "Camera does not report the requested frame rate; recorder "
                                "preflight will measure and reject it if needed");
    }

    set_hardware_id(video_device);
    stream_ = add_stream("color", fps);
    start_capture([this]() { capture_loop(); });
  }

  ~OpenCvCameraNode() override { stop_capture(); }

  OpenCvCameraNode(const OpenCvCameraNode &) = delete;
  OpenCvCameraNode &operator=(const OpenCvCameraNode &) = delete;
  OpenCvCameraNode(OpenCvCameraNode &&) = delete;
  OpenCvCameraNode &operator=(OpenCvCameraNode &&) = delete;

private:
  std::string find_camera_device() {
    const auto devices = scan_color_devices();
    for (const auto &device : devices) {
      RCLCPP_INFO(get_logger(), "Found %s V4L2 color device %s (%s)",
                  device.builtin ? "built-in" : "external", device.path.c_str(),
                  device.card.c_str());
    }
    const auto chosen = camera_opencv::choose_device(devices);
    if (!chosen) {
      throw std::runtime_error("No external USB color camera found. Set 'video_device' to select "
                               "a device explicitly.");
    }
    RCLCPP_INFO(get_logger(), "Selected %s (%s)", chosen->path.c_str(), chosen->card.c_str());
    return chosen->path;
  }

  // grab() can block (e.g. after an unplug); the base class watchdog then stops the
  // node and, if grab() never returns, exits the process.
  void capture_loop() {
    cv::Mat frame;
    while (capture_running()) {
      report_stats();
      if (!cap_.grab()) {
        RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "Failed to grab frame");
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        continue;
      }
      const auto stamp = now();
      if (!cap_.retrieve(frame)) {
        frame_dropped(stream_);
        RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "Failed to retrieve frame");
        continue;
      }
      // Never resize acquisition data: geometry changes invalidate calibration.
      if (frame.cols != width_ || frame.rows != height_) {
        frame_dropped(stream_);
        RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 5000,
                              "Captured %dx%d but profile requires %dx%d; dropping frame",
                              frame.cols, frame.rows, width_, height_);
        continue;
      }
      sensor_msgs::msg::CompressedImage msg;
      if (!mrp_camera_common::encode_jpeg(frame, jpeg_quality_, msg.data)) {
        frame_dropped(stream_);
        RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "Failed to encode image to JPEG");
        continue;
      }
      msg.header.stamp = stamp;
      msg.header.frame_id = frame_id_;
      msg.format = mrp_camera_common::JPEG_FORMAT;
      const auto bytes = msg.data.size();
      publisher_->publish(msg);
      frame_published(stream_, bytes);
    }
  }

  rclcpp::Publisher<sensor_msgs::msg::CompressedImage>::SharedPtr publisher_;
  cv::VideoCapture cap_;
  StreamId stream_{};
  int width_ = 0;
  int height_ = 0;
  int jpeg_quality_ = mrp_camera_common::DEFAULT_JPEG_QUALITY;
  std::string frame_id_;
};

int main(int argc, char **argv) {
  return mrp_camera_common::run_camera_node<OpenCvCameraNode>(argc, argv);
}
