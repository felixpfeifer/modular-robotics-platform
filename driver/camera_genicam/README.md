# camera_genicam

A lean ROS 2 (Jazzy) driver for **GenICam industrial cameras** on **GigE Vision (LAN)**
and **USB3 Vision**, for any vendor (Basler, Allied Vision, Lucid, Hikrobot, Daheng, FLIR,
IDS uEye+, ...). It is built on [Aravis](https://github.com/AravisProject/aravis)
(`libaravis-0.8`, LGPL-2.1+, packaged in Ubuntu 24.04), so it needs **no vendor SDK**.
Like `camera_opencv`, `camera_realsense` and `camera_ids`, it publishes only **JPEG**
`sensor_msgs/CompressedImage` on `image/compressed` (`format: "jpeg"`), so the recorder and
existing camera configs work unchanged.

## Why not camera_aravis2

[camera_aravis2](https://github.com/FraunhoferIOSB/camera_aravis2) (Fraunhofer IOSB, BSD,
`ros-jazzy-camera-aravis2`) is the general-purpose ROS 2 driver on the same library. It
publishes raw `sensor_msgs/Image` on `image_raw` through `image_transport`. The MRP recorder
validates `format == "jpeg"` and an exact `width x height` per frame. With camera_aravis2, a
second node would have to debayer, resize and re-encode every frame before the recorder
receives it. The `compressed_image_transport` plugin labels its frames `"bgr8; jpeg compressed
bgr8"`, and it does not resize. Calling libaravis directly keeps a single node with the same
parameters, failure behaviour and topic contract as the other MRP camera drivers. For
multi-camera hardware sync, PTP, chunk data or `camera_info` calibration, camera_aravis2
is the better tool.

The two drivers use the same library, so the troubleshooting below applies to both.

## Published topics

| Topic | Type | Content |
| ----- | ---- | ------- |
| `image/compressed` | `sensor_msgs/msg/CompressedImage` | BGR JPEG, `format: "jpeg"`. Mono sensors are expanded to 3 channels. |

The node does not publish `camera_info`. Messages are stamped with the host time at which
each frame arrives, like the other MRP camera drivers.

## Parameters

Set driver parameters at startup with a YAML file or `--ros-args -p`. They are
read-only while the driver is running.

| Name | Default | Description |
| ---- | ------- | ----------- |
| `serial_number` | `""` | Camera to open. Empty = select by `device_id`, or the first camera. All cameras are logged at startup. |
| `device_id` | `""` | Aravis device id (e.g. `Basler-acA1300-60gc-21234567`, shown by `arv-tool-0.8`) or the camera's IP address. |
| `transport` | `any` | `gige`, `usb3`, `any`, or `fake` (Aravis' simulated GigE camera, for tests and demos). |
| `image_width` / `image_height` | `640` / `480` | Output size: the camera image is centre-cropped to this aspect ratio and then scaled, never stretched. `0`/`0` keeps the camera image size. |
| `fps` | `30` | Frame rate (`AcquisitionFrameRate`). Exposure, region and link bandwidth can limit it; the log shows the rate the camera accepted. |
| `pixel_format` | `""` | GenICam pixel format. Empty = automatic: 8-bit Bayer first (1 byte/pixel on the wire), then BGR8/RGB8, YUV422, Mono8, Mono16/12/10. Packed formats (`Mono12p`, ...) are not supported. |
| `exposure_ms` | `0` | Fixed exposure time. `0` = use `auto_exposure`. |
| `auto_exposure` | `true` | `ExposureAuto=Continuous` (when `exposure_ms` is 0). `false` turns it off and keeps the camera's exposure time. |
| `gain_db` | `-1` | Fixed gain in dB. `-1` = use `auto_gain`. |
| `auto_gain` | `false` | `GainAuto=Continuous` (when `gain_db` is -1). `false` turns it off and keeps the camera's gain. |
| `auto_white_balance` | `true` | `BalanceWhiteAuto=Continuous` (color cameras that have it). |
| `user_set` | `""` | Load a settings set stored in the camera first (e.g. `UserSet1`, `Default`). |
| `features` | `[]` | Further GenICam features, applied **last**: `["Name=Value", ...]`, or `"Name"` to execute a command. E.g. `BinningHorizontal=2`, `Width=1280`, `OffsetX=320`, `ReverseX=true`. |
| `packet_size` | `0` | GigE: `GevSCPSPacketSize` in bytes. `0` = negotiate the largest size the network path carries (uses jumbo frames when the NIC allows). |
| `packet_delay_ns` | `0` | GigE: inter-packet delay. Use it with several cameras on one link to avoid dropped packets. |
| `frame_id` | `camera_link` | `frame_id` of the messages. |
| `jpeg_quality` | `90` | 1–100. |
| `startup_timeout_s` | `30` | How long to wait for the camera to appear (power-up, DHCP or link-local addressing). |

Order of configuration: `user_set` → trigger off, continuous acquisition → packet size →
pixel format → `fps` → exposure → gain → white balance → `features`.

For training data, fix exposure, gain and white balance (`exposure_ms`, `gain_db`,
`auto_white_balance:=false`, or a `user_set` with `auto_exposure:=false`), so the images do
not change between episodes.

## Running standalone

```bash
docker compose up --build
```

The image also builds [`mrp_camera_common`](../mrp_camera_common/README.md), so the
build context is the driver workspace, which must hold `mrp_camera_common/` next to
this repository (`docker-compose.yaml` sets this up). On bare metal, build both
packages in one colcon workspace.

With no camera at hand, add `command: ["--ros-args", "-p", "transport:=fake"]` to
`docker-compose.yaml`. The file has more examples.

### GigE Vision (LAN) setup

1. **Give the camera an IP in the subnet of a host network card.** Most cameras use DHCP
   and fall back to link-local (169.254.x.x). A direct cable works when the host NIC is also
   link-local, or has a static address in the camera's subnet. For a persistent IP, use the
   vendor tool or `arv-tool-0.8 -n <id> network` in the container.
2. **Use host networking.** `docker-compose.yaml` sets `network_mode: host`. Discovery is a UDP
   broadcast on the camera's subnet, and the camera streams UDP to the host, so a bridged
   Docker network does not work. GigE needs no `privileged` or device access.
3. **Check discovery:** `docker compose run --rm --entrypoint arv-tool-0.8 camera_genicam`
   lists the cameras, and `... arv-tool-0.8 -n <id> features` lists their features.
4. **For full resolution or several cameras**, tune the host. Example NIC: `enp3s0`.
   - Jumbo frames: `sudo ip link set enp3s0 mtu 9000`. The driver then negotiates large
     packets on its own.
   - Larger socket buffers: `sudo sysctl -w net.core.rmem_max=33554432 net.core.rmem_default=33554432`.
   - A firewall (ufw, firewalld) must not block incoming UDP from the camera.

Bandwidth: 1 Gbit/s ≈ 115 MB/s. At 1920x1200 and 30 FPS, Bayer8 needs 69 MB/s, but BGR8
needs 207 MB/s, which is too much. This is why the automatic choice prefers Bayer. Use
binning, a smaller region (`features`) or a lower `fps` when the log reports stream failures.

### USB3 Vision

Use `transport:=usb3` and give the container the USB bus. The commented lines in
`docker-compose.yaml` mount `/dev/bus/usb` and add device rule `c 189:* rmw`.

## Behaviour on failure

If the GigE heartbeat reports that control was lost (cable pulled, camera power-cycled,
another host took control), the node exits with status 1; see also
[Reliability](#reliability-health-and-diagnostics).
`restart: unless-stopped` then starts it again. Only one host can control a GigE camera at a
time. Close vendor viewers before starting the driver.

## In the MRP app

The image carries the MRP camera driver labels (`io.mrp.driver.kind=camera` and
`io.mrp.driver.manifest`, see the `Dockerfile`). Once `mrp-camera-genicam` is on the deployment
host (`./start.sh` builds it), the app lists **GenICam (USB3 Vision, Aravis)** under *Found on this
host* in a camera module's type. No catalogue change is needed. Cells run it like the RealSense
driver: USB bus access only, no privileges, `serial_number` from the setup page, and `fps` passed
as a double. The manifest has no USB vendor id, because USB3 Vision cameras come from many
vendors. So the connection test does not look for the camera on USB; it opens it instead.

GigE Vision is still standalone only. Cell services do not get host networking, which GigE
discovery and streaming need (the IDS GigE path has the same limitation). GigE in cells needs:

1. A deployment-plan access mode that grants host networking (or a macvlan network on the
   camera NIC) only to this image, checked in `mrp_app.deployment.check_plan` like `usb_bus`.
2. A device scan for the connection test (`arv-tool-0.8` in the image, run with host
   networking).

## Tests

`colcon test` runs these tests:

- `test_genicam_utils`: unit tests for pixel-format choice, Bayer/YUV/Mono conversion
  (including the GenICam→OpenCV Bayer pattern mapping), camera selection and feature syntax.
- `fake_camera_smoke`: starts the real node against Aravis' simulated GigE camera and checks
  that the frames on `image/compressed` are JPEG at the configured size.

No camera or network is needed. `./ci.local` runs both and builds the image.

## Not yet verified

The camera calls are tested only against Aravis' simulated camera. Check these with the first
real camera:

- GigE discovery and streaming from a container with host networking, and the packet-size
  negotiation with jumbo frames;
- `ExposureAuto`/`GainAuto`/`BalanceWhiteAuto` and `user_set` on your vendor's camera.
  Feature names follow the GenICam SFNC, but some vendors differ;
- USB3 Vision access with the mounted USB bus.

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

Frame timestamps are Aravis' host system timestamp of each buffer (taken when the
frame starts to arrive), not the time the frame was handed to the node.
