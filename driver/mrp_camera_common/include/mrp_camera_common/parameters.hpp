#pragma once

// Parameter descriptors for startup-only driver settings. Ranges are enforced by
// rclcpp when the parameter is declared, so an out-of-range value from the command
// line or a YAML file stops the node with a message naming the parameter.

#include <rcl_interfaces/msg/floating_point_range.hpp>
#include <rcl_interfaces/msg/integer_range.hpp>
#include <rcl_interfaces/msg/parameter_descriptor.hpp>

#include <cstdint>
#include <string>

namespace mrp_camera_common {

// Image dimensions accepted by every driver (larger is not a sensible camera stream).
inline constexpr std::int64_t MAX_IMAGE_DIMENSION = 16384;

inline rcl_interfaces::msg::ParameterDescriptor read_only(const std::string &description = {}) {
  rcl_interfaces::msg::ParameterDescriptor descriptor;
  descriptor.read_only = true;
  descriptor.description = description;
  return descriptor;
}

inline rcl_interfaces::msg::ParameterDescriptor read_only_int(std::int64_t from, std::int64_t to,
                                                              const std::string &description = {}) {
  auto descriptor = read_only(description);
  descriptor.integer_range.push_back(
      rcl_interfaces::msg::IntegerRange{}.set__from_value(from).set__to_value(to));
  return descriptor;
}

// Note: rclcpp range checks let NaN through; drivers still check std::isfinite.
inline rcl_interfaces::msg::ParameterDescriptor
read_only_double(double from, double to, const std::string &description = {}) {
  auto descriptor = read_only(description);
  descriptor.floating_point_range.push_back(
      rcl_interfaces::msg::FloatingPointRange{}.set__from_value(from).set__to_value(to));
  return descriptor;
}

} // namespace mrp_camera_common
