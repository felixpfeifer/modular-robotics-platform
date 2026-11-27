# mrp_camera_common

Header-only ROS 2 (Jazzy) package shared by the MRP camera drivers
(`camera_opencv`, `camera_realsense`, `camera_genicam`, `camera_ids`). A driver only
opens, configures and reads its camera; everything else is here, so every driver
behaves the same way.

| Header | What it provides |
| --- | --- |
| `camera_node.hpp` | `CameraNode` base class and `run_camera_node()` (`main`) |
| `image.hpp` | `encode_jpeg`, `fit_to_size` (centre crop to the output aspect ratio, then scale), `JPEG_FORMAT` |
| `frame_stats.hpp` | `FrameStats` (rate/bitrate windows), `StallWatchdog` |
| `heartbeat.hpp` | `HeartbeatFile` for the container healthcheck |
| `parameters.hpp` | read-only parameter descriptors with ranges |

## Behaviour every driver gets

- **Capture thread.** `start_capture(loop)` runs the driver's loop in its own thread.
  An exception that escapes the loop logs the error, stops the node and makes the
  process exit with status 1, so `restart: unless-stopped` brings it back.
- **Watchdog.** A 1 Hz timer on the executor thread, independent of the loop. If a
  stream publishes nothing for 10 s, the node stops with status 1, even when the loop
  is stuck in a blocking SDK call. If the loop then does not return within 5 s, the
  process exits immediately (`std::_Exit(1)`): a hung camera call cannot be
  interrupted any other way.
- **Diagnostics.** One `diagnostic_msgs/DiagnosticStatus` per stream on `/diagnostics`
  each second: measured FPS against the configured rate (WARN below 90 %), bitrate,
  dropped frames, time since the last frame (ERROR after 2 s), the camera's serial
  number as `hardware_id`.
- **Heartbeat.** When `MRP_CAMERA_HEARTBEAT_FILE` is set (the driver images set it),
  the file's modification time is refreshed while every stream delivers frames. The
  image `HEALTHCHECK` only checks the file's age, so it works with any RMW (including
  `rmw_zenoh` without a router) and with renamed nodes.
- **Images are never distorted.** Drivers that scale (GenICam, IDS) use
  `fit_to_size`: the sensor image is centre-cropped to the output aspect ratio and
  then scaled. A 1280×1024 sensor published at 640×480 loses 32 rows at the top and
  bottom instead of being squeezed.

## Writing a driver

```cpp
class MyCameraNode : public mrp_camera_common::CameraNode {
public:
  MyCameraNode() : CameraNode("camera_node") {
    // declare parameters with mrp_camera_common::read_only*(), open the camera ...
    stream_ = add_stream("color", fps);
    start_capture([this]() { loop(); });
  }
  ~MyCameraNode() override {
    stop_capture(); // first: the loop uses this class's members
    // close the camera
  }

private:
  void loop() {
    while (capture_running()) {
      report_stats();
      // wait for a frame (with a timeout), encode, publish, then:
      frame_published(stream_, bytes); // or frame_dropped(stream_)
    }
  }
  StreamId stream_{};
};

int main(int argc, char **argv) {
  return mrp_camera_common::run_camera_node<MyCameraNode>(argc, argv);
}
```

## Checks (CI and local)

`ci/driver-check.sh PACKAGE [apt packages...]` runs in the MRP ROS base image from
the repository root of the package under test. It checks that `.clang-format`,
`.clang-tidy` and `test/.clang-tidy` match this repository's copies, then runs
clang-format, a build with warnings as errors, the unit tests, clang-tidy on every
compiled file, and the tests again under AddressSanitizer and
UndefinedBehaviorSanitizer. The GitLab jobs and `./ci.local` of every driver call it.

Locally, the drivers expect this repository next to them:

```
driver/
├── mrp_camera_common/
├── camera_opencv/
└── ...
```

The driver images are built with that directory as the context, for example
`docker compose -f camera_opencv/docker-compose.yaml build`.
