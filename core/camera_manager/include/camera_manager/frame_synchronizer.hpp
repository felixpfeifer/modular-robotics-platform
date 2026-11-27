#pragma once

#include "camera_manager/frame.hpp"

#include <cstddef>
#include <cstdint>
#include <deque>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace camera_manager {

struct SynchronizedFrameSet {
  std::vector<Frame> frames;
  std::int64_t max_timestamp_delta_ns{0};
};

class FrameSynchronizer {
public:
  FrameSynchronizer(std::vector<std::string> required_cameras, std::int64_t tolerance_ns,
                    std::size_t buffer_capacity = 3);

  std::optional<SynchronizedFrameSet> add(Frame frame);

private:
  std::vector<std::string> required_cameras_;
  std::int64_t tolerance_ns_;
  std::size_t buffer_capacity_;
  std::map<std::string, std::deque<Frame>> buffers_;
};

} // namespace camera_manager
