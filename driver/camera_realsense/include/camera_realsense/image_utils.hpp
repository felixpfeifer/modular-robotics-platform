#pragma once

// Pure helpers for the RealSense driver. No librealsense dependency, so they
// can be unit-tested on machines without the SDK or a camera.

#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>

#include <cmath>
#include <cstdint>
#include <limits>
#include <optional>
#include <vector>

namespace camera_realsense {

// `format` of the published depth CompressedImage. It follows the
// compressed_image_transport convention ("<raw encoding>; <codec> compressed
// <decoded encoding>"), so image_transport subscribers and
// cv2.imdecode(..., IMREAD_UNCHANGED) both work. Color uses
// mrp_camera_common::JPEG_FORMAT.
inline constexpr const char *DEPTH_FORMAT = "16UC1; png compressed 16UC1";

// Encode a 16-bit single-channel depth image as lossless PNG.
// compression_level 0..9: 1 is ~3x faster than the default (3) and only a few
// percent larger, which matters at 30 FPS on a Jetson.
inline bool encode_depth_png(const cv::Mat &depth_mm, int compression_level,
                             std::vector<uchar> &encoded) {
  if (depth_mm.empty() || depth_mm.type() != CV_16UC1) {
    return false;
  }
  const std::vector<int> params = {cv::IMWRITE_PNG_COMPRESSION, compression_level};
  return cv::imencode(".png", depth_mm, encoded, params);
}

// Convert raw Z16 sensor units to millimetres, so published depth always uses
// one unit no matter which camera model is used. D400 cameras already use
// 1 mm units (scale 0.001 m), so they are copied with no rescaling; others
// (e.g. L515 with 0.25 mm) are rescaled.
// Values beyond max_depth_mm (0 disables the limit) are set to 0 (= invalid),
// matching the RealSense convention that 0 means "no depth".
inline cv::Mat depth_to_millimetres(const cv::Mat &raw_z16, float depth_scale_m, int max_depth_mm) {
  cv::Mat out;
  if (raw_z16.empty() || raw_z16.type() != CV_16UC1 || !(depth_scale_m > 0.0F)) {
    return out;
  }
  const double factor = static_cast<double>(depth_scale_m) * 1000.0;
  if (std::abs(factor - 1.0) < 1e-6) {
    out = raw_z16.clone();
  } else {
    // convertTo saturates to [0, 65535] and rounds.
    raw_z16.convertTo(out, CV_16UC1, factor);
  }
  if (max_depth_mm > 0) {
    out.setTo(0, out > max_depth_mm);
  }
  return out;
}

// Converts a librealsense frame timestamp (milliseconds) into a ROS-style
// (sec, nanosec) pair. Kept here so the conversion is unit-tested.
struct Stamp {
  int32_t sec;
  uint32_t nanosec;
};

inline std::optional<Stamp> stamp_from_milliseconds(double ms) {
  constexpr int64_t ns_per_second = 1000000000LL;
  constexpr int64_t sec_limit = static_cast<int64_t>(std::numeric_limits<int32_t>::max()) + 1;
  if (!std::isfinite(ms) || ms < 0.0 || ms >= sec_limit * 1000.0) {
    return std::nullopt;
  }
  const auto total_ns = static_cast<int64_t>(std::llround(ms * 1e6));
  return Stamp{static_cast<int32_t>(total_ns / ns_per_second),
               static_cast<uint32_t>(total_ns % ns_per_second)};
}

} // namespace camera_realsense
