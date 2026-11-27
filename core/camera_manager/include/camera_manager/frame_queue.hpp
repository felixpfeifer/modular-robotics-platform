#pragma once

#include <cstddef>
#include <deque>
#include <mutex>
#include <optional>

namespace camera_manager {

template <typename T> class BoundedQueue {
public:
  explicit BoundedQueue(std::size_t capacity) : capacity_(capacity) {}

  bool push(T value) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (capacity_ == 0U) {
      return false;
    }
    if (queue_.size() == capacity_) {
      queue_.pop_front();
      ++dropped_count_;
    }
    queue_.push_back(std::move(value));
    return true;
  }

  std::optional<T> pop() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (queue_.empty()) {
      return std::nullopt;
    }
    T value = std::move(queue_.front());
    queue_.pop_front();
    return value;
  }

  std::size_t size() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return queue_.size();
  }

  std::size_t dropped_count() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return dropped_count_;
  }

private:
  const std::size_t capacity_;
  mutable std::mutex mutex_;
  std::deque<T> queue_;
  std::size_t dropped_count_{0};
};

} // namespace camera_manager
