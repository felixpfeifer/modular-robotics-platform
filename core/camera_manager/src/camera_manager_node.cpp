#include "camera_manager/camera_worker.hpp"
#include "camera_manager/frame_synchronizer.hpp"

#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>

#include <chrono>
#include <cstdint>
#include <map>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace camera_manager {

class CameraManagerNode final : public rclcpp::Node {
public:
  CameraManagerNode() : Node("camera_manager"), start_time_(get_clock()->now()) {
    const auto camera_ids = declare_parameter<std::vector<std::string>>(
        "camera_ids", std::vector<std::string>{"camera_a", "camera_b"});
    const auto width = declare_parameter<std::int64_t>("mock_width", 640);
    const auto height = declare_parameter<std::int64_t>("mock_height", 480);
    const auto fps = declare_parameter<double>("mock_fps", 30.0);
    const auto jpeg_quality = declare_parameter<std::int64_t>("jpeg_quality", 85);
    const auto sync_tolerance_ms = declare_parameter<std::int64_t>("sync_tolerance_ms", 10);

    validate_parameters(camera_ids, width, height, fps, jpeg_quality, sync_tolerance_ms);
    synchronizer_ =
        std::make_unique<FrameSynchronizer>(camera_ids, sync_tolerance_ms * 1'000'000, 3);

    const auto interval = std::chrono::milliseconds(static_cast<std::int64_t>(1000.0 / fps));
    for (const auto &camera_id : camera_ids) {
      publishers_.emplace(camera_id, create_publisher<sensor_msgs::msg::CompressedImage>(
                                         "/cameras/" + camera_id + "/image_raw/compressed", 10));
      auto driver = std::make_unique<MockCameraDriver>(camera_id, std::chrono::milliseconds{},
                                                       interval, static_cast<std::uint32_t>(width),
                                                       static_cast<std::uint32_t>(height));
      workers_.push_back(std::make_unique<CameraWorker>(
          std::move(driver), 3, [this, camera_id, jpeg_quality](Frame frame) {
            publish_frame(camera_id, std::move(frame), jpeg_quality);
          }));
    }
    for (auto &worker : workers_) {
      worker->start();
    }
    RCLCPP_INFO(get_logger(), "Started %zu mock cameras", workers_.size());
  }

  ~CameraManagerNode() override {
    for (auto &worker : workers_) {
      worker->stop();
    }
  }

private:
  static void validate_parameters(const std::vector<std::string> &camera_ids, std::int64_t width,
                                  std::int64_t height, double fps, std::int64_t jpeg_quality,
                                  std::int64_t tolerance_ms) {
    if (camera_ids.empty() || width <= 0 || height <= 0 || fps <= 0.0 || jpeg_quality < 1 ||
        jpeg_quality > 100 || tolerance_ms < 0) {
      throw std::invalid_argument("invalid camera_manager parameters");
    }
    for (const auto &camera_id : camera_ids) {
      // cppcheck-suppress useStlAlgorithm
      if (camera_id.empty() || camera_id.find_first_of("/ ") != std::string::npos) {
        throw std::invalid_argument("camera_ids must be non-empty path components");
      }
    }
  }

  void publish_frame(const std::string &camera_id, Frame frame, std::int64_t jpeg_quality) {
    const auto expected_bytes = static_cast<std::size_t>(frame.width) * frame.height * 3U;
    if (frame.width == 0U || frame.height == 0U || frame.pixels.size() != expected_bytes) {
      RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 5000, "Dropping malformed frame from %s",
                            camera_id.c_str());
      return;
    }

    const cv::Mat image(static_cast<int>(frame.height), static_cast<int>(frame.width), CV_8UC3,
                        frame.pixels.data());
    std::vector<std::uint8_t> encoded;
    if (!cv::imencode(".jpg", image, encoded,
                      {cv::IMWRITE_JPEG_QUALITY, static_cast<int>(jpeg_quality)})) {
      RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 5000, "JPEG encoding failed for %s",
                            camera_id.c_str());
      return;
    }

    sensor_msgs::msg::CompressedImage message;
    message.header.frame_id = camera_id;
    message.header.stamp = start_time_ + rclcpp::Duration::from_nanoseconds(frame.timestamp_ns);
    message.format = "jpeg";
    message.data = std::move(encoded);
    publishers_.at(camera_id)->publish(message);

    std::lock_guard<std::mutex> lock(synchronizer_mutex_);
    static_cast<void>(synchronizer_->add(std::move(frame)));
  }

  rclcpp::Time start_time_;
  std::vector<std::unique_ptr<CameraWorker>> workers_;
  std::map<std::string, rclcpp::Publisher<sensor_msgs::msg::CompressedImage>::SharedPtr>
      publishers_;
  std::unique_ptr<FrameSynchronizer> synchronizer_;
  std::mutex synchronizer_mutex_;
};

} // namespace camera_manager

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  try {
    rclcpp::spin(std::make_shared<camera_manager::CameraManagerNode>());
  } catch (const std::exception &exception) {
    RCLCPP_FATAL(rclcpp::get_logger("camera_manager"), "Startup failed: %s", exception.what());
  }
  rclcpp::shutdown();
  return 0;
}
