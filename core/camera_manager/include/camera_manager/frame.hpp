#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace camera_manager {

enum class TimestampDomain { HostReceiveMonotonic, Device, Ros };

struct Frame {
  std::string camera_id;
  std::uint64_t sequence{0};
  std::int64_t timestamp_ns{0};
  TimestampDomain timestamp_domain{TimestampDomain::HostReceiveMonotonic};
  std::uint32_t width{0};
  std::uint32_t height{0};
  std::string encoding{"bgr8"};
  std::vector<std::uint8_t> pixels;
};

} // namespace camera_manager
