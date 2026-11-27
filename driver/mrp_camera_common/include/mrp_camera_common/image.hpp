#pragma once

// Image helpers shared by the MRP camera drivers. No ROS dependency, so they are
// unit-tested without a camera.

#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include <cstdint>
#include <vector>

namespace mrp_camera_common {

// `format` of every published color CompressedImage. The recorder accepts only
// "jpeg"/"jpg", so all drivers use exactly this string.
inline constexpr const char *JPEG_FORMAT = "jpeg";

inline constexpr int DEFAULT_JPEG_QUALITY = 90;

// Encode an 8-bit BGR (CV_8UC3) or mono (CV_8UC1) frame as JPEG. Mono frames are
// expanded to 3-channel BGR first, so every consumer always decodes HxWx3.
// Returns false (and leaves `encoded` unspecified) for any other input.
inline bool encode_jpeg(const cv::Mat &image, int quality, std::vector<std::uint8_t> &encoded) {
  if (image.empty() || quality < 1 || quality > 100) {
    return false;
  }
  const std::vector<int> params = {cv::IMWRITE_JPEG_QUALITY, quality};
  if (image.type() == CV_8UC3) {
    return cv::imencode(".jpg", image, encoded, params);
  }
  if (image.type() == CV_8UC1) {
    cv::Mat bgr;
    cv::cvtColor(image, bgr, cv::COLOR_GRAY2BGR);
    return cv::imencode(".jpg", bgr, encoded, params);
  }
  return false;
}

// The largest centred rectangle of `source` that has the aspect ratio of `target`.
// Returns an empty rectangle when either size is not positive.
inline cv::Rect center_crop_for_aspect(cv::Size source, cv::Size target) {
  if (source.width <= 0 || source.height <= 0 || target.width <= 0 || target.height <= 0) {
    return {};
  }
  const auto sw = static_cast<std::int64_t>(source.width);
  const auto sh = static_cast<std::int64_t>(source.height);
  const auto tw = static_cast<std::int64_t>(target.width);
  const auto th = static_cast<std::int64_t>(target.height);
  if (sw * th > tw * sh) { // source is wider: cut the left and right edges
    const auto width = static_cast<int>(sh * tw / th);
    return {(source.width - width) / 2, 0, width, source.height};
  }
  const auto height = static_cast<int>(sw * th / tw); // taller (or equal): cut top and bottom
  return {0, (source.height - height) / 2, source.width, height};
}

// Bring `image` to exactly `target` without distorting it: crop the centre to the
// target aspect ratio, then scale. The result shares memory with `image` when no
// change is needed. Returns an empty Mat when `image` or `target` is empty.
inline cv::Mat fit_to_size(const cv::Mat &image, cv::Size target) {
  if (image.empty() || target.width <= 0 || target.height <= 0) {
    return {};
  }
  if (image.size() == target) {
    return image;
  }
  cv::Mat cropped = image(center_crop_for_aspect(image.size(), target));
  if (cropped.size() == target) {
    return cropped;
  }
  const bool shrinking = cropped.cols > target.width;
  cv::Mat out;
  cv::resize(cropped, out, target, 0, 0, shrinking ? cv::INTER_AREA : cv::INTER_LINEAR);
  return out;
}

} // namespace mrp_camera_common
