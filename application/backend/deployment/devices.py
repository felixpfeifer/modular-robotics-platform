"""Host device discovery and read-only hardware probes for the deployment agent.

Discovery reads sysfs (visible inside the agent container), so the agent needs no /dev
access. Anything that talks to a device runs in a short-lived, network-less container that
receives exactly that one device node. Nothing here starts a cell or moves a motor.
"""

import base64
import json
import os
import re
import subprocess
import threading
from pathlib import Path

from mrp_app import cameras
from mrp_app.calibration import CALIBRATION_NAME, JOINT_IDS, validate_calibration  # noqa: F401

SERIAL_NAME = re.compile(r"tty(ACM|USB)\d{1,3}")
VIDEO_NAME = re.compile(r"video\d{1,3}")
ARM_IMAGE = os.environ.get("MRP_ARM_IMAGE", "mrp-robot-so101")
CAMERA_IMAGE = os.environ.get("MRP_CAMERA_IMAGE", "mrp-episode-recorder")
CALIBRATION_VOLUME = "mrp-calibration"
WORKSPACE_VOLUME = "mrp-cell-workspace"
ROLES = ("leader", "follower")
# Known USB-serial bridges used on SO-101 controller boards (QinHeng CH340/CH343, FTDI, CP210x).
KNOWN_BRIDGES = {"1a86", "0403", "10c4"}


def _text(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def _usb_parent(node):
    """Nearest parent directory that is a USB device (has idVendor)."""
    path = Path(node).resolve()
    for candidate in [path, *path.parents]:
        if (candidate / "idVendor").is_file():
            return candidate
    return None


def scan_serial(sys_root="/sys"):
    ports = []
    base = Path(sys_root) / "class/tty"
    for entry in sorted(base.glob("tty*")) if base.is_dir() else []:
        if not SERIAL_NAME.fullmatch(entry.name):
            continue
        usb = _usb_parent(entry / "device")
        vendor = _text(usb / "idVendor") if usb else ""
        ports.append(
            {
                "port": f"/dev/{entry.name}",
                "vendor_id": vendor,
                "product_id": _text(usb / "idProduct") if usb else "",
                "manufacturer": _text(usb / "manufacturer") if usb else "",
                "product": _text(usb / "product") if usb else "",
                "serial": _text(usb / "serial") if usb else "",
                "likely_so101": vendor in KNOWN_BRIDGES,
            }
        )
    return ports


def scan_video(sys_root="/sys"):
    cameras = []
    base = Path(sys_root) / "class/video4linux"
    for entry in (
        sorted(base.glob("video*"), key=lambda p: int(p.name[5:]) if p.name[5:].isdigit() else 0)
        if base.is_dir()
        else []
    ):
        if not VIDEO_NAME.fullmatch(entry.name):
            continue
        usb = _usb_parent(entry / "device")
        removable = _text(usb / "removable") if usb else ""
        capture = _text(entry / "index") in ("", "0")  # uvcvideo: index 1+ are metadata nodes
        cameras.append(
            {
                "device": f"/dev/{entry.name}",
                "card": _text(entry / "name"),
                "usb": usb is not None,
                "vendor_id": _text(usb / "idVendor") if usb else "",
                "serial": _text(usb / "serial") if usb else "",
                # Laptop cameras are fixed (non-removable) USB devices or not USB at all.
                "integrated": usb is None or removable == "fixed",
                "capture": capture,
            }
        )
    # External capture devices first, integrated cameras last.
    return sorted((c for c in cameras if c["capture"]), key=lambda c: (c["integrated"], c["device"]))


# USB IDs of cameras that a vendor SDK opens (no V4L2 node): vendor, product text that must match.
SDK_CAMERA_USB = {"ids_ueye": ("1409", ""), "realsense": ("8086", "realsense")}


def scan_usb(sys_root="/sys"):
    """Every USB device (not interface) with its IDs, product name and serial number."""
    devices = []
    base = Path(sys_root) / "bus/usb/devices"
    for entry in sorted(base.iterdir()) if base.is_dir() else []:
        if ":" in entry.name or not (entry / "idVendor").is_file():
            continue
        devices.append(
            {
                "vendor_id": _text(entry / "idVendor"),
                "product_id": _text(entry / "idProduct"),
                "product": _text(entry / "product"),
                "serial": _text(entry / "serial"),
            }
        )
    return devices


def sdk_cameras(model, sys_root="/sys", usb=None):
    """The connected USB devices that look like a ``model`` camera (IDS uEye, RealSense).

    ``usb`` is a custom model's ``{"vendor_id", "product"}`` hint. None when the model gives no
    way to recognise its camera on USB (then only the driver itself can tell).
    """
    if model in SDK_CAMERA_USB:
        vendor, product = SDK_CAMERA_USB[model]
    elif usb:
        vendor, product = usb["vendor_id"], usb.get("product", "")
    else:
        return None
    return [
        d
        for d in scan_usb(sys_root)
        if d["vendor_id"] == vendor and product in d["product"].lower().replace(" ", "")
    ]


def discover_camera_images(run=subprocess.run):
    """Local images labelled as MRP camera drivers: ``({model id: model}, [problems])``.

    Only labels are read (``docker image inspect``); nothing is started. A broken label is
    reported, not fatal, so one bad image does not hide the others.
    """
    listed = docker(
        ["image", "ls", "--filter", f"label={cameras.LABEL_KIND}={cameras.KIND_CAMERA}",
         "--format", "{{.Repository}}:{{.Tag}}"], 30, run,
    )  # fmt: skip
    found, problems = {}, []
    if listed.returncode:
        return found, [f"Could not list Docker images: {(listed.stderr or '').strip()[:200]}"]
    for ref in sorted(set(listed.stdout.split())):
        if "<none>" in ref:
            continue
        inspected = docker(["image", "inspect", "--format", "{{json .Config.Labels}}", ref], 30, run)
        try:
            parsed = cameras.parse_labels(json.loads(inspected.stdout or "null"), ref)
        except (ValueError, cameras.CameraModelError) as error:
            problems.append(str(error) if ref in str(error) else f"{ref}: {error}")
            continue
        if parsed is None:
            continue
        ident, model = parsed
        if ident in found:
            problems.append(
                f"{ref}: camera id '{ident}' is also used by {found[ident]['image']}; kept that one."
            )
            continue
        found[ident] = model
    return found, problems


def pull_image(image, run=subprocess.run):
    """``docker pull`` a validated camera driver image. Returns ``{"ok", "detail"}``."""
    if not cameras.IMAGE_REFERENCE.fullmatch(image or ""):
        raise ValueError("Not a valid image reference.")
    result = docker(["pull", image], 900, run)
    tail = ((result.stdout or "") + (result.stderr or "")).strip().splitlines()[-1:] or [""]
    return {"ok": result.returncode == 0, "detail": tail[0][:300]}


def image_present(image, run=subprocess.run):
    """The image exists locally; cells start with --pull never, so a missing image fails late."""
    return docker(["image", "inspect", "--format", "{{.Id}}", image], 30, run).returncode == 0


def is_wsl(proc_version="/proc/version"):
    return "microsoft" in _text(proc_version).lower()


def scan(sys_root="/sys"):
    serial, video = scan_serial(sys_root), scan_video(sys_root)
    hints = []
    if not serial:
        hints.append(
            "No serial devices found. Plug in both arms"
            + (
                ", then in Windows (admin PowerShell) run `usbipd list` and "
                "`usbipd attach --wsl --busid <BUSID>` for each arm."
                if is_wsl()
                else " and check the USB cables."
            )
        )
    if not [c for c in video if not c["integrated"]]:
        hints.append(
            "No external USB camera found."
            + (
                " On WSL attach it with `usbipd attach --wsl` (the kernel needs UVC support)."
                if is_wsl()
                else ""
            )
        )
    return {"serial": serial, "video": video, "wsl": is_wsl(), "hints": hints}


def resolve(spec_entry, kind, sys_root="/sys"):
    """Re-resolve a saved selection to its current device node, by serial number when known.

    ttyACM numbering changes when a device is re-attached; the USB serial number does not.
    Returns the node path, or raises ValueError. The result always comes from a fresh scan,
    never from a caller-supplied path alone.
    """
    key = "port" if kind in ROLES else "device"
    found = scan_serial(sys_root) if kind in ROLES else scan_video(sys_root)
    paths = {item[key]: item for item in found}
    wanted, serial = spec_entry.get(key), spec_entry.get("serial")
    if serial:
        matches = [item[key] for item in found if item.get("serial") == serial]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            if wanted in matches:
                return wanted
            raise ValueError(f"More than one {kind} device has serial {serial}; select it again.")
    if wanted in paths:
        return wanted
    raise ValueError(f"The {kind} device {wanted or '(none)'} is not connected. Re-attach it and scan again.")


def docker(arguments, timeout=60, run=subprocess.run):
    result = run(["docker", *arguments], capture_output=True, text=True, timeout=timeout, check=False)
    return result


def _json_output(result):
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        detail = (result.stderr or result.stdout or "no output").strip()[-400:]
        return {"ok": False, "error": f"Probe failed: {detail}"}


def probe_arm(
    port, tools_dir, command="scan", extra=(), mount_calibration=False, timeout=60, run=subprocess.run
):
    """Run so101_probe.py against one port in a throwaway container."""
    arguments = [
        "run", "--rm", "--network", "none", "--device", f"{port}:{port}",
        "-v", f"{Path(tools_dir) / 'robot_so101/tools'}:/tools:ro",
    ]  # fmt: skip
    if mount_calibration:
        arguments += ["-v", f"{CALIBRATION_VOLUME}:/calibration"]
    arguments += ["--entrypoint", "python3", ARM_IMAGE, "/tools/so101_probe.py", command, port, *extra]
    return _json_output(docker(arguments, timeout, run))


def probe_camera(
    device, tools_dir, width=640, height=480, fps=30.0, seconds=3.0, snapshot=False, run=subprocess.run
):
    arguments = [
        "run", "--rm", "--network", "none", "--device", f"{device}:{device}",
        "-v", f"{Path(tools_dir) / 'camera_opencv/tools'}:/tools:ro",
        "--entrypoint", "python3", CAMERA_IMAGE, "/tools/camera_probe.py", device,
        "--width", str(int(width)), "--height", str(int(height)), "--fps", str(float(fps)),
        "--seconds", str(float(seconds)),
    ]  # fmt: skip
    if snapshot:
        arguments.append("--snapshot")
    return _json_output(docker(arguments, 30 + int(seconds), run))


# Sourced when present: the MRP base image layout, then a plain ROS image's (custom drivers).
PROBE_SETUP = (
    'for f in /opt/platform/install/setup.bash /app/install/setup.bash; do [ -f "$f" ] && source "$f"; done; '
    '[ -n "${AMENT_PREFIX_PATH:-}" ] || source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash; '
)


def probe_sdk_camera(
    image, driver, topic, width, height, fps, probe_dir, seconds=3.0, run=subprocess.run, access="usb_bus"
):
    """Open an SDK camera (RealSense, IDS) with its own driver image in a throwaway container.

    The container gets only the USB bus, no network (ROS runs over Fast DDS inside it) and is
    removed afterwards, also when the probe times out. ``driver`` is the node command line.
    A ``network`` camera gets the default bridge network instead of the USB bus.
    """
    name = f"mrp-camera-probe-{os.getpid()}-{threading.get_ident() % 100000}"
    reach = (
        ["--network", "bridge"]
        if access == "network"
        else ["--network", "none", "-v", "/dev/bus/usb:/dev/bus/usb", "--device-cgroup-rule", "c 189:* rmw"]
    )
    arguments = [
        "run", "--rm", "--name", name, *reach,
        "-e", "RMW_IMPLEMENTATION=rmw_fastrtps_cpp",
        "-v", f"{Path(probe_dir) / 'sdk_camera_probe.py'}:/probe/sdk_camera_probe.py:ro",
        "--entrypoint", "bash", image, "-c",
        PROBE_SETUP + 'exec python3 /probe/sdk_camera_probe.py "$@"', "--",
        "--topic", topic, "--width", str(int(width)), "--height", str(int(height)), "--fps", str(float(fps)),
        "--seconds", str(float(seconds)), "--startup", "40", "--", *driver,
    ]  # fmt: skip
    if image == "mrp-camera-ids":
        arguments[2:2] = ["--cap-add", "NET_ADMIN", "--cap-add", "SYS_NICE"]
    try:
        return _json_output(docker(arguments, 90 + int(seconds), run))
    except subprocess.TimeoutExpired:
        docker(["rm", "-f", name], 30, run)
        return {"ok": False, "error": "The camera test timed out; the test container was removed."}


def identify_leader(ports, tools_dir, seconds=5.0, run=subprocess.run):
    """Wiggle test: the arm the operator moves by hand (the passive leader) shows the most travel.

    Both ports are watched at the same time. The result is a suggestion; the user confirms it.
    """
    if len(ports) != 2 or ports[0] == ports[1]:
        raise ValueError("Select two different serial ports.")
    results = {}

    def watch(port):
        results[port] = probe_arm(
            port, tools_dir, "watch", ["--seconds", str(seconds)], timeout=int(seconds) + 40, run=run
        )

    threads = [threading.Thread(target=watch, args=(port,)) for port in ports]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for port, report in results.items():
        if report.get("ok") is False or "total_travel" not in report:
            raise ValueError(f"Cannot read {port}: {report.get('error', 'no data')}")
    travel = {port: results[port]["total_travel"] for port in ports}
    leader, other = sorted(ports, key=lambda p: -travel[p])
    margin = travel[leader] - travel[other]
    return {
        "travel": travel,
        "suggested_leader": leader if margin > 100 else None,
        "suggested_follower": other if margin > 100 else None,
        "detail": (
            "Move only the LEADER arm (the one without motors) by hand."
            if margin <= 100
            else "The arm that moved is suggested as the leader."
        ),
    }


def snapshot_b64(report):
    """Validate the base64 JPEG returned by camera_probe before it reaches the UI."""
    data = report.get("jpeg_base64")
    if not data:
        return None
    raw = base64.b64decode(data, validate=True)
    return data if raw.startswith(b"\xff\xd8") else None


def list_calibrations(run=subprocess.run):
    """Calibration files stored in the calibration volume (names only)."""
    result = docker(
        [
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            f"{CALIBRATION_VOLUME}:/c:ro",
            "--entrypoint",
            "ls",
            ARM_IMAGE,
            "/c",
        ],
        30,
        run,
    )
    if result.returncode:
        return []
    return sorted(n for n in result.stdout.split() if CALIBRATION_NAME.fullmatch(n))


def read_calibrations(run=subprocess.run):
    """Name -> content of every valid calibration file in the calibration volume (invalid ones are skipped)."""
    script = (
        "import json,os,sys;d='/c';print(json.dumps({n:open(os.path.join(d,n)).read() "
        "for n in sorted(os.listdir(d)) if n.endswith(('.yaml','.yml')) and os.path.isfile(os.path.join(d,n))"
        " and os.path.getsize(os.path.join(d,n))<=8000}))"
    )
    result = docker(
        ["run", "--rm", "--network", "none", "-v", f"{CALIBRATION_VOLUME}:/c:ro", "--entrypoint", "python3",
         ARM_IMAGE, "-c", script],
        30, run,
    )  # fmt: skip
    if result.returncode:
        raise ValueError("Cannot read the calibration volume: " + (result.stderr or result.stdout)[-200:])
    found = json.loads(result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}")
    clean = {}
    for name, text in found.items():
        try:
            if CALIBRATION_NAME.fullmatch(name):
                clean[name] = validate_calibration(text)
        except ValueError:
            continue
    return clean


def render_cell_config(root, params, calibration_files=None, run=subprocess.run):
    """Generate the recorder configuration for this start from the project's settings.

    The result goes into the workspace volume that the recorder, bridge, exporter and the
    application read. For a real robot ``calibration_files`` names every real arm's calibration
    and their digest becomes the recordings' provenance. Multi-arm cells derive their robot
    configs from the recorder's, mounted read-only. Returns the calibration hash.
    """
    arguments = [
        "run", "--rm", "--network", "none",
        "-v", f"{CALIBRATION_VOLUME}:/calibration:ro",
        "-v", f"{WORKSPACE_VOLUME}:/out",
        "-v", f"{Path(root) / 'application/backend/deployment/cell-templates'}:/src:ro",
        "-v", f"{Path(root) / 'core/recorder/config/robots'}:/robots:ro",
        "--entrypoint", "python3", ARM_IMAGE, "/src/render_cell_config.py", "/out", json.dumps(params),
    ]  # fmt: skip
    if calibration_files:
        arguments += ["/calibration", *calibration_files]
    arguments += ["--robots", "/robots"]
    result = docker(arguments, 3600 if os.environ.get("MRP_IMAGE_PULL_POLICY") == "missing" else 60, run)
    if result.returncode:
        raise ValueError(
            "Cannot generate the recording configuration: " + (result.stderr or result.stdout)[-300:]
        )
    return result.stdout.strip()


def import_calibration(name, text, run=subprocess.run):
    """Store an uploaded, validated calibration file in the calibration volume."""
    if not CALIBRATION_NAME.fullmatch(name or ""):
        raise ValueError("Calibration file name must look like leader.yaml.")
    clean = validate_calibration(text)
    result = run(
        ["docker", "run", "--rm", "-i", "--network", "none", "-v", f"{CALIBRATION_VOLUME}:/c", "--entrypoint", "sh",
         ARM_IMAGE, "-c", 'cat > "/c/$0"', name],
        input=clean, capture_output=True, text=True, timeout=30, check=False,
    )  # fmt: skip
    if result.returncode:
        raise ValueError("Cannot store the calibration file: " + (result.stderr or result.stdout)[-200:])
    return name
