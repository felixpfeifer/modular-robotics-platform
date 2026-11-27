#pragma once

// A file whose modification time shows that frames are flowing. The container
// HEALTHCHECK checks its age; that needs no ROS tooling, works with any RMW and
// any node name (cells rename the node), and reports "healthy" only while the
// camera actually delivers images.

#include <cstdlib>
#include <string>
#include <utility>

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace mrp_camera_common {

inline constexpr const char *HEARTBEAT_ENV = "MRP_CAMERA_HEARTBEAT_FILE";

class HeartbeatFile {
public:
  explicit HeartbeatFile(std::string path) : path_(std::move(path)) {}

  // The path from MRP_CAMERA_HEARTBEAT_FILE; disabled when the variable is unset or empty.
  static HeartbeatFile from_environment() {
    const char *path = std::getenv(HEARTBEAT_ENV);
    return HeartbeatFile(path != nullptr ? path : "");
  }

  bool enabled() const { return !path_.empty(); }
  const std::string &path() const { return path_; }

  // Creates the file if needed and sets its modification time to now.
  bool touch() const {
    if (!enabled()) {
      return false;
    }
    const int fd = ::open(path_.c_str(), O_WRONLY | O_CREAT | O_CLOEXEC, 0644);
    if (fd < 0) {
      return false;
    }
    const bool ok = ::futimens(fd, nullptr) == 0;
    ::close(fd);
    return ok;
  }

private:
  std::string path_;
};

} // namespace mrp_camera_common
