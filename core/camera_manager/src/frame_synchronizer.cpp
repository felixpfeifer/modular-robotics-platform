#include "camera_manager/frame_synchronizer.hpp"

#include <algorithm>
#include <cmath>
#include <deque>

namespace camera_manager {

FrameSynchronizer::FrameSynchronizer(std::vector<std::string> required_cameras,
                                     std::int64_t tolerance_ns, std::size_t buffer_capacity)
    : required_cameras_(std::move(required_cameras)), tolerance_ns_(tolerance_ns),
      buffer_capacity_(buffer_capacity) {
  // cppcheck-suppress useStlAlgorithm
  for (const auto &camera : required_cameras_) {
    buffers_.emplace(camera, std::deque<Frame>{});
  }
}

std::optional<SynchronizedFrameSet> FrameSynchronizer::add(Frame frame) {
  const auto buffer = buffers_.find(frame.camera_id);
  if (buffer == buffers_.end() || buffer_capacity_ == 0U) {
    return std::nullopt;
  }
  if (buffer->second.size() == buffer_capacity_) {
    buffer->second.pop_front();
  }
  buffer->second.push_back(std::move(frame));

  // cppcheck-suppress useStlAlgorithm
  for (const auto &camera : required_cameras_) {
    // cppcheck-suppress useStlAlgorithm
    if (buffers_.at(camera).empty()) {
      return std::nullopt;
    }
  }

  std::vector<Frame> candidate;
  candidate.reserve(required_cameras_.size());
  for (const auto &camera : required_cameras_) {
    // cppcheck-suppress useStlAlgorithm
    candidate.push_back(buffers_.at(camera).back());
  }
  const auto min_timestamp = std::min_element(candidate.begin(), candidate.end(),
                                              [](const Frame &left, const Frame &right) {
                                                return left.timestamp_ns < right.timestamp_ns;
                                              })
                                 ->timestamp_ns;
  const auto max_timestamp = std::max_element(candidate.begin(), candidate.end(),
                                              [](const Frame &left, const Frame &right) {
                                                return left.timestamp_ns < right.timestamp_ns;
                                              })
                                 ->timestamp_ns;
  if (max_timestamp - min_timestamp > tolerance_ns_) {
    return std::nullopt;
  }
  for (auto &entry : buffers_) {
    entry.second.pop_back();
  }
  return SynchronizedFrameSet{std::move(candidate), max_timestamp - min_timestamp};
}

} // namespace camera_manager
