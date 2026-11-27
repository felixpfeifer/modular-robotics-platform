#pragma once

// Per-stream frame statistics and stall detection. No ROS dependency.

#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdio>
#include <optional>
#include <string>

namespace mrp_camera_common {

using SteadyClock = std::chrono::steady_clock;

// Totals of one reporting window.
struct StatsReport {
  double seconds = 0.0;
  std::size_t frames = 0;
  std::size_t bytes = 0;
  std::size_t dropped = 0;

  double fps() const { return seconds > 0.0 ? static_cast<double>(frames) / seconds : 0.0; }
  double mbit_per_second() const {
    return seconds > 0.0 ? static_cast<double>(bytes) * 8.0 / (seconds * 1e6) : 0.0;
  }
  std::size_t average_kib() const { return frames > 0 ? bytes / frames / 1024 : 0; }
};

inline std::string format_report(const StatsReport &report) {
  char text[160];
  std::snprintf(text, sizeof(text), "%.1f FPS | %.2f Mbit/s | avg %zu KiB/frame | dropped %zu",
                report.fps(), report.mbit_per_second(), report.average_kib(), report.dropped);
  return text;
}

// Counts frames and bytes and hands out one report per period. Not thread-safe:
// use it from the capture thread only.
class FrameStats {
public:
  FrameStats(SteadyClock::duration period, SteadyClock::time_point start)
      : period_(period), window_start_(start) {}

  void add_frame(std::size_t bytes) {
    ++frames_;
    bytes_ += bytes;
  }
  void add_drop() { ++dropped_; }

  // The totals since the last report once `period` has passed, then starts a new window.
  std::optional<StatsReport> poll(SteadyClock::time_point now) {
    const auto elapsed = now - window_start_;
    if (elapsed < period_) {
      return std::nullopt;
    }
    StatsReport report;
    report.seconds = std::chrono::duration<double>(elapsed).count();
    report.frames = frames_;
    report.bytes = bytes_;
    report.dropped = dropped_;
    window_start_ = now;
    frames_ = bytes_ = dropped_ = 0;
    return report;
  }

private:
  SteadyClock::duration period_;
  SteadyClock::time_point window_start_;
  std::size_t frames_ = 0;
  std::size_t bytes_ = 0;
  std::size_t dropped_ = 0;
};

// Time since the last published frame. Fed by the capture thread, read by the
// watchdog timer on the executor thread, so the timestamp is atomic.
class StallWatchdog {
public:
  StallWatchdog(SteadyClock::duration max_stall, SteadyClock::time_point start)
      : max_stall_(max_stall), last_(start.time_since_epoch().count()) {}

  void feed(SteadyClock::time_point now) noexcept {
    last_.store(now.time_since_epoch().count(), std::memory_order_relaxed);
  }
  SteadyClock::duration silence(SteadyClock::time_point now) const noexcept {
    return now -
           SteadyClock::time_point(SteadyClock::duration(last_.load(std::memory_order_relaxed)));
  }
  bool stalled(SteadyClock::time_point now) const noexcept { return silence(now) >= max_stall_; }
  SteadyClock::duration max_stall() const noexcept { return max_stall_; }

private:
  SteadyClock::duration max_stall_;
  std::atomic<SteadyClock::rep> last_;
};

} // namespace mrp_camera_common
