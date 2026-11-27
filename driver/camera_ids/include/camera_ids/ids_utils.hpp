#pragma once

// Pure helpers for the IDS uEye driver. No uEye SDK dependency, so they can be
// unit-tested (and built in CI) on machines without the SDK or a camera. Image
// helpers (JPEG, crop-and-scale) are in mrp_camera_common.

#include <string>
#include <vector>

namespace camera_ids {

// One entry of the uEye camera list, reduced to what selection needs.
struct CameraEntry {
  std::string serial;
  std::string model;
  int camera_id = 0; // user-definable ID stored in the camera (often 1 on every camera)
  int device_id = 0; // assigned by the driver; unique while the daemon runs
  bool in_use = false;
};

// Choose the camera to open: by serial number if given, else by camera ID if
// > 0, else the first camera that is not in use. Returns the index into
// `cameras`, or -1 with `error` set.
inline int select_camera(const std::vector<CameraEntry> &cameras, const std::string &serial,
                         int camera_id, std::string &error) {
  if (cameras.empty()) {
    error = "no IDS uEye camera found";
    return -1;
  }
  for (size_t i = 0; i < cameras.size(); ++i) {
    const auto &cam = cameras[i];
    const bool match =
        !serial.empty() ? cam.serial == serial : (camera_id <= 0 || cam.camera_id == camera_id);
    if (!match) {
      continue;
    }
    if (cam.in_use) {
      if (!serial.empty() || camera_id > 0) {
        error = "camera " + cam.serial + " is already in use by another process";
        return -1;
      }
      continue; // automatic choice: try the next free camera
    }
    return static_cast<int>(i);
  }
  if (!serial.empty()) {
    error = "no IDS uEye camera with serial_number '" + serial + "'";
  } else if (camera_id > 0) {
    error = "no IDS uEye camera with camera_id " + std::to_string(camera_id);
  } else {
    error = "all IDS uEye cameras are in use";
  }
  return -1;
}

// uEye takes the parameter_file path as wchar_t; only ASCII paths convert reliably
// without a locale. Returns false for anything else.
inline bool ascii_to_wide(const std::string &text, std::wstring &out) {
  out.clear();
  for (const char c : text) {
    const auto byte = static_cast<unsigned char>(c);
    if (byte == 0 || byte > 127) {
      return false;
    }
    out.push_back(static_cast<wchar_t>(byte));
  }
  return true;
}

} // namespace camera_ids
