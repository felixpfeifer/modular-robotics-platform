#include "camera_manager/camera_worker.hpp"

#include <algorithm>
#include <utility>

namespace camera_manager {

MockCameraDriver::MockCameraDriver(std::string camera_id, std::chrono::milliseconds delay,
                                   std::chrono::milliseconds interval, std::uint32_t width,
                                   std::uint32_t height)
    : camera_id_(std::move(camera_id)), delay_(delay), interval_(interval), width_(width),
      height_(height) {}

bool MockCameraDriver::open() {
  stop_requested_.store(false);
  sequence_ = 0;
  return true;
}

bool MockCameraDriver::grab(Frame &frame) {
  if (stop_requested_.load()) {
    return false;
  }
  if (interval_.count() > 0) {
    std::this_thread::sleep_for(interval_);
  }
  if (stop_requested_.load()) {
    return false;
  }
  if (delay_.count() > 0) {
    std::this_thread::sleep_for(delay_);
  }
  if (stop_requested_.load()) {
    return false;
  }
  frame.camera_id = camera_id_;
  frame.sequence = sequence_++;
  const auto frame_interval_ms = std::max<std::int64_t>(interval_.count(), 1);
  frame.timestamp_ns =
      static_cast<std::int64_t>(frame.sequence + 1U) * frame_interval_ms * 1'000'000;
  frame.width = width_;
  frame.height = height_;
  const auto pixel_count = static_cast<std::size_t>(width_) * height_ * 3U;
  frame.pixels.assign(pixel_count, static_cast<std::uint8_t>(frame.sequence % 255U));
  return true;
}

void MockCameraDriver::request_stop() { stop_requested_.store(true); }

void MockCameraDriver::close() { request_stop(); }

CameraWorker::CameraWorker(std::unique_ptr<ICameraDriver> driver, std::size_t queue_capacity,
                           FrameCallback callback)
    : driver_(std::move(driver)), queue_(queue_capacity), callback_(std::move(callback)) {}

CameraWorker::~CameraWorker() { stop(); }

void CameraWorker::start() {
  if (running_.exchange(true)) {
    return;
  }
  thread_ = std::thread(&CameraWorker::run, this);
}

void CameraWorker::stop() {
  if (!running_.exchange(false)) {
    return;
  }
  driver_->request_stop();
  if (thread_.joinable()) {
    thread_.join();
  }
  driver_->close();
}

std::size_t CameraWorker::dropped_count() const { return queue_.dropped_count(); }

void CameraWorker::run() {
  if (!driver_->open()) {
    running_.store(false);
    return;
  }
  while (running_.load()) {
    Frame frame;
    if (driver_->grab(frame)) {
      queue_.push(frame);
      if (const auto queued = queue_.pop(); queued.has_value()) {
        callback_(*queued);
      }
    }
  }
}

} // namespace camera_manager
