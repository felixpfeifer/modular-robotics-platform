#pragma once

#include "camera_manager/frame.hpp"
#include "camera_manager/frame_queue.hpp"

#include <atomic>
#include <chrono>
#include <functional>
#include <memory>
#include <thread>

namespace camera_manager {

class ICameraDriver {
public:
  virtual ~ICameraDriver() = default;
  virtual bool open() = 0;
  virtual bool grab(Frame &frame) = 0;
  virtual void request_stop() = 0;
  virtual void close() = 0;
};

class MockCameraDriver final : public ICameraDriver {
public:
  explicit MockCameraDriver(std::string camera_id, std::chrono::milliseconds delay = {},
                            std::chrono::milliseconds interval = {}, std::uint32_t width = 1,
                            std::uint32_t height = 1);
  bool open() override;
  bool grab(Frame &frame) override;
  void request_stop() override;
  void close() override;

private:
  std::string camera_id_;
  std::chrono::milliseconds delay_;
  std::chrono::milliseconds interval_;
  std::uint32_t width_;
  std::uint32_t height_;
  std::atomic<bool> stop_requested_{false};
  std::uint64_t sequence_{0};
};

class CameraWorker {
public:
  using FrameCallback = std::function<void(Frame)>;

  CameraWorker(std::unique_ptr<ICameraDriver> driver, std::size_t queue_capacity,
               FrameCallback callback);
  ~CameraWorker();
  CameraWorker(const CameraWorker &) = delete;
  CameraWorker &operator=(const CameraWorker &) = delete;

  void start();
  void stop();
  std::size_t dropped_count() const;

private:
  void run();

  std::unique_ptr<ICameraDriver> driver_;
  BoundedQueue<Frame> queue_;
  FrameCallback callback_;
  std::atomic<bool> running_{false};
  std::thread thread_;
};

} // namespace camera_manager
