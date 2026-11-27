#pragma once

// Pure helpers for the V4L2 driver: device classification and selection, so the
// decisions are unit-tested without a camera.

#include <linux/videodev2.h>

#include <cctype>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace camera_opencv {

inline bool is_video_capture_device(const v4l2_capability &capability) {
  const auto flags = (capability.capabilities & V4L2_CAP_DEVICE_CAPS) != 0U
                         ? capability.device_caps
                         : capability.capabilities;
  return (flags & V4L2_CAP_VIDEO_CAPTURE) != 0U;
}

inline bool is_color_pixel_format(std::uint32_t pixel_format) {
  switch (pixel_format) {
  case V4L2_PIX_FMT_YUYV:
  case V4L2_PIX_FMT_UYVY:
  case V4L2_PIX_FMT_MJPEG:
  case V4L2_PIX_FMT_RGB24:
  case V4L2_PIX_FMT_BGR24:
  case V4L2_PIX_FMT_NV12:
    return true;
  default:
    return false;
  }
}

// The sysfs `removable` attribute of a USB device is "removable", "fixed" or
// "unknown". Only "fixed" marks a built-in (laptop) camera: many desktop and Jetson
// USB ports report "unknown" for cameras that are plugged in.
inline bool is_builtin_removable_value(const std::string &value) { return value == "fixed"; }

struct DeviceCandidate {
  std::string path; // e.g. /dev/video2
  std::string card; // V4L2 card name
  bool builtin = false;
};

// The device `video_device:=auto` opens: the first RealSense color node, otherwise
// the first color capture device that is not built in.
inline std::optional<DeviceCandidate> choose_device(const std::vector<DeviceCandidate> &devices) {
  std::optional<DeviceCandidate> fallback;
  for (const auto &device : devices) {
    if (device.builtin) {
      continue;
    }
    if (device.card.find("RealSense") != std::string::npos) {
      return device;
    }
    if (!fallback) {
      fallback = device;
    }
  }
  return fallback;
}

// A V4L2 FOURCC such as "MJPG" or "YUYV" as OpenCV expects it, or nullopt when
// `text` is not four printable characters.
inline std::optional<int> fourcc_code(const std::string &text) {
  if (text.size() != 4) {
    return std::nullopt;
  }
  std::uint32_t code = 0;
  for (std::size_t i = 0; i < 4; ++i) {
    const auto c = static_cast<unsigned char>(text[i]);
    if (std::isprint(c) == 0) {
      return std::nullopt;
    }
    code |= static_cast<std::uint32_t>(c) << (8U * i);
  }
  return static_cast<int>(code);
}

inline std::string fourcc_text(int code) {
  std::string text(4, ' ');
  for (std::size_t i = 0; i < 4; ++i) {
    const auto c = static_cast<char>((static_cast<std::uint32_t>(code) >> (8U * i)) & 0xFFU);
    text[i] = std::isprint(static_cast<unsigned char>(c)) != 0 ? c : '?';
  }
  return text;
}

} // namespace camera_opencv
