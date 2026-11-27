# camera_opencv

A minimal ROS 2 (Jazzy) camera driver that captures frames from a V4L2 video
device with OpenCV, JPEG-encodes them, and publishes them as
`sensor_msgs/CompressedImage`.

It is intended for the **color stream of an Intel RealSense** camera (which Linux
exposes as a standard UVC `/dev/videoX` node), but works with any V4L2 device
including a laptop webcam.

## Published topics

| Topic               | Type                              | Description              |
| ------------------- | --------------------------------- | ------------------------ |
| `image/compressed`  | `sensor_msgs/msg/CompressedImage` | JPEG-encoded color frames |

## Parameters

Set driver parameters at startup with a YAML file or `--ros-args -p`. They are
read-only while the driver is running.

- **`video_device`** *(string, default `auto`)* — `auto` scans `/dev/video*` and
  prefers the RealSense **color** node, then falls back to an external USB color
  camera. Only cameras whose USB port reports `removable=fixed` count as built-in;
  ports that report `unknown` (common on desktops and Jetsons) count as external. Set an explicit path (e.g. `/dev/video0`) to bypass detection.
- **`image_width`** *(int, default `640`)* — requested capture width.
- **`image_height`** *(int, default `480`)* — requested capture height.
- **`fps`** *(int, default `30`)* — requested capture frame rate.
- **`frame_id`** *(string, default `camera_link`)* — `frame_id` set on the message header.
- **`jpeg_quality`** *(int, default `90`)* — 1–100.
- **`pixel_format`** *(string, default empty)* — V4L2 FOURCC to request, e.g. `MJPG`
  (needed by many webcams above 640×480 @ 30 FPS on USB 2) or `YUYV`. Empty keeps
  OpenCV's choice. `tools/camera_probe.py --pixel-format` uses the same default, so
  the probe measures the mode the driver will run.

Startup logs both requested and actual V4L2 width, height, and FPS. A camera
that cannot provide the requested dimensions is rejected. The episode recorder
independently measures the delivered rate and enforces the production 30 FPS
profile.

### RealSense auto-detection

The RealSense presents several V4L2 nodes (depth → `Z16`, infrared → `Y8`,
color → `YUYV`/`MJPEG`, plus metadata nodes). With `video_device:=auto`, the
node scans `/dev/video*` for external USB capture devices that advertise a
color format and prefers cards whose V4L2 name contains `RealSense`. This is
robust against the `/dev/videoX` numbers changing between reboots/replugs.

> **Scope:** this driver only provides the **color** image. It does **not**
> provide depth, infrared, or stream alignment. For those, use the official
> [`realsense2_camera`](https://github.com/IntelRealSense/realsense-ros) package
> (librealsense), not this OpenCV/V4L2 driver.

## Running

### Bare metal

```bash
# In a workspace that also contains mrp_camera_common:
colcon build --symlink-install
source install/setup.bash

# Auto-detect the RealSense color stream (default):
ros2 run camera_opencv camera_node

# Or pin a specific device:
ros2 run camera_opencv camera_node --ros-args -p video_device:=/dev/video2
```

### Docker Compose

```bash
docker compose up --build
```

The image also builds [`mrp_camera_common`](../mrp_camera_common/README.md), so the
build context is the driver workspace, which must hold `mrp_camera_common/` next to
this repository (`docker-compose.yaml` sets this up). On bare metal, build both
packages in one colcon workspace.

The container runs in `network_mode: host`, is `privileged`, and mounts `/dev`
so it can access the camera. By default the node auto-detects the RealSense color
stream. To pin a device instead, add a `command` to `docker-compose.yaml`:

```yaml
    command: ["--ros-args", "-p", "video_device:=/dev/video2"]
```

(The image entrypoint forwards these arguments to `ros2 run camera_opencv camera_node`.)

## Finding the right device manually

If auto-detection picks the wrong node, identify the color device yourself:

```bash
sudo apt install v4l-utils
v4l2-ctl --list-devices                       # find the RealSense entries
v4l2-ctl -d /dev/videoX --list-formats-ext    # the color node lists YUYV / MJPG
```

For a stable path that survives reboots, use the persistent symlink:

```bash
ls -l /dev/v4l/by-id/
# e.g. /dev/v4l/by-id/usb-Intel_R__RealSense_TM__Depth_Camera_435i_...-video-index2
```

## Notes

- Frame timestamps are taken with `this->now()` immediately after `grab()`. This
  is the closest approximation to the hardware sensor time achievable without
  custom V4L2 ioctls to translate `CLOCK_MONOTONIC` → `CLOCK_REALTIME`.
- Capture runs in a dedicated thread so the blocking `grab()` does not stall ROS
  executors.

## Reliability, health and diagnostics

Shared by all MRP camera drivers through
[`mrp_camera_common`](../mrp_camera_common/README.md):

- If no frames are published for 10 seconds (JPEG), the node exits with status 1,
  so `restart: unless-stopped` starts it again. The watchdog runs outside the capture
  loop, so this also works when a camera call hangs; a loop that does not return
  within 5 s after that makes the process exit immediately.
- The image `HEALTHCHECK` reports healthy only while frames flow: the node refreshes
  `$MRP_CAMERA_HEARTBEAT_FILE` and the check tests its age. No ROS tooling is
  involved, so it works with `rmw_zenoh` and with renamed nodes.
- `/diagnostics` carries one status per stream each second: measured FPS against the
  configured rate, bitrate, dropped frames and the time since the last frame.
