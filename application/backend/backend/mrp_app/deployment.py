"""Validation boundary for the vetted deployment presets.

Mock and simulation presets get no device access at all. The real-hardware presets may map
exactly the serial ports and camera node the operator selected (and the agent re-verified)
into exactly the service that needs them, and nothing else.
"""

import os
import re

MOCK_SERVICES = {
    "zenoh_router",
    "leader",
    "leader_motion",
    "follower",
    "control",
    "camera",
    "camera2",
    "bridge",
    "recorder",
    "convert",
    "upload",
}
PRESET_SERVICES = {
    "mock-so101": set(MOCK_SERVICES),
    "hwleader-so101": set(MOCK_SERVICES),
    "real-so101": set(MOCK_SERVICES),
    "sim-so101": {
        "zenoh_router",
        "leader",
        "follower",
        "control",
        "camera_compressor",
        "bridge",
        "recorder",
        "task_monitor",
        "convert",
        "upload",
    },
}
ALLOWED_BACKENDS = {
    "mock-so101": {"leader": "mock", "follower": "mock"},
    "hwleader-so101": {"leader": "real", "follower": "mock"},
    "real-so101": {"leader": "real", "follower": "real"},
    "sim-so101": {"leader": "mock", "follower": "gazebo"},
}


USB_BUS = "/dev/bus/usb"
USB_CGROUP_RULE = "c 189:* rmw"


def _device_source(device):
    """Host path of a Compose device entry (short string or long-form mapping)."""
    if isinstance(device, dict):
        return str(device.get("source", ""))
    return str(device).split(":", 1)[0]


# Extra services a multi-arm or multi-camera cell adds to the mock-family presets.
EXTRA_SERVICE = re.compile(r"(arm|bridge|camera|leader_motion)_[a-z][a-z0-9_]{0,23}|arm_adapter")
# The arm backends each preset may run at all; a cell narrows this per service.
PRESET_BACKENDS = {
    "mock-so101": {"leader": {"mock"}, "follower": {"mock"}},
    "hwleader-so101": {"leader": {"mock", "real"}, "follower": {"mock"}},
    "real-so101": {"leader": {"mock", "real"}, "follower": {"mock", "real"}},
    "sim-so101": {"leader": {"mock"}, "follower": {"gazebo"}},
}


def check_plan(plan, preset_id="mock-so101", devices=None, extra=None):
    """Validate a rendered plan. ``devices`` maps service name -> the one host device it may get.

    ``extra`` describes a cell with more arms or cameras: ``{"services": set of added service
    names, "arms": {service: (role, backend)}}`` for every arm service, base ones included.
    """
    if preset_id not in PRESET_SERVICES:
        raise ValueError("Unknown deployment preset.")
    devices = devices or {}
    extra = extra or {}
    added = set(extra.get("services", ()))
    if added and (preset_id == "sim-so101" or not all(EXTRA_SERVICE.fullmatch(n) for n in added)):
        raise ValueError("Only mock-family presets can add arm, bridge and camera services.")
    expected = {name: ALLOWED_BACKENDS[preset_id][name] for name in ("leader", "follower")}
    for name, (role, backend) in (extra.get("arms") or {}).items():
        if backend not in PRESET_BACKENDS[preset_id][role]:
            raise ValueError(f"The {preset_id} preset cannot run a {backend} {role}.")
        expected[name] = backend
    services = plan.get("services", {})
    if set(services) != PRESET_SERVICES[preset_id] | added:
        raise ValueError("Preset must contain exactly the approved services.")
    usb_bus = dict(extra.get("usb_bus") or {})
    for name, service in services.items():
        # SDK cameras (RealSense, IDS) talk libusb and may re-enumerate: they alone get the USB bus,
        # and only with their catalogue image. Never privileged, never more than USB device nodes.
        bus_camera = name in usb_bus and service.get("image") == usb_bus[name]
        caps = service.get("cap_add") or []
        if caps and not (
            bus_camera and service.get("image") == "mrp-camera-ids" and set(caps) == {"NET_ADMIN", "SYS_NICE"}
        ):
            raise ValueError("Only IDS camera services may use the required capabilities.")
        if service.get("privileged"):
            raise ValueError("Presets cannot run privileged or widen device cgroup rules.")
        rules = service.get("device_cgroup_rules") or []
        if rules and not (bus_camera and rules == [USB_CGROUP_RULE]):
            raise ValueError("Presets cannot run privileged or widen device cgroup rules.")
        requested = {_device_source(device) for device in service.get("devices") or []}
        if requested and requested != {devices.get(name)}:
            raise ValueError("Presets cannot access physical devices beyond the ones selected for the cell.")
        for mount in service.get("volumes", []):
            if (
                bus_camera
                and mount.get("type") == "bind"
                and mount.get("source") == USB_BUS
                and mount.get("target") == USB_BUS
            ):
                continue
            if mount.get("type") == "bind" and (
                str(mount.get("source", "")).startswith("/dev")
                or "docker.sock" in str(mount.get("source", ""))
            ):
                raise ValueError("Presets cannot mount devices or the Docker socket.")
        is_arm = name in expected or (name.startswith("arm_") and name != "arm_adapter")
        if is_arm and service.get("environment", {}).get("BACKEND") != expected.get(name):
            raise ValueError("Only the approved arm backends are allowed.")
    return plan


def check_mock_plan(plan):
    return check_plan(plan, "mock-so101")


def _source_bind(mount, source_root):
    """A read-only bind of workspace source code, mounted over a published image."""
    if not source_root or mount.get("type") != "bind" or not mount.get("read_only"):
        return False
    root = os.path.normpath(str(source_root))
    source = os.path.normpath(str(mount.get("source", "")))
    return os.path.isabs(source) and os.path.commonpath([root, source]) == root


def check_training_plan(plan, source_root=None):
    services = plan.get("services", {})
    if set(services) != {"train", "hub_import"} or services["train"].get("network_mode") != "none":
        raise ValueError("Training must be an offline trainer plus the Hub importer.")
    for service in services.values():
        if service.get("devices") or service.get("privileged"):
            raise ValueError("Training cannot access devices.")
        if any(
            m.get("type") == "bind" and not _source_bind(m, source_root) for m in service.get("volumes", [])
        ):
            raise ValueError("Training services may only use named volumes.")
    return plan


def check_policy_plan(plan, source_root=None):
    services = plan.get("services", {})
    if set(services) != {"act_server", "policy_source"}:
        raise ValueError("Policy deployment must contain exactly the server and source.")
    for service in services.values():
        if service.get("devices") or service.get("privileged"):
            raise ValueError("Policy containers cannot access devices.")
        for mount in service.get("volumes", []):
            if _source_bind(mount, source_root):
                continue
            if mount.get("type") == "bind" or not mount.get("read_only"):
                raise ValueError("Policy containers may only mount the checkpoint volume read-only.")
    return plan
