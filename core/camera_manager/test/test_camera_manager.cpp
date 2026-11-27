#include "camera_manager/camera_worker.hpp"
#include "camera_manager/frame_synchronizer.hpp"

#include <atomic>
#include <cassert>
#include <chrono>
#include <future>
#include <memory>
#include <thread>

namespace {

using camera_manager::Frame;

void test_bounded_queue_drops_oldest() {
  camera_manager::BoundedQueue<int> queue(2);
  assert(queue.push(1));
  assert(queue.push(2));
  assert(queue.push(3));
  assert(queue.size() == 2);
  assert(queue.dropped_count() == 1);
  assert(queue.pop().value() == 2);
  assert(queue.pop().value() == 3);
}

Frame frame(const char *camera, std::int64_t timestamp) {
  Frame result;
  result.camera_id = camera;
  result.timestamp_ns = timestamp;
  return result;
}

void test_synchronizer_uses_capture_timestamp() {
  camera_manager::FrameSynchronizer synchronizer({"a", "b"}, 10'000'000);
  const auto first = synchronizer.add(frame("a", 1'000'000'000));
  assert(!first.has_value());
  const auto synchronized = synchronizer.add(frame("b", 1'004'000'000));
  assert(synchronized.has_value());
  assert(synchronized->max_timestamp_delta_ns == 4'000'000);

  const auto second = synchronizer.add(frame("a", 2'000'000'000));
  const auto third = synchronizer.add(frame("b", 2'015'000'000));
  assert(!second.has_value());
  assert(!third.has_value());
}

void test_blocking_camera_does_not_stop_other_worker() {
  std::promise<void> fast_frame;
  auto fast_future = fast_frame.get_future();
  auto notified = std::make_shared<std::atomic<bool>>(false);
  camera_manager::CameraWorker slow(
      std::make_unique<camera_manager::MockCameraDriver>("slow", std::chrono::milliseconds(200)), 2,
      [](Frame) {});
  camera_manager::CameraWorker fast(std::make_unique<camera_manager::MockCameraDriver>("fast"), 2,
                                    [&fast_frame, notified](Frame) {
                                      if (!notified->exchange(true)) {
                                        fast_frame.set_value();
                                      }
                                    });
  slow.start();
  fast.start();
  assert(fast_future.wait_for(std::chrono::milliseconds(100)) == std::future_status::ready);
  fast.stop();
  slow.stop();
}

} // namespace

int main() {
  test_bounded_queue_drops_oldest();
  test_synchronizer_uses_capture_timestamp();
  test_blocking_camera_does_not_stop_other_worker();
  return 0;
}
