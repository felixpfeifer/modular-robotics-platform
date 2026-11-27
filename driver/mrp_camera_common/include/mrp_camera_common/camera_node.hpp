#pragma once

// Base class for the MRP camera drivers. A driver opens and configures its camera
// in its constructor, registers one stream per published image topic and starts its
// capture loop with start_capture(). This class then owns everything the drivers
// share:
//
//  * the capture thread: an exception escaping the loop stops the node with exit
//    status 1, so the container's restart policy brings it back;
//  * a watchdog on the executor thread, independent of the loop: if a stream
//    publishes nothing for `max_stall`, the node stops even when the loop is stuck
//    inside a blocking SDK call; if the loop then does not return within the stop
//    timeout, the process exits immediately with status 1;
//  * /diagnostics (one status per stream, once per second);
//  * the heartbeat file used by the container HEALTHCHECK;
//  * the periodic rate log.
//
// Contract for drivers: call stop_capture() first thing in the destructor, before
// any member the loop uses is destroyed.

#include <mrp_camera_common/frame_stats.hpp>
#include <mrp_camera_common/heartbeat.hpp>

#include <diagnostic_msgs/msg/diagnostic_array.hpp>
#include <diagnostic_msgs/msg/diagnostic_status.hpp>
#include <rclcpp/rclcpp.hpp>

#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <functional>
#include <future>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace mrp_camera_common {

using namespace std::chrono_literals;

inline constexpr auto DEFAULT_MAX_STALL = std::chrono::seconds(10);
inline constexpr auto DEFAULT_STOP_TIMEOUT = std::chrono::seconds(5);
inline constexpr auto REPORT_PERIOD = std::chrono::seconds(5);
// The heartbeat is touched only while every stream published within this time.
inline constexpr auto HEARTBEAT_FRESHNESS = std::chrono::seconds(2);

// Image topics: reliable, so recorders that ask for reliable delivery are matched;
// best-effort subscribers (the recorder, the dashboard) are matched as well.
inline rclcpp::QoS image_qos() { return rclcpp::QoS(rclcpp::KeepLast(10)).reliable(); }

class CameraNode : public rclcpp::Node {
public:
  using StreamId = std::size_t;

  bool failed() const noexcept { return failed_; }

  ~CameraNode() override { stop_capture(); }

  CameraNode(const CameraNode &) = delete;
  CameraNode &operator=(const CameraNode &) = delete;
  CameraNode(CameraNode &&) = delete;
  CameraNode &operator=(CameraNode &&) = delete;

protected:
  explicit CameraNode(const std::string &name,
                      const rclcpp::NodeOptions &options = rclcpp::NodeOptions())
      : rclcpp::Node(name, options), heartbeat_(HeartbeatFile::from_environment()) {}

  // Registers a published stream; call before start_capture(). `expected_fps` <= 0
  // disables the low-rate warning in the diagnostics.
  StreamId add_stream(const std::string &name, double expected_fps,
                      SteadyClock::duration max_stall = DEFAULT_MAX_STALL) {
    if (thread_.joinable()) {
      throw std::logic_error("add_stream() must be called before start_capture()");
    }
    streams_.push_back(std::make_unique<Stream>(name, expected_fps, max_stall));
    return streams_.size() - 1;
  }

  // Shown as hardware_id in the diagnostics, e.g. the camera's serial number.
  void set_hardware_id(const std::string &hardware_id) {
    const std::lock_guard<std::mutex> lock(mutex_);
    hardware_id_ = hardware_id;
  }

  // Runs `loop` in the capture thread. The loop runs while capture_running().
  void start_capture(std::function<void()> loop) {
    if (streams_.empty()) {
      throw std::logic_error("register at least one stream before start_capture()");
    }
    const auto start = SteadyClock::now();
    for (auto &stream : streams_) {
      stream->watchdog.feed(start);
      stream->stats = FrameStats(REPORT_PERIOD, start);
    }
    diagnostics_pub_ = create_publisher<diagnostic_msgs::msg::DiagnosticArray>(
        "/diagnostics", rclcpp::SystemDefaultsQoS());
    running_ = true;
    std::promise<void> done;
    thread_done_ = done.get_future();
    thread_ = std::thread([this, loop = std::move(loop), done = std::move(done)]() mutable {
      try {
        loop();
      } catch (const std::exception &error) {
        fail(std::string("Capture failed: ") + error.what());
      } catch (...) {
        fail("Capture failed with an unknown exception");
      }
      done.set_value();
    });
    watchdog_timer_ = create_wall_timer(1s, [this]() { on_watchdog_tick(); });
    if (heartbeat_.enabled()) {
      RCLCPP_INFO(get_logger(), "Heartbeat file: %s", heartbeat_.path().c_str());
    }
  }

  // Stops the loop and joins the capture thread. A loop that does not return within
  // `timeout` is stuck in a blocking camera call that nothing can interrupt: the
  // process then exits with status 1 so the restart policy recovers the camera.
  void stop_capture(SteadyClock::duration timeout = DEFAULT_STOP_TIMEOUT) noexcept {
    running_ = false;
    if (watchdog_timer_) {
      watchdog_timer_->cancel();
    }
    if (!thread_.joinable()) {
      return;
    }
    if (thread_done_.wait_for(timeout) == std::future_status::timeout) {
      RCLCPP_FATAL(get_logger(), "Capture thread did not stop within %.1f s; exiting",
                   std::chrono::duration<double>(timeout).count());
      std::fflush(nullptr);
      std::_Exit(1);
    }
    thread_.join();
  }

  // Loop condition for the capture thread.
  bool capture_running() const noexcept { return running_ && rclcpp::ok(); }

  // Logs `reason`, marks the node failed (exit status 1) and stops spinning. Ignored
  // during an orderly shutdown.
  void fail(const std::string &reason) {
    if (!running_ || !rclcpp::ok()) {
      return;
    }
    RCLCPP_ERROR(get_logger(), "%s", reason.c_str());
    failed_ = true;
    running_ = false;
    rclcpp::shutdown();
  }

  // Capture thread only.
  void frame_published(StreamId id, std::size_t bytes) {
    auto &stream = *streams_.at(id);
    stream.stats.add_frame(bytes);
    stream.watchdog.feed(SteadyClock::now());
  }
  void frame_dropped(StreamId id) { streams_.at(id)->stats.add_drop(); }

  // Capture thread only: logs every stream's rate once per report period. `extra`
  // is called only then, and its text appended (e.g. SDK transfer statistics).
  void report_stats(const std::function<std::string()> &extra = {}) {
    const auto now = SteadyClock::now();
    std::string line;
    for (auto &stream : streams_) {
      const auto report = stream->stats.poll(now);
      if (!report) {
        return; // all windows start together, so they all end together
      }
      {
        const std::lock_guard<std::mutex> lock(mutex_);
        stream->last_report = *report;
      }
      line += (line.empty() ? "" : " || ") + stream->name + ": " + format_report(*report);
    }
    if (extra) {
      line += " | " + extra();
    }
    RCLCPP_INFO(get_logger(), "%s", line.c_str());
  }

private:
  struct Stream {
    Stream(std::string stream_name, double fps, SteadyClock::duration max_stall)
        : name(std::move(stream_name)), expected_fps(fps), stats(REPORT_PERIOD, SteadyClock::now()),
          watchdog(max_stall, SteadyClock::now()) {}
    std::string name;
    double expected_fps;
    FrameStats stats;                       // capture thread only
    StallWatchdog watchdog;                 // atomic
    std::optional<StatsReport> last_report; // guarded by mutex_
  };

  void on_watchdog_tick() {
    const auto now = SteadyClock::now();
    bool fresh = true;
    diagnostic_msgs::msg::DiagnosticArray array;
    array.header.stamp = this->now();
    for (const auto &stream : streams_) {
      const auto silence = stream->watchdog.silence(now);
      fresh = fresh && silence < HEARTBEAT_FRESHNESS;
      array.status.push_back(stream_status(*stream, silence));
      if (stream->watchdog.stalled(now)) {
        diagnostics_pub_->publish(array);
        fail("No " + stream->name + " frames published for " +
             std::to_string(std::chrono::duration_cast<std::chrono::seconds>(silence).count()) +
             " s");
        return;
      }
    }
    diagnostics_pub_->publish(array);
    if (fresh && heartbeat_.enabled() && !heartbeat_.touch()) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 60000, "Cannot write heartbeat file %s",
                           heartbeat_.path().c_str());
    }
  }

  diagnostic_msgs::msg::DiagnosticStatus stream_status(const Stream &stream,
                                                       SteadyClock::duration silence) {
    using diagnostic_msgs::msg::DiagnosticStatus;
    using diagnostic_msgs::msg::KeyValue;
    DiagnosticStatus status;
    status.name = std::string(get_fully_qualified_name()) + ": " + stream.name;
    std::optional<StatsReport> report;
    {
      const std::lock_guard<std::mutex> lock(mutex_);
      status.hardware_id = hardware_id_;
      report = stream.last_report;
    }
    const double silent_s = std::chrono::duration<double>(silence).count();
    auto value = [](double v) {
      char text[32];
      std::snprintf(text, sizeof(text), "%.2f", v);
      return std::string(text);
    };
    status.values.push_back(
        KeyValue{}.set__key("seconds_since_last_frame").set__value(value(silent_s)));
    if (stream.expected_fps > 0.0) {
      status.values.push_back(
          KeyValue{}.set__key("expected_fps").set__value(value(stream.expected_fps)));
    }
    if (report) {
      status.values.push_back(KeyValue{}.set__key("fps").set__value(value(report->fps())));
      status.values.push_back(
          KeyValue{}.set__key("mbit_per_second").set__value(value(report->mbit_per_second())));
      status.values.push_back(
          KeyValue{}.set__key("dropped_frames").set__value(std::to_string(report->dropped)));
    }
    if (silence >= HEARTBEAT_FRESHNESS) {
      status.level = DiagnosticStatus::ERROR;
      status.message = "no frames";
    } else if (!report) {
      status.level = DiagnosticStatus::OK;
      status.message = "starting";
    } else if (stream.expected_fps > 0.0 && report->fps() < 0.9 * stream.expected_fps) {
      status.level = DiagnosticStatus::WARN;
      status.message = "frame rate below the configured rate";
    } else {
      status.level = DiagnosticStatus::OK;
      status.message = "streaming";
    }
    return status;
  }

  HeartbeatFile heartbeat_;
  std::vector<std::unique_ptr<Stream>> streams_;
  std::mutex mutex_;
  std::string hardware_id_;
  rclcpp::Publisher<diagnostic_msgs::msg::DiagnosticArray>::SharedPtr diagnostics_pub_;
  rclcpp::TimerBase::SharedPtr watchdog_timer_;
  std::thread thread_;
  std::future<void> thread_done_;
  std::atomic<bool> running_{false};
  std::atomic<bool> failed_{false};
};

// main() of every driver: init, construct, spin, exit status 1 on any failure.
// `at_exit` runs after the node is destroyed (e.g. to shut an SDK down).
template <typename NodeT>
int run_camera_node(int argc, char **argv, const std::function<void()> &at_exit = {}) {
  rclcpp::init(argc, argv);
  int code = 0;
  try {
    auto node = std::make_shared<NodeT>();
    rclcpp::spin(node);
    code = node->failed() ? 1 : 0;
  } catch (const std::exception &error) {
    RCLCPP_FATAL(rclcpp::get_logger("camera_node"), "%s", error.what());
    code = 1;
  }
  if (rclcpp::ok()) {
    rclcpp::shutdown();
  }
  if (at_exit) {
    at_exit();
  }
  return code;
}

} // namespace mrp_camera_common
