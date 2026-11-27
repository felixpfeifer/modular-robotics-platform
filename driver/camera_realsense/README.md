# camera_realsense

A lean ROS 2 (Jazzy) driver for Intel RealSense cameras, built directly on
librealsense2. Like `camera_opencv`, it only publishes **compressed** images
(`sensor_msgs/CompressedImage`), which are small to record and easy to feed to
VLA models. Unlike `camera_opencv`, it can **optionally** publish depth that is
aligned to the color image.

- **Color (always on):** JPEG on `image/compressed`, `format: "jpeg"`. This uses
  the same topic, format and parameter names as `camera_opencv`, so the recorder
  and existing camera configs (e.g. `top_rgb_30.yaml`) work unchanged.
- **Depth (off by default):** set `enable_depth:=true` to also publish lossless
  16-bit PNG depth in **millimetres** on `depth/compressed`.

Use `camera_opencv` if a plain V4L2 webcam is enough. Use this driver when you
want a RealSense with exact intrinsics, hardware timestamps, and (now or later)
depth. Both drivers open the camera's color sensor, so run only one per camera.

## Published topics

| Topic | Type | When | Content |
| ----- | ---- | ---- | ------- |
| `image/compressed` | `sensor_msgs/msg/CompressedImage` | always | BGR JPEG, `format: "jpeg"` |
| `camera_info` | `sensor_msgs/msg/CameraInfo` | `publish_camera_info` | Factory color intrinsics |
| `depth/compressed` | `sensor_msgs/msg/CompressedImage` | `enable_depth` | uint16 mm PNG, `format: "16UC1; png compressed 16UC1"`, `0` = no depth |
| `depth/camera_info` | `sensor_msgs/msg/CameraInfo` | `enable_depth` + `publish_camera_info` | Depth intrinsics (the color intrinsics when aligned) |

## Parameters

Set driver parameters at startup with a YAML file or `--ros-args -p`. They are
read-only while the driver is running.

| Name | Default | Description |
| ---- | ------- | ----------- |
| `serial_number` | `""` | Camera to open. Empty = the first one found. All cameras are logged at startup. |
| `image_width` / `image_height` | `640` / `480` | Color resolution. If the camera cannot provide it, the node refuses to start (it never resizes). |
| `fps` | `30` | Frame rate for color, and for depth when enabled. |
| `frame_id` | `camera_link` | `frame_id` of color messages, and of aligned depth messages. |
| `jpeg_quality` | `90` | 1–100. |
| `enable_depth` | `false` | Publish depth as well. |
| `depth_width` / `depth_height` | `640` / `480` | Depth resolution the sensor captures at. With `align_depth`, the output takes the color resolution. |
| `align_depth` | `true` | Reproject depth into the color image, so pixel (u,v) matches in both images. |
| `depth_frame_id` | `camera_depth_frame` | `frame_id` of depth messages when `align_depth:=false`. |
| `png_compression` | `1` | 0–9. 1 is much faster than higher levels and only slightly larger, which matters on a Jetson. |
| `max_depth_mm` | `0` | Depth beyond this value becomes `0` (invalid). `0` = no limit. |
| `publish_camera_info` | `true` | Publish the `camera_info` topics. |
| `hardware_timestamps` | `true` | Stamp messages with librealsense global time (the sensor clock mapped to the host clock) when available. Falls back to ROS time sampled when the frameset arrives and always uses ROS time with `use_sim_time`. |

## Running

### Bare metal

```bash
sudo apt install ros-jazzy-librealsense2 libopencv-dev
colcon build && source install/setup.bash   # workspace with mrp_camera_common

ros2 run camera_realsense camera_node                                 # color only
ros2 run camera_realsense camera_node --ros-args -p enable_depth:=true  # color + aligned depth
```

On bare metal, the user needs USB access to the camera: install Intel's udev
rules (`99-realsense-libusb.rules`), or run as root.

### Docker Compose

```bash
docker compose up --build
```

The image also builds [`mrp_camera_common`](../mrp_camera_common/README.md), so the
build context is the driver workspace, which must hold `mrp_camera_common/` next to
this repository (`docker-compose.yaml` sets this up). On bare metal, build both
packages in one colcon workspace.

The container is `privileged`, mounts `/dev` and uses `network_mode: host`. To
enable depth, add a `command` to `docker-compose.yaml`:

```yaml
    command: ["--ros-args", "-p", "enable_depth:=true"]
```

The Compose service uses `restart: unless-stopped` to restart the node after a
capture failure.

## Using the data

```python
import cv2, numpy as np

rgb = cv2.imdecode(
    np.frombuffer(color_msg.data, np.uint8), cv2.IMREAD_COLOR
)  # HxWx3 BGR uint8
depth = cv2.imdecode(
    np.frombuffer(depth_msg.data, np.uint8), cv2.IMREAD_UNCHANGED
)  # HxW uint16, mm
```

The depth `format` string follows the `compressed_image_transport` convention,
so `image_transport`-based viewers should be able to show the `depth` base topic
through the `compressed` transport. This has not been tested yet.

## Notes and limits

- See [Reliability](#reliability-health-and-diagnostics): color and depth are
  watched separately.
- **Depth is not recorded yet:** the episode recorder only accepts JPEG camera
  streams. Recording depth requires a depth stream type in the recorder and in
  the LeRobot conversion.
- Depth costs USB bandwidth and CPU (alignment and PNG). At 640×480 @ 30 FPS it
  needs a USB 3 port. The node prints a warning at startup if the camera is on
  USB 2.
- With depth enabled, color and depth come from one synchronised frameset. Each
  message keeps the timestamp of its own sensor frame.

## Reliability, health and diagnostics

Shared by all MRP camera drivers through
[`mrp_camera_common`](../mrp_camera_common/README.md):

- If no frames are published for 10 seconds (color, or depth when enabled), the node exits with status 1,
  so `restart: unless-stopped` starts it again. The watchdog runs outside the capture
  loop, so this also works when a camera call hangs; a loop that does not return
  within 5 s after that makes the process exit immediately.
- The image `HEALTHCHECK` reports healthy only while frames flow: the node refreshes
  `$MRP_CAMERA_HEARTBEAT_FILE` and the check tests its age. No ROS tooling is
  involved, so it works with `rmw_zenoh` and with renamed nodes.
- `/diagnostics` carries one status per stream each second: measured FPS against the
  configured rate, bitrate, dropped frames and the time since the last frame.
