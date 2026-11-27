// CameraNode with a fake driver: the capture thread, the watchdog, the hard exit
// for a stuck loop, diagnostics and the heartbeat, without any camera.

#include <mrp_camera_common/camera_node.hpp>
#include <mrp_camera_common/image.hpp>

#include <gtest/gtest.h>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include <sys/stat.h>
#include <unistd.h>

using mrp_camera_common::CameraNode;
using namespace std::chrono_literals;

namespace {

enum class Mode { Stream, Silent, Throw, Hang };

std::string test_namespace() { return "/camera_common_test_" + std::to_string(::getpid()); }

class FakeCamera : public CameraNode {
public:
  explicit FakeCamera(Mode mode)
      : CameraNode("fake_camera", rclcpp::NodeOptions().arguments(
                                      {"--ros-args", "-r", "__ns:=" + test_namespace()})),
        mode_(mode) {
    stream_ = add_stream("color", 50.0, 1500ms);
    set_hardware_id("fake-serial");
    publisher_ = create_publisher<sensor_msgs::msg::CompressedImage>(
        "image/compressed", mrp_camera_common::image_qos());
    start_capture([this]() { loop(); });
  }
  ~FakeCamera() override { stop_capture(); }
  FakeCamera(const FakeCamera &) = delete;
  FakeCamera &operator=(const FakeCamera &) = delete;
  FakeCamera(FakeCamera &&) = delete;
  FakeCamera &operator=(FakeCamera &&) = delete;

  using CameraNode::stop_capture;

private:
  void loop() {
    if (mode_ == Mode::Throw) {
      throw std::runtime_error("camera unplugged");
    }
    if (mode_ == Mode::Hang) {
      for (;;) { // a blocking SDK call that ignores the stop request
        std::this_thread::sleep_for(100ms);
      }
    }
    const cv::Mat frame(24, 32, CV_8UC3, cv::Scalar(10, 20, 30));
    while (capture_running()) {
      if (mode_ == Mode::Stream) {
        sensor_msgs::msg::CompressedImage msg;
        msg.format = mrp_camera_common::JPEG_FORMAT;
        if (mrp_camera_common::encode_jpeg(frame, 90, msg.data)) {
          publisher_->publish(msg);
          frame_published(stream_, msg.data.size());
        }
        report_stats();
      }
      std::this_thread::sleep_for(20ms);
    }
  }

  Mode mode_;
  StreamId stream_{};
  rclcpp::Publisher<sensor_msgs::msg::CompressedImage>::SharedPtr publisher_;
};

class CameraNodeTest : public ::testing::Test {
protected:
  void SetUp() override { rclcpp::init(0, nullptr); }
  void TearDown() override {
    if (rclcpp::ok()) {
      rclcpp::shutdown();
    }
  }
};

// Spins `node` until `done()` or the timeout; returns done().
template <typename Done>
bool spin_until(const rclcpp::Node::SharedPtr &node, Done done, std::chrono::seconds timeout) {
  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(node);
  const auto deadline = std::chrono::steady_clock::now() + timeout;
  while (!done() && rclcpp::ok() && std::chrono::steady_clock::now() < deadline) {
    executor.spin_some(50ms);
    std::this_thread::sleep_for(10ms);
  }
  return done();
}

} // namespace

TEST_F(CameraNodeTest, PublishesFramesDiagnosticsAndHeartbeat) {
  const std::string heartbeat =
      ::testing::TempDir() + "/camera_heartbeat_" + std::to_string(::getpid());
  std::remove(heartbeat.c_str());
  ::setenv(mrp_camera_common::HEARTBEAT_ENV, heartbeat.c_str(), 1);
  auto camera = std::make_shared<FakeCamera>(Mode::Stream);
  ::unsetenv(mrp_camera_common::HEARTBEAT_ENV);

  auto listener = std::make_shared<rclcpp::Node>("listener");
  std::atomic<int> frames{0};
  std::atomic<bool> diagnostics_ok{false};
  auto image_sub = listener->create_subscription<sensor_msgs::msg::CompressedImage>(
      test_namespace() + "/image/compressed", rclcpp::SensorDataQoS(),
      [&](const sensor_msgs::msg::CompressedImage &msg) {
        if (msg.format == "jpeg" && !msg.data.empty()) {
          ++frames;
        }
      });
  auto diagnostics_sub = listener->create_subscription<diagnostic_msgs::msg::DiagnosticArray>(
      "/diagnostics", 10, [&](const diagnostic_msgs::msg::DiagnosticArray &array) {
        for (const auto &status : array.status) {
          if (status.name.find(test_namespace()) != std::string::npos &&
              status.hardware_id == "fake-serial" &&
              status.level == diagnostic_msgs::msg::DiagnosticStatus::OK) {
            diagnostics_ok = true;
          }
        }
      });

  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(camera);
  executor.add_node(listener);
  const auto deadline = std::chrono::steady_clock::now() + 20s;
  while ((frames < 20 || !diagnostics_ok) && std::chrono::steady_clock::now() < deadline) {
    executor.spin_some(50ms);
  }
  EXPECT_GE(frames, 20);
  EXPECT_TRUE(diagnostics_ok);
  struct stat info {};
  EXPECT_EQ(::stat(heartbeat.c_str(), &info), 0) << "heartbeat file was not written";
  EXPECT_FALSE(camera->failed());
  executor.remove_node(camera);
  camera.reset(); // orderly stop: the loop returns, nothing is reported as a failure
  std::remove(heartbeat.c_str());
}

TEST_F(CameraNodeTest, WatchdogStopsSilentCamera) {
  auto camera = std::make_shared<FakeCamera>(Mode::Silent);
  EXPECT_TRUE(spin_until(camera, [] { return !rclcpp::ok(); }, 10s));
  EXPECT_TRUE(camera->failed());
}

TEST_F(CameraNodeTest, ExceptionInLoopFailsTheNode) {
  auto camera = std::make_shared<FakeCamera>(Mode::Throw);
  EXPECT_TRUE(spin_until(camera, [] { return !rclcpp::ok(); }, 10s));
  EXPECT_TRUE(camera->failed());
}

TEST(CameraNodeDeathTest, StuckLoopExitsTheProcess) {
  GTEST_FLAG_SET(death_test_style, "threadsafe");
  EXPECT_EXIT(
      {
        rclcpp::init(0, nullptr);
        auto camera = std::make_shared<FakeCamera>(Mode::Hang);
        camera->stop_capture(300ms);
      },
      ::testing::ExitedWithCode(1), "did not stop");
}

TEST_F(CameraNodeTest, RunCameraNodeReturnsOneWhenConstructionFails) {
  rclcpp::shutdown(); // run_camera_node initialises rclcpp itself
  struct Broken : rclcpp::Node {
    Broken() : rclcpp::Node("broken") { throw std::runtime_error("no camera found"); }
    bool failed() const { return false; }
  };
  char name[] = "camera_node";
  char *argv[] = {name, nullptr};
  EXPECT_EQ(mrp_camera_common::run_camera_node<Broken>(1, argv), 1);
}
