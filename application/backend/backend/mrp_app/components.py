"""Cell components: every arm and camera of a cell, in one normalised form.

A cell spec describes its hardware in one of two ways:

* the original single-pair keys: ``leader``/``follower``/``camera``, ``devices``,
  ``settings.camera``/``settings.side_camera`` and ``settings.teleop.joint_mapping``;
* lists, usually derived from the workspace layout: ``arms`` (one entry per leader or follower arm)
  and ``cameras`` (one entry per camera). Either list may be used without the other.

``expand`` turns both forms into the same ``{"arms": [...], "cameras": [...]}``, and ``topology`` adds
what the deployment needs: Compose service names, ROS namespaces and topics. One leader driving one
follower keeps the original topology, so existing cells, recordings and datasets are unchanged.
With more arms, every arm runs in its own namespace and the arm adapter presents them to the
arbiter and the recorder as one combined robot (see docs/architecture/0003-multi-arm-cells.md).
"""

import re

from . import arms as arm_models
from . import cameras as camera_models

MAX_PER_ROLE = 4
MAX_CAMERAS = 6
ARM_ID = re.compile(r"[a-z][a-z0-9_]{0,15}")
CAMERA_ID = re.compile(r"[a-z][a-z0-9_]{0,23}")
RESERVED_ARM_IDS = {"adapter"}  # `arm_adapter` is the adapter service
PORT = re.compile(r"/dev/(ttyACM\d{1,3}|ttyUSB\d{1,3}|serial/by-id/[A-Za-z0-9._:+-]{1,120})")
VIDEO = re.compile(r"/dev/(video\d{1,3}|v4l/by-id/[A-Za-z0-9._:+-]{1,120})")
CALIBRATION_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,60}\.ya?ml")
JOINT = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")
MAPPING_KEYS = {"leader_joint", "scale", "leader_reference_rad", "follower_reference_rad"}
ARM_BACKENDS = {"leader": ("mock", "real"), "follower": ("mock", "gazebo", "real")}


def camera_sources():
    """Mock sources plus one real source per camera model (the model's driver), custom ones included."""
    return (*camera_models.MOCK_SOURCES, *camera_models.models())


CAMERA_RANGES = {"width": (160, 1920), "height": (120, 1080), "fps": (5, 60)}
CAMERA_DEFAULTS = {"width": 640, "height": 480, "fps": 30}
LEGACY_CAMERAS = (("webcam", "camera", "camera"), ("side", "side_camera", "side_camera"))


class ComponentError(ValueError):
    pass


def _text(value, label, maximum=60):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ComponentError(f"{label} must be text up to {maximum} characters.")
    return value


def validate_joint_mapping(mapping, label="settings.teleop.joint_mapping"):
    """Shape and ranges only: whether the joints exist is checked against the robot profile at start."""
    if not isinstance(mapping, dict) or len(mapping) > 32:
        raise ComponentError(f"{label} must map follower joint names to settings.")
    clean = {}
    for joint, entry in mapping.items():
        if not JOINT.fullmatch(str(joint)) or not isinstance(entry, dict) or set(entry) - MAPPING_KEYS:
            raise ComponentError(f"{label}.{joint} may only contain: {', '.join(sorted(MAPPING_KEYS))}.")
        item = {}
        for key, value in entry.items():
            if key == "leader_joint":
                if not isinstance(value, str) or not JOINT.fullmatch(value):
                    raise ComponentError(f"{label}.{joint}.leader_joint is not a joint name.")
            else:
                low, high = (-10.0, 10.0) if key == "scale" else (-6.3, 6.3)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                    raise ComponentError(f"{label}.{joint}.{key} must be a number from {low} to {high}.")
                if key == "scale" and abs(value) < 0.01:
                    raise ComponentError(f"{label}.{joint}.scale must not be zero.")
            item[key] = value
        clean[joint] = item
    return clean


def _device(entry, label, kind):
    """A device entry: an arm's serial port (+ calibration) or a camera's video node."""
    key, pattern = ("port", PORT) if kind == "arm" else ("device", VIDEO)
    allowed = {key, "serial"} | ({"calibration"} if kind == "arm" else {"card"})
    if not isinstance(entry, dict) or set(entry) - allowed:
        raise ComponentError(f"{label} may only contain: {', '.join(sorted(allowed))}.")
    clean = dict(entry)
    if key in clean and (not isinstance(clean[key], str) or not pattern.fullmatch(clean[key])):
        raise ComponentError(f"{label}.{key} must be a serial or video device path under /dev.")
    if "calibration" in clean and (
        not isinstance(clean["calibration"], str) or not CALIBRATION_FILE.fullmatch(clean["calibration"])
    ):
        raise ComponentError(f"{label}.calibration must be a plain .yaml file name.")
    for field in ("serial", "card"):
        if field in clean and (not isinstance(clean[field], str) or len(clean[field]) > 120):
            raise ComponentError(f"{label}.{field} must be a short string.")
    return clean


def _arms(raw):
    if not isinstance(raw, list) or not 2 <= len(raw) <= 2 * MAX_PER_ROLE:
        raise ComponentError(
            f"arms must list 2 to {2 * MAX_PER_ROLE} arms (at least one leader and one follower)."
        )
    allowed = {
        "id",
        "role",
        "backend",
        "model",
        "variant",
        "name",
        "module",
        "leader",
        "device",
        "joint_mapping",
    }
    clean, ids = [], set()
    for index, entry in enumerate(raw):
        label = f"arms[{index}]"
        if not isinstance(entry, dict) or set(entry) - allowed or not {"id", "role", "backend"} <= set(entry):
            raise ComponentError(
                f"{label} needs id, role and backend (optional: {', '.join(sorted(allowed - {'id', 'role', 'backend'}))})."
            )
        ident, role, backend = entry["id"], entry["role"], entry["backend"]
        if not isinstance(ident, str) or not ARM_ID.fullmatch(ident) or ident in RESERVED_ARM_IDS:
            raise ComponentError(
                f"{label}.id must be 1-16 lowercase letters, digits or '_', starting with a letter."
            )
        if ident in ids:
            raise ComponentError(f"Arm id '{ident}' is used twice.")
        ids.add(ident)
        label = f"Arm '{ident}'"
        if role not in ARM_BACKENDS:
            raise ComponentError(f"{label}: role must be leader or follower.")
        if backend not in ARM_BACKENDS[role]:
            raise ComponentError(f"{label}: backend must be one of {', '.join(ARM_BACKENDS[role])}.")
        model = entry.get("model", arm_models.DEFAULT_MODEL)
        try:
            arm_models.check_arm(role, model, backend)
        except arm_models.ArmError as error:
            raise ComponentError(f"{label}: {error}") from None
        arm = {"id": ident, "role": role, "backend": backend, "model": model}
        try:
            variant = arm_models.check_variant(model, entry.get("variant"))
        except arm_models.ArmError as error:
            raise ComponentError(f"{label}: {error}") from None
        if variant:
            arm["variant"] = variant
        for key in ("name", "module"):
            if key in entry:
                arm[key] = _text(entry[key], f"{label}.{key}")
        if "device" in entry:
            if backend != "real":
                raise ComponentError(f"{label}: a device is only used by a real arm.")
            arm["device"] = _device(entry["device"], f"{label}.device", "arm")
        if role == "leader":
            if "leader" in entry or "joint_mapping" in entry:
                raise ComponentError(f"{label}: leader and joint_mapping belong to followers.")
        else:
            if "leader" in entry:
                arm["leader"] = entry["leader"]
            arm["joint_mapping"] = validate_joint_mapping(
                entry.get("joint_mapping", {}), f"{label}.joint_mapping"
            )
        clean.append(arm)
    leaders = [a for a in clean if a["role"] == "leader"]
    followers = [a for a in clean if a["role"] == "follower"]
    if not leaders or not followers or len(leaders) > MAX_PER_ROLE or len(followers) > MAX_PER_ROLE:
        raise ComponentError(f"A cell needs 1 to {MAX_PER_ROLE} leaders and 1 to {MAX_PER_ROLE} followers.")
    by_id = {a["id"]: a for a in leaders}
    for follower in followers:
        if "leader" not in follower:
            if len(leaders) > 1:
                raise ComponentError(f"Arm '{follower['id']}': choose which leader drives it.")
            follower["leader"] = leaders[0]["id"]
        leader = by_id.get(follower["leader"])
        if leader is None:
            raise ComponentError(
                f"Arm '{follower['id']}': leader '{follower['leader']}' is not a leader arm of this cell."
            )
        if follower["backend"] == "real" and leader["backend"] != "real":
            raise ComponentError(
                f"Arm '{follower['id']}' is real, so it can only be driven by a real leader; "
                f"'{leader['id']}' is {leader['backend']}."
            )
        try:
            arm_models.check_pair(leader["model"], follower["model"])
        except arm_models.ArmError as error:
            raise ComponentError(f"Arm '{follower['id']}': {error}") from None
    idle = [a["id"] for a in leaders if not any(f["leader"] == a["id"] for f in followers)]
    if idle:
        raise ComponentError(f"Leader '{idle[0]}' drives no follower.")
    if any(a["backend"] == "gazebo" for a in clean) and len(clean) != 2:
        raise ComponentError(
            "The Gazebo scene simulates one follower; multi-arm cells use mock or real arms."
        )
    ports = [a["device"]["port"] for a in clean if "port" in a.get("device", {})]
    if len(set(ports)) != len(ports):
        raise ComponentError("Each arm must use a different serial port.")
    return clean


def _cameras(raw):
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_CAMERAS:
        raise ComponentError(
            f"cameras must list 1 to {MAX_CAMERAS} cameras; the recorder needs at least one."
        )
    allowed = {"id", "source", "model", "variant", "name", "module", "device", "width", "height", "fps"}
    clean, ids = [], set()
    for index, entry in enumerate(raw):
        label = f"cameras[{index}]"
        if not isinstance(entry, dict) or set(entry) - allowed or not {"id", "source"} <= set(entry):
            raise ComponentError(
                f"{label} needs id and source (optional: model, variant, name, module, device, width, height, fps)."
            )
        ident, source = entry["id"], entry["source"]
        if not isinstance(ident, str) or not CAMERA_ID.fullmatch(ident):
            raise ComponentError(
                f"{label}.id must be 1-24 lowercase letters, digits or '_', starting with a letter."
            )
        if ident in ids:
            raise ComponentError(f"Camera id '{ident}' is used twice.")
        ids.add(ident)
        label = f"Camera '{ident}'"
        if source not in camera_sources():
            raise ComponentError(f"{label}: source must be one of {', '.join(camera_sources())}.")
        camera = {"id": ident, "source": source}
        # The model is the camera's type from the layout; a real camera runs that model's driver.
        model = entry.get("model", source if camera_models.is_real(source) else camera_models.DEFAULT_MODEL)
        if camera_models.is_real(source) and model != source:
            raise ComponentError(f"{label}: a real camera uses its model's driver ({model}), not {source}.")
        try:
            camera_models.check_camera(model, entry.get("variant"))
        except camera_models.CameraModelError as error:
            raise ComponentError(f"{label}: {error}") from None
        camera["model"] = model
        if entry.get("variant"):
            camera["variant"] = entry["variant"]
        for key, (low, high) in CAMERA_RANGES.items():
            value = entry.get(key, CAMERA_DEFAULTS[key])
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ComponentError(f"{label}: {key} must be a whole number from {low} to {high}.")
            camera[key] = value
        for key in ("name", "module"):
            if key in entry:
                camera[key] = _text(entry[key], f"{label}.{key}")
        if "device" in entry:
            if not camera_models.is_real(source):
                raise ComponentError(f"{label}: a device is only used by a real camera.")
            if source == "opencv_usb":
                camera["device"] = _device(entry["device"], f"{label}.device", "camera")
            else:
                try:
                    camera["device"] = camera_models.check_device(source, entry["device"])
                except camera_models.CameraModelError as error:
                    raise ComponentError(f"{label}: {error}") from None
        clean.append(camera)
    if any(c["source"] == "gazebo_scene" for c in clean) and len(clean) != 1:
        raise ComponentError("The Gazebo scene renders one camera.")
    nodes = [c["device"]["device"] for c in clean if "device" in c.get("device", {})]
    if len(set(nodes)) != len(nodes):
        raise ComponentError("Each camera must use a different video device.")
    # SDK cameras are told apart by serial number; without one the driver opens the first it finds.
    # Network cameras by their address.
    for model, info in camera_models.models().items():
        same = [c for c in clean if c["source"] == model and model != "opencv_usb"]
        key = "address" if info["access"] == "network" else "serial"
        values = [c.get("device", {}).get(key) or "" for c in same]
        if len(same) > 1 and ("" in values or len(set(values)) != len(values)):
            what = "address" if key == "address" else "serial number"
            raise ComponentError(f"With several {info['label']} cameras, give each a different {what}.")
    return clean


def validate_lists(spec):
    """Validate the list form of a spec. Returns ``{"arms": ..., "cameras": ...}`` for the lists given."""
    result = {}
    if "arms" in spec:
        result["arms"] = _arms(spec["arms"])
    if "cameras" in spec:
        result["cameras"] = _cameras(spec["cameras"])
    return result


def aggregates(lists):
    """The single-pair keys a list-form spec stands for; preset matching works on these."""
    derived = {}
    if "arms" in lists:
        backends = {role: {a["backend"] for a in lists["arms"] if a["role"] == role} for role in ARM_BACKENDS}
        derived["leader"] = "real" if "real" in backends["leader"] else "mock"
        derived["follower"] = next((b for b in ("real", "gazebo") if b in backends["follower"]), "mock")
    if "cameras" in lists:
        sources = {c["source"] for c in lists["cameras"]}
        # Presets only know "a real camera" (opencv_usb); every real model counts as one.
        real = any(camera_models.is_real(s) for s in sources)
        derived["camera"] = (
            "gazebo_scene" if "gazebo_scene" in sources else ("opencv_usb" if real else "synthetic")
        )
    return derived


def expand(spec, settings):
    """Every arm and camera of a validated spec, whichever form it uses."""
    devices = spec.get("devices") or {}
    if "arms" in spec:
        arms = [dict(arm) for arm in spec["arms"]]
    else:
        arms = [
            {"id": "leader", "role": "leader", "backend": spec["leader"],
             "model": spec.get("leader_model", arm_models.DEFAULT_MODEL)},
            {"id": "follower", "role": "follower", "backend": spec["follower"],
             "model": spec.get("follower_model", arm_models.DEFAULT_MODEL), "leader": "leader",
             "joint_mapping": dict(settings["teleop"]["joint_mapping"])},
        ]  # fmt: skip
        for arm in arms:
            if arm["id"] in devices:
                arm["device"] = dict(devices[arm["id"]])
    if "cameras" in spec:
        cameras = [dict(camera) for camera in spec["cameras"]]
    else:
        cameras = []
        for ident, group, role in LEGACY_CAMERAS:
            values = settings[group]
            if role == "side_camera" and not values["enabled"]:
                continue
            source = spec["camera"] if role == "camera" else values["source"]
            camera = {"id": ident, "source": source, **{k: values[k] for k in CAMERA_DEFAULTS}}
            if role in devices:
                camera["device"] = dict(devices[role])
            cameras.append(camera)
    by_role = {role: [a for a in arms if a["role"] == role] for role in ARM_BACKENDS}
    for arm in arms:
        if arm["backend"] == "real":
            device = arm.setdefault("device", {})
            only = len(by_role[arm["role"]]) == 1
            device.setdefault("calibration", f"{arm['role']}.yaml" if only else f"{arm['id']}.yaml")
    return {"arms": arms, "cameras": cameras}


def topology(components):
    """Add Compose services, ROS namespaces and topics. One leader + one follower keeps the original wiring."""
    arms, cameras = components["arms"], components["cameras"]
    multi = sum(a["role"] == "leader" for a in arms) > 1 or sum(a["role"] == "follower" for a in arms) > 1
    first = set()
    for arm in arms:
        if arm["role"] not in first:
            first.add(arm["role"])
            arm["service"] = arm["role"]
            arm["namespace"] = f"arm_{arm['id']}" if multi else ("leader" if arm["role"] == "leader" else "")
        else:
            arm["service"] = f"arm_{arm['id']}"
            arm["namespace"] = f"arm_{arm['id']}"
        prefix = f"/{arm['namespace']}" if arm["namespace"] else ""
        arm["joint_states_topic"] = f"{prefix}/joint_states"
        if arm["role"] == "follower":
            arm["bridge"] = "bridge" if arm["service"] == "follower" else f"bridge_{arm['id']}"
            arm["intent_topic"] = (
                f"/platform/control/arms/{arm['id']}/joint_intent"
                if multi
                else "/platform/control/joint_intent"
            )
    for index, camera in enumerate(cameras):
        camera["service"] = ("camera", "camera2")[index] if index < 2 else f"camera_{camera['id']}"
        camera["env_prefix"] = ("CAMERA", "CAMERA2")[index] if index < 2 else None
        camera["topic"] = f"/{camera['id']}/image/compressed"
    return {"arms": arms, "cameras": cameras, "multi_arm": multi}
