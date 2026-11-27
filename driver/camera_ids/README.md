# camera_ids

A lean ROS 2 (Jazzy) driver for **IDS uEye cameras** ("UI-" models) connected by
**USB 2, USB 3 or GigE (LAN)**, built on the uEye API of the **IDS Software Suite**.
Like `camera_opencv` and `camera_realsense`, it publishes only **JPEG**
`sensor_msgs/CompressedImage` on `image/compressed` (`format: "jpeg"`), so the
recorder and existing camera configs work unchanged.

## Why a separate container and SDK

uEye UI cameras are **not** USB3 Vision / GigE Vision (GenICam) devices, and they are
not V4L2 webcams. Before first use, a USB uEye camera reports itself as
`1409:1000 IDS Imaging ... generic (firmware not loaded yet)`. The IDS daemons
`ueyeusbd` (USB) and `ueyeethd` (GigE) upload the firmware and give the uEye API
access to the camera. This image installs the SDK and starts the daemons itself,
before the node.

For IDS **uEye+** cameras (U3V / GigE Vision, IDS peak), a GenICam-based driver is
the better fit. IDS peak can also open UI cameras through its "uEye Transport
Layer", but that still needs the IDS Software Suite.

## Getting the IDS SDK

You need a free IDS account to download the IDS Software Suite, so the image build cannot
fetch it.

1. On the IDS website, download **IDS Software Suite for Linux, Debian package**
   (4.96 or later): the 64-bit (amd64) variant for the workstation and the arm64
   variant for the Jetson.
2. Put the downloads in `driver/camera_ids/sdk/`. The Software Suite archives are tracked with Git LFS, and a
   bind mount keeps the archives out of the image layers. Each build installs only the
   packages for its own architecture.
3. Build locally with `docker compose build`, or from the workspace root with
   `./start.sh`, which builds it when the SDK is present.

**IDS peak is not enough.** The `ids-peak*.tar.gz` archives are skipped. IDS peak opens
uEye UI cameras only through its uEye transport layer (`ids_ueyegentl.cti`), which
needs `libueye_api` and the USB daemon from the IDS Software Suite. Those are not in
the IDS peak archives. IDS peak is only useful for uEye+ (USB3 Vision / GigE Vision)
cameras, which this driver does not use.

Packages whose names match `demo|cockpit|tools-qt|manual|halcon` are skipped: the GUI
tools would pull in a Qt desktop, and the manuals and HALCON interface are not used. Change that with `--build-arg IDS_SDK_EXCLUDE=...` (empty = install
everything).

## Building in the private lab project

The two Software Suite 4.96.1 Debian archives are tracked with Git LFS. Verify that
the IDS license permits sharing them with your lab before uploading them. Keep the
GitLab project private and enable Git LFS. From a real checkout of the private project:

```bash
git lfs install
git add .gitattributes .gitignore .dockerignore .gitlab-ci.yml README.md sdk/README.md docker/install-ids-sdk.sh sdk/ids-software-suite-linux-*-debian.tgz
git commit -m "Build IDS camera driver using SDK in Git LFS"
git push
```

CI checks out the LFS objects and builds each architecture on its matching native
runner. It does not publish an image. Lab members can clone with Git LFS installed
and build on their own machines using `./start.sh`. The image contains IDS
software and remains subject to its license.

## Published topics

| Topic | Type | Content |
| ----- | ---- | ------- |
| `image/compressed` | `sensor_msgs/msg/CompressedImage` | BGR JPEG, `format: "jpeg"`. Mono sensors are expanded to 3 channels. |

The node does not publish `camera_info`, because uEye cameras carry no factory
intrinsics. Messages are stamped with the host time at which each frame arrives.

## Parameters

Set driver parameters at startup with a YAML file or `--ros-args -p`. They are
read-only while the driver is running.

| Name | Default | Description |
| ---- | ------- | ----------- |
| `serial_number` | `""` | Camera to open. Empty = select by `camera_id`, or the first free camera. All cameras are logged at startup. |
| `camera_id` | `0` | User-definable camera ID (set with IDS Camera Manager). `0` = any. Many cameras ship with ID 1, so prefer `serial_number`. |
| `image_width` / `image_height` | `640` / `480` | Output image size: the full sensor view is centre-cropped to this aspect ratio and then scaled, never stretched (a 1280×1024 sensor at 640×480 loses 32 rows at the top and bottom). `0`/`0` keeps the native sensor size or AOI from `parameter_file`. |
| `fps` | `30` | Target frame rate. The camera runs at the nearest supported rate, which can be lower for full-sensor capture. |
| `pixel_clock_mhz` | `0` | Pixel clock. `0` = camera default, which is often too low for the target `fps`. |
| `exposure_ms` | `0` | Fixed exposure time. `0` = use `auto_exposure`. |
| `auto_exposure` | `true` | Automatic exposure (when `exposure_ms` is 0). |
| `gain` | `-1` | Fixed hardware master gain, 0–100 (other values stop the node at startup). `-1` = use `auto_gain`. |
| `auto_gain` | `false` | Automatic gain (when `gain` is -1). |
| `auto_white_balance` | `true` | Automatic white balance (color sensors only). |
| `parameter_file` | `""` | Camera settings `.ini` saved from IDS uEye Cockpit, loaded before the parameters above. Use it for binning, subsampling, hot pixels, etc. |
| `frame_id` | `camera_link` | `frame_id` of the messages. |
| `jpeg_quality` | `90` | 1–100. |
| `startup_timeout_s` | `30` | How long to wait for the camera to appear (firmware upload, GigE discovery). |

For training data, fix the exposure, gain and white balance (or load a
`parameter_file`), so the images do not change between episodes.

## In the MRP app

1. On the **Cell** page, select the camera module and set its **type** to *IDS uEye (UI
   cameras)*.
2. On the **Components** page, switch that camera to **Real**. Enter the serial number,
   or leave it empty to use the first free camera. Only USB works in cells for now.

The agent starts `mrp-camera-ids` with the USB bus (`/dev/bus/usb` and the USB device
cgroup rule) and the topic, size and FPS of the cell. Get the image first with
`./start.sh`, which builds it when the SDK is present.

## Running standalone

```bash
docker compose up --build
```

The image also builds [`mrp_camera_common`](../mrp_camera_common/README.md), so the
build context is the driver workspace, which must hold `mrp_camera_common/` next to
this repository (`docker-compose.yaml` sets this up). On bare metal, build both
packages in one colcon workspace.

The container is `privileged`, mounts `/dev` and uses `network_mode: host`, because
the camera re-enumerates on the USB bus after the firmware upload. To configure the
camera, add a `command` to `docker-compose.yaml`; there are examples in the file.

- **USB:** works without extra settings (`IDS_USB=1` is the default).
- **GigE (LAN):** set `IDS_ETH=1`. The camera needs an IP address in the subnet of a
  host network card. Assign it with IDS Camera Manager, or with the IP tools of the
  SDK, and set it up as the IDS Software Suite manual describes for the ETH daemon.

Do not run the IDS daemons on the host at the same time. Two USB daemons would
compete for the same camera.

See [Reliability](#reliability-health-and-diagnostics) for restarts, the
healthcheck and `/diagnostics`.

## Hardware verification

The driver builds against the Linux amd64 uEye SDK 4.96.1. The unit tests
exercise the SDK-independent helpers. A hardware run should verify:

- the package layout of the IDS `.deb` download and the daemon paths (the install
  script prints both);
- that the daemons start in the container without systemd/udev, and that the first
  USB camera is found after the firmware upload;
- GigE discovery and IP configuration with `IDS_ETH=1`.

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
