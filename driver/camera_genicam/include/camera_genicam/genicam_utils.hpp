#pragma once

// Pure helpers for the GenICam (Aravis) driver. They do not include Aravis, so they
// are unit-tested without a camera, and every decision that does not need the
// device (camera choice, pixel format, conversion, feature syntax) is tested here.

#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <cctype>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace camera_genicam {

// ---------------------------------------------------------------------------------
// Pixel formats (GenICam SFNC / PFNC names, as Aravis reports them)

// Formats this driver can convert, in the order it prefers them when
// `pixel_format` is empty. 8-bit Bayer comes first: it is 1 byte per pixel, a third
// of BGR8, which matters on a 1 Gbit/s GigE link. Packed formats (Mono12p, ...) are
// not supported; the camera nearly always offers an unpacked alternative.
inline const std::vector<std::string> &supported_pixel_formats() {
  static const std::vector<std::string> formats = {
      "BayerRG8", "BayerBG8",   "BayerGR8",      "BayerGB8", "BGR8",   "RGB8",   "BGRa8",  "RGBa8",
      "YUV422_8", "YCbCr422_8", "YUV422_8_UYVY", "Mono8",    "Mono16", "Mono12", "Mono10",
  };
  return formats;
}

inline bool is_supported_pixel_format(const std::string &format) {
  const auto &formats = supported_pixel_formats();
  return std::find(formats.begin(), formats.end(), format) != formats.end();
}

// The pixel format to configure: `requested` if set (it must be offered by the
// camera and supported here), else the most preferred supported one the camera
// offers. Returns an empty string with `error` set when nothing fits.
inline std::string choose_pixel_format(const std::vector<std::string> &available,
                                       const std::string &requested, std::string &error) {
  auto offered = [&](const std::string &f) {
    return std::find(available.begin(), available.end(), f) != available.end();
  };
  auto list = [&]() {
    std::string s;
    for (const auto &f : available) {
      s += (s.empty() ? "" : ", ") + f;
    }
    return s.empty() ? std::string("none") : s;
  };
  if (!requested.empty()) {
    if (!is_supported_pixel_format(requested)) {
      error = "pixel_format '" + requested + "' is not supported by this driver";
      return {};
    }
    if (!offered(requested)) {
      error =
          "the camera does not offer pixel_format '" + requested + "' (it offers: " + list() + ")";
      return {};
    }
    return requested;
  }
  for (const auto &f : supported_pixel_formats()) {
    if (offered(f)) {
      return f;
    }
  }
  error = "the camera offers no pixel format this driver can convert (it offers: " + list() + ")";
  return {};
}

// Bytes per pixel of a supported format (0 = unknown).
inline int bytes_per_pixel(const std::string &format) {
  if (format.rfind("Bayer", 0) == 0 || format == "Mono8") {
    return 1;
  }
  if (format == "BGR8" || format == "RGB8") {
    return 3;
  }
  if (format == "BGRa8" || format == "RGBa8") {
    return 4;
  }
  if (format == "YUV422_8" || format == "YCbCr422_8" || format == "YUV422_8_UYVY" ||
      format == "Mono16" || format == "Mono12" || format == "Mono10") {
    return 2;
  }
  return 0;
}

// Convert one frame to an 8-bit image the JPEG encoder takes: CV_8UC1 for mono
// formats, CV_8UC3 (BGR) for everything else. Mono8 and BGR8 are wrapped without a
// copy, so `out` may point into `data`: use it before the buffer is returned to the
// stream. Lines are assumed unpadded (width * bytes per pixel), as GenICam
// transports deliver them. Returns an empty string on success, otherwise the reason.
inline std::string to_8bit_image(const void *data, size_t size, int width, int height,
                                 const std::string &format, cv::Mat &out) {
  if (data == nullptr || width <= 0 || height <= 0) {
    return "empty frame";
  }
  const int bpp = bytes_per_pixel(format);
  if (bpp == 0) {
    return "unsupported pixel format '" + format + "'";
  }
  const size_t needed =
      static_cast<size_t>(width) * static_cast<size_t>(height) * static_cast<size_t>(bpp);
  if (size < needed) {
    return "frame has " + std::to_string(size) + " bytes, " + std::to_string(width) + "x" +
           std::to_string(height) + " " + format + " needs " + std::to_string(needed);
  }
  auto *bytes =
      const_cast<void *>(data); // cv::Mat headers are non-const; we never write through them

  if (format == "Mono8") {
    out = cv::Mat(height, width, CV_8UC1, bytes);
    return {};
  }
  if (format == "BGR8") {
    out = cv::Mat(height, width, CV_8UC3, bytes);
    return {};
  }
  if (format == "RGB8") {
    cv::cvtColor(cv::Mat(height, width, CV_8UC3, bytes), out, cv::COLOR_RGB2BGR);
    return {};
  }
  if (format == "BGRa8") {
    cv::cvtColor(cv::Mat(height, width, CV_8UC4, bytes), out, cv::COLOR_BGRA2BGR);
    return {};
  }
  if (format == "RGBa8") {
    cv::cvtColor(cv::Mat(height, width, CV_8UC4, bytes), out, cv::COLOR_RGBA2BGR);
    return {};
  }
  if (format == "YUV422_8" || format == "YCbCr422_8") { // Y0 U Y1 V
    cv::cvtColor(cv::Mat(height, width, CV_8UC2, bytes), out, cv::COLOR_YUV2BGR_YUYV);
    return {};
  }
  if (format == "YUV422_8_UYVY") { // U Y0 V Y1
    cv::cvtColor(cv::Mat(height, width, CV_8UC2, bytes), out, cv::COLOR_YUV2BGR_UYVY);
    return {};
  }
  if (format == "Mono16" || format == "Mono12" || format == "Mono10") {
    // Unpacked, little-endian, LSB-aligned: keep the top 8 significant bits.
    const int shift = format == "Mono16" ? 8 : (format == "Mono12" ? 4 : 2);
    cv::Mat(height, width, CV_16UC1, bytes)
        .convertTo(out, CV_8UC1, 1.0 / static_cast<double>(1 << shift));
    return {};
  }
  // OpenCV names Bayer patterns after the second row, so GenICam (first row) RG
  // corresponds to OpenCV BG, and so on (same mapping as cv_bridge).
  int code = -1;
  if (format == "BayerRG8") {
    code = cv::COLOR_BayerBG2BGR;
  } else if (format == "BayerBG8") {
    code = cv::COLOR_BayerRG2BGR;
  } else if (format == "BayerGR8") {
    code = cv::COLOR_BayerGB2BGR;
  } else if (format == "BayerGB8") {
    code = cv::COLOR_BayerGR2BGR;
  }
  if (code < 0) {
    return "unsupported pixel format '" + format + "'";
  }
  cv::cvtColor(cv::Mat(height, width, CV_8UC1, bytes), out, code);
  return {};
}

// ---------------------------------------------------------------------------------
// Camera selection

// One entry of the Aravis device list, reduced to what selection needs.
struct CameraEntry {
  std::string id; // Aravis device id, e.g. "Basler-acA1300-60gc-21234567"
  std::string vendor;
  std::string model;
  std::string serial;
  std::string address;  // IP address (GigE Vision) or USB location
  std::string protocol; // "GigEVision", "USB3Vision" or "Fake"
};

// Aravis protocol name for the `transport` parameter; empty = any. Returns false for
// an unknown transport.
inline bool transport_protocol(const std::string &transport, std::string &protocol) {
  if (transport.empty() || transport == "any") {
    protocol.clear();
  } else if (transport == "gige") {
    protocol = "GigEVision";
  } else if (transport == "usb3") {
    protocol = "USB3Vision";
  } else if (transport == "fake") {
    protocol = "Fake";
  } else {
    return false;
  }
  return true;
}

// Choose the camera to open: by serial number if given, else by `device_id` (Aravis
// device id or IP address) if given, else the first camera. Only cameras of
// `protocol` count (empty = any). Returns the index into `cameras`, or -1 with
// `error` set. Whether a GigE camera is already controlled by another host is only
// known when opening it.
inline int select_camera(const std::vector<CameraEntry> &cameras, const std::string &protocol,
                         const std::string &serial, const std::string &device_id,
                         std::string &error) {
  bool any_of_protocol = false;
  for (size_t i = 0; i < cameras.size(); ++i) {
    const auto &cam = cameras[i];
    if (!protocol.empty() && cam.protocol != protocol) {
      continue;
    }
    any_of_protocol = true;
    const bool match = !serial.empty()      ? cam.serial == serial
                       : !device_id.empty() ? (cam.id == device_id || cam.address == device_id)
                                            : true;
    if (match) {
      return static_cast<int>(i);
    }
  }
  const std::string kind = protocol.empty() ? "GenICam" : protocol;
  if (!any_of_protocol) {
    error = "no " + kind + " camera found";
  } else if (!serial.empty()) {
    error = "no " + kind + " camera with serial_number '" + serial + "'";
  } else {
    error = "no " + kind + " camera with device id or address '" + device_id + "'";
  }
  return -1;
}

// ---------------------------------------------------------------------------------
// Free-form GenICam features ("Name=Value", or "Name" to execute a command)

struct FeatureSetting {
  std::string name;
  std::string value;
  bool is_command = false; // no '=': execute the command feature `name`
};

// Parse one `features` entry. Names are GenICam feature names (letters, digits,
// '_'); surrounding spaces are trimmed. Returns an empty string on success.
inline std::string parse_feature(const std::string &text, FeatureSetting &out) {
  auto trim = [](std::string s) {
    const auto not_space = [](unsigned char c) { return std::isspace(c) == 0; };
    s.erase(s.begin(), std::find_if(s.begin(), s.end(), not_space));
    s.erase(std::find_if(s.rbegin(), s.rend(), not_space).base(), s.end());
    return s;
  };
  const auto eq = text.find('=');
  out.name = trim(text.substr(0, eq));
  out.is_command = eq == std::string::npos;
  out.value = out.is_command ? std::string() : trim(text.substr(eq + 1));
  if (out.name.empty()) {
    return "feature '" + text + "' has no name (use Name=Value, or Name for a command)";
  }
  for (const unsigned char c : out.name) {
    if (std::isalnum(c) == 0 && c != '_') {
      return "feature name '" + out.name + "' may only contain letters, digits and '_'";
    }
  }
  if (!out.is_command && out.value.empty()) {
    return "feature '" + out.name + "' has an empty value";
  }
  return {};
}

} // namespace camera_genicam
