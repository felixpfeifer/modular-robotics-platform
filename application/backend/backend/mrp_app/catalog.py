"""Component catalog and cell composition rules.

A project's cell is a choice of components (leader, follower, camera, task) with
a backend each. Choices are validated against this catalog and resolved to a
vetted deployment preset that the agent can run. Anything marked ``planned``
is shown in the UI but can never be selected or deployed. Real hardware is
selectable, but the deployment agent only starts it after a passing connection
test and an explicit operator confirmation.
"""

from . import arms, cameras, components
from .arms import ArmError
from .components import CALIBRATION_FILE, PORT, VIDEO, ComponentError

AVAILABLE, PLANNED = "available", "planned"

COMPONENTS = {
    "leader": {
        "label": "Leader arm (teleoperation input)",
        "options": {
            "mock": {"label": "SO-101 mock (ros2_control)", "status": AVAILABLE},
            "real": {
                "label": "SO-101 leader (USB serial)",
                "status": AVAILABLE,
                "note": "Needs a calibration file and a passing connection test before the cell can start.",
            },
        },
    },
    "follower": {
        "label": "Follower arm (robot)",
        "options": {
            "mock": {"label": "SO-101 mock (ros2_control)", "status": AVAILABLE},
            "gazebo": {"label": "SO-101 in Gazebo physics", "status": AVAILABLE},
            "real": {
                "label": "SO-101 follower (USB serial)",
                "status": AVAILABLE,
                "note": "Powers real motors: needs a real leader, calibration and an operator confirmation.",
            },
        },
    },
    "camera": {
        "label": "Camera",
        "options": {
            "synthetic": {
                "label": "Synthetic test pattern",
                "status": AVAILABLE,
                "note": "Checks the data pipeline only; it does not show the robot.",
            },
            "gazebo_scene": {"label": "Rendered tabletop camera", "status": AVAILABLE},
            "opencv_usb": {
                "label": "USB webcam (OpenCV)",
                "status": AVAILABLE,
                "note": "Pick the external USB camera, not the laptop's integrated one.",
            },
        },
    },
}

TASKS = {
    "pipeline_check": {
        "label": "Pipeline check (synthetic)",
        "instruction": "Exercise mock tracking and synthetic webcam recording.",
        "synthetic": True,
    },
    "red_cube_to_rectangle": {
        "label": "Red cube to green rectangle",
        "instruction": "Grasp the red cube and place it inside the green rectangle.",
        "synthetic": False,
    },
    "free_teleop": {
        "label": "Free teleoperation",
        "instruction": "Teleoperate the follower with the leader arm and demonstrate the task you want to teach.",
        "synthetic": False,
    },
    "scene_motion_check": {
        "label": "Scene motion check",
        "instruction": "Move the simulated SO-101 to the neutral pose while observing the rendered tabletop.",
        "synthetic": False,
    },
}

# Supported combinations -> vetted deployment preset. Extend by adding a preset
# to the agent and a row here; the UI and validation follow automatically.
PRESETS = {
    "mock-so101": {
        "label": "Mock SO-101 (optionally with a USB camera)",
        "match": {"leader": "mock", "follower": "mock", "camera": ["synthetic", "opencv_usb"]},
        "tasks": ["pipeline_check"],
        "domain": 42,
        "camera_topic": "/webcam/image/compressed",
        "image_feature": "observation.images.webcam",
        "simulation": False,
        "family": "mock",
        "robot": "so101",  # robot profile: driver/*/profile.json with this id
        "models": {"leader": "so101", "follower": "so101"},  # arms.ARMS ids
        "hardware": [],
    },
    "hwleader-so101": {
        "label": "Real SO-101 leader + mock follower (no motors move)",
        "match": {"leader": "real", "follower": "mock", "camera": ["synthetic", "opencv_usb"]},
        "tasks": ["pipeline_check"],
        "domain": 42,
        "camera_topic": "/webcam/image/compressed",
        "image_feature": "observation.images.webcam",
        "simulation": False,
        "family": "mock",
        "robot": "so101",  # robot profile: driver/*/profile.json with this id
        "models": {"leader": "so101", "follower": "so101"},  # arms.ARMS ids
        "hardware": ["leader"],
    },
    "real-so101": {
        "label": "Real SO-101 leader + follower",
        "match": {"leader": "real", "follower": "real", "camera": ["synthetic", "opencv_usb"]},
        "tasks": ["free_teleop"],
        "domain": 42,
        "camera_topic": "/webcam/image/compressed",
        "image_feature": "observation.images.webcam",
        "simulation": False,
        "family": "mock",
        "robot": "so101",  # robot profile: driver/*/profile.json with this id
        "models": {"leader": "so101", "follower": "so101"},  # arms.ARMS ids
        "hardware": ["leader", "follower"],
    },
    "sim-so101": {
        "label": "Gazebo tabletop SO-101",
        "match": {"leader": "mock", "follower": "gazebo", "camera": "gazebo_scene"},
        "tasks": ["red_cube_to_rectangle", "scene_motion_check"],
        "domain": 43,
        "camera_topic": "/top_camera/image/compressed",
        "image_feature": "observation.images.top",
        "simulation": True,
        "family": "sim",
        "robot": "so101",  # robot profile: driver/*/profile.json with this id
        "models": {"leader": "so101", "follower": "so101"},  # arms.ARMS ids
        "hardware": [],
    },
}

# Policies the Train and Deploy steps can offer. Only ``available`` ones are wired end to end.
POLICIES = {
    "act": {
        "label": "ACT (LeRobot)",
        "status": AVAILABLE,
        "note": "Train on CPU here, on a GPU server via a generated notebook, or import a checkpoint.",
        "training": ["local_cpu", "notebook", "import"],
    },
    "diffusion": {
        "label": "Diffusion Policy (LeRobot)",
        "status": PLANNED,
        "note": "Not wired into training or deployment yet.",
    },
    "groot_n1": {
        "label": "NVIDIA GR00T N1",
        "status": PLANNED,
        "note": (
            "Needs an NVIDIA GPU and the Isaac-GR00T fine-tuning/serving stack, which this application "
            "does not run. Planned: export a dataset in the layout GR00T expects and hand off to a GPU node."
        ),
    },
}

# Containers that can train and/or serve a policy. ``needs_gpu`` runtimes are only offered where the
# deployment agent reports an NVIDIA GPU (locally); a remote server you start yourself is always allowed.
RUNTIMES = {
    "lerobot_act": {
        "label": "LeRobot ACT (this app's image)",
        "protocol": "http",
        "schemes": ["http"],
        "default_port": 8092,
        "needs_gpu": False,
        "local_train": True,
        "local_serve": True,
        "hub_download": True,
        "note": "Small checkpoints; can be downloaded into this app.",
    },
    "lerobot_async": {
        "label": "LeRobot async policy server (official)",
        "protocol": "grpc",
        "schemes": ["grpc"],
        "default_port": 8080,
        "needs_gpu": False,
        "local_train": False,
        "local_serve": True,
        "hub_download": False,
        "note": "Official lerobot.async_inference policy_server (ACT, SmolVLA, pi0). The server pulls the model itself.",
    },
    "groot": {
        "label": "NVIDIA GR00T (official Isaac-GR00T)",
        "protocol": "zmq",
        "schemes": ["tcp"],
        "default_port": 5555,
        "needs_gpu": True,
        "local_train": True,
        "local_serve": True,
        "hub_download": False,
        "note": "About 12 GB per checkpoint. It is never downloaded here; the serving container pulls it with its own token.",
    },
}

DEFAULT_SPEC = {
    "leader": "mock",
    "follower": "mock",
    "camera": "synthetic",
    "task_id": "pipeline_check",
}


class CellSpecError(ValueError):
    pass


OPTIONAL_KEYS = {
    "devices", "mock_motion", "settings", "images", "leader_model", "follower_model", "arms", "cameras",
}  # fmt: skip
DEVICE_ROLES = {"leader": "port", "follower": "port", "camera": "device", "side_camera": "device"}
CAMERA_ROLES = ("camera", "side_camera")
IMAGE_ROLES = {"leader", "follower", "camera", "side_camera"}
IMAGE_REFERENCE = cameras.IMAGE_REFERENCE  # one definition, shared with custom camera images


def validate_images(images):
    if not isinstance(images, dict) or set(images) - IMAGE_ROLES:
        raise CellSpecError("images may only contain leader, follower, camera and side_camera.")
    for role, image in images.items():
        if (
            not isinstance(image, str)
            or len(image) > 255
            or not IMAGE_REFERENCE.fullmatch(image)
            or image.startswith("localhost/")
        ):
            raise CellSpecError(
                f"images.{role} must be a Docker Hub image name, optionally with a tag or digest."
            )
    return dict(images)


def _options(value):
    return value if isinstance(value, list) else [value]


def _validate_devices(spec, chosen, hardware):
    """Check the optional ``devices`` block against the arms/camera that are real."""
    devices = spec.get("devices", {})
    if not isinstance(devices, dict) or set(devices) - set(DEVICE_ROLES):
        raise CellSpecError("devices may only describe leader, follower and camera.")
    needed = list(hardware) + (["camera"] if chosen["camera"] == "opencv_usb" else [])
    if chosen.get("side_camera") == "opencv_usb":
        needed.append("side_camera")
    clean = {}
    for role in devices:
        if role not in needed:
            raise CellSpecError(f"devices.{role} was given but that component is not real.")
    for role in needed:
        entry = devices.get(role)
        if entry is None:
            continue  # selecting devices can happen in a later step; start is gated on a test
        key = DEVICE_ROLES[role]
        pattern = VIDEO if role in CAMERA_ROLES else PORT
        allowed = {key, "serial", "card"} | (
            {"calibration"} if role not in CAMERA_ROLES else {"width", "height", "fps"}
        )
        if not isinstance(entry, dict) or set(entry) - allowed:
            raise CellSpecError(f"devices.{role} has unsupported fields.")
        path = entry.get(key)
        if not isinstance(path, str) or not pattern.fullmatch(path):
            raise CellSpecError(f"devices.{role}.{key} must be a serial or video device path under /dev.")
        calibration = entry.get("calibration")
        if calibration is not None and (
            not isinstance(calibration, str) or not CALIBRATION_FILE.fullmatch(calibration)
        ):
            raise CellSpecError(f"devices.{role}.calibration must be a plain .yaml file name.")
        for field in ("serial", "card"):
            if field in entry and (not isinstance(entry[field], str) or len(entry[field]) > 120):
                raise CellSpecError(f"devices.{role}.{field} must be a short string.")
        clean[role] = dict(entry)
    ports = [clean[r][DEVICE_ROLES[r]] for r in ("leader", "follower") if r in clean]
    if len(set(ports)) != len(ports):
        raise CellSpecError("Leader and follower must use different serial ports.")
    nodes = [clean[r]["device"] for r in CAMERA_ROLES if r in clean]
    if len(set(nodes)) != len(nodes):
        raise CellSpecError("The two cameras must use different video devices.")
    return clean


def validate_devices(devices, camera, hardware, side_camera=None):
    """Validate a ``devices`` block for a preset whose real arms are ``hardware``."""
    chosen = {"camera": camera, "side_camera": side_camera}
    return _validate_devices({"devices": devices}, chosen, hardware)


SETTINGS_DEFAULTS = {
    "camera": {"width": 640, "height": 480, "fps": 30},
    "side_camera": {"enabled": False, "source": "synthetic", "width": 640, "height": 480, "fps": 30},
    "recording": {
        "minimum_duration_seconds": 5.0,
        "preflight_min_free_gib": 10.0,
        "maximum_camera_gap_ms": 0,  # 0 = automatic: 2.25 frame periods, at least 75 ms
        "instruction": "",
    },
    "mock_motion": {"seed": 0, "speed": 1.0, "mode": "waypoints"},
    # Control arbiter and teleop source. Joint names come from the robot profile, not from here.
    "teleop": {
        "validity_ms": 80,
        "max_leader_age_ms": 200,
        "source_timeout_ms": 200,
        "max_handover_jump_rad": 0.15,
        "joint_mapping": {},  # follower joint -> {leader_joint, scale, leader/follower_reference_rad}
    },
}
_RANGES = {
    "width": (160, 1920), "height": (120, 1080), "fps": (5, 60),
    "minimum_duration_seconds": (1.0, 600.0), "preflight_min_free_gib": (0.5, 1000.0),
    "seed": (0, 2**31 - 1), "speed": (0.2, 3.0), "maximum_camera_gap_ms": (0, 1000),
    "validity_ms": (20, 100), "max_leader_age_ms": (20, 2000), "source_timeout_ms": (50, 5000),
    "max_handover_jump_rad": (0.01, 0.5),
}  # fmt: skip
_KINDS = {
    "width": int, "height": int, "fps": int, "seed": int,
    "minimum_duration_seconds": (int, float), "preflight_min_free_gib": (int, float), "speed": (int, float),
    "maximum_camera_gap_ms": (int, float),
    "validity_ms": int, "max_leader_age_ms": int, "source_timeout_ms": int, "max_handover_jump_rad": (int, float),
}  # fmt: skip


def _validate_joint_mapping(mapping):
    try:
        return components.validate_joint_mapping(mapping)
    except ComponentError as error:
        raise CellSpecError(str(error)) from None


def validate_settings(settings):
    """Normalise the optional ``settings`` block: unknown keys are errors, missing keys get defaults."""
    if settings is None:
        settings = {}
    if not isinstance(settings, dict) or set(settings) - set(SETTINGS_DEFAULTS):
        raise CellSpecError("settings may only contain: " + ", ".join(SETTINGS_DEFAULTS) + ".")
    clean = {}
    for group, defaults in SETTINGS_DEFAULTS.items():
        given = settings.get(group, {})
        if not isinstance(given, dict) or set(given) - set(defaults):
            raise CellSpecError(f"settings.{group} may only contain: {', '.join(defaults)}.")
        merged = {**defaults, **given}
        for key, value in merged.items():
            if key in _RANGES:
                low, high = _RANGES[key]
                kind = _KINDS[key]
                if isinstance(value, bool) or not isinstance(value, kind) or not low <= value <= high:
                    raise CellSpecError(f"settings.{group}.{key} must be a number from {low} to {high}.")
            if key == "maximum_camera_gap_ms" and 0 < merged[key] < 30:
                raise CellSpecError(
                    "settings.recording.maximum_camera_gap_ms must be 0 (automatic) or 30 to 1000."
                )
            if key in _RANGES:
                continue
            if key == "enabled" and not isinstance(value, bool):
                raise CellSpecError(f"settings.{group}.enabled must be true or false.")
            elif key == "source" and value not in ("synthetic", "opencv_usb"):
                raise CellSpecError("settings.side_camera.source must be synthetic or opencv_usb.")
            elif key == "mode" and value not in ("waypoints", "sine"):
                raise CellSpecError("settings.mock_motion.mode must be waypoints or sine.")
            elif key == "instruction" and (not isinstance(value, str) or len(value) > 200):
                raise CellSpecError("settings.recording.instruction must be text up to 200 characters.")
            elif key == "joint_mapping":
                merged[key] = _validate_joint_mapping(value)
        clean[group] = merged
    return clean


def _lists(spec):
    """Validate ``arms``/``cameras`` and fill in the single-pair keys they stand for."""
    try:
        lists = components.validate_lists(spec)
    except ComponentError as error:
        raise CellSpecError(str(error)) from None
    devices = spec.get("devices") if isinstance(spec.get("devices"), dict) else {}
    settings = spec.get("settings") if isinstance(spec.get("settings"), dict) else {}
    group = lambda name: settings.get(name) if isinstance(settings.get(name), dict) else {}  # noqa: E731
    if "arms" in lists:
        if {"leader", "follower"} & set(devices) or {"leader_model", "follower_model"} & set(spec):
            raise CellSpecError("With an arms list, each arm keeps its own model and device in its entry.")
        if group("teleop").get("joint_mapping"):
            raise CellSpecError("With an arms list, each follower keeps its own joint_mapping in its entry.")
    if "cameras" in lists:
        if {"camera", "side_camera"} & set(devices):
            raise CellSpecError("With a cameras list, each camera keeps its own device in its entry.")
        if group("side_camera").get("enabled"):
            raise CellSpecError("With a cameras list, add the side camera to the list instead.")
    derived = components.aggregates(lists)
    for key, value in derived.items():
        if key in spec and spec[key] != value:
            raise CellSpecError(f"{key} must be {value!r} for the listed components (or be left out).")
    return {**spec, **lists, **derived}


def validate_spec(spec):
    """Return the normalised spec and its preset id, or raise CellSpecError with a reason."""
    if not isinstance(spec, dict) or set(spec) - {"leader", "follower", "camera", "task_id"} - OPTIONAL_KEYS:
        raise CellSpecError(
            "Cell needs leader, follower, camera and task_id (optional: "
            + ", ".join(sorted(OPTIONAL_KEYS))
            + ")."
        )
    spec = _lists(spec)
    if not {"leader", "follower", "camera", "task_id"} <= set(spec):
        raise CellSpecError(
            "Cell needs leader, follower, camera and task_id (optional: "
            + ", ".join(sorted(OPTIONAL_KEYS))
            + ")."
        )
    for kind, component in COMPONENTS.items():
        choice = spec[kind]
        option = component["options"].get(choice) if isinstance(choice, str) else None
        if option is None:
            raise CellSpecError(f"Unknown {kind}: {choice!r}.")
        if option["status"] != AVAILABLE:
            raise CellSpecError(
                f"{component['label']} '{option['label']}' is planned and cannot be selected yet."
                + (f" {option['note']}" if option.get("note") else "")
            )
    if "mock_motion" in spec and not isinstance(spec["mock_motion"], bool):
        raise CellSpecError("mock_motion must be true or false.")
    if "arms" in spec:
        models = {role: {a["model"] for a in spec["arms"] if a["role"] == role} for role in arms.ROLES}
    else:
        try:
            models = {role: {model} for role, model in arms.validate_models(spec).items()}
        except ArmError as error:
            raise CellSpecError(str(error)) from None
    chosen = {kind: spec[kind] for kind in COMPONENTS}
    for preset_id, preset in PRESETS.items():
        if all(models[r] == {preset["models"][r]} for r in arms.ROLES) and all(
            chosen[kind] in _options(value) for kind, value in preset["match"].items()
        ):
            if spec["task_id"] not in preset["tasks"]:
                allowed = ", ".join(preset["tasks"])
                raise CellSpecError(
                    f"Task {spec['task_id']!r} is not available for this cell. Choose: {allowed}."
                )
            result = dict(spec)
            if "images" in spec:
                result["images"] = validate_images(spec["images"])
                if result["images"] and preset_id == "sim-so101":
                    raise CellSpecError("Custom images are not supported by the simulation preset.")
            settings = validate_settings(spec.get("settings"))
            side = settings["side_camera"]
            side_choice = side["source"] if side["enabled"] else None
            if "settings" in spec:
                result["settings"] = settings
            if "devices" in spec:
                result["devices"] = _validate_devices(
                    spec,
                    {
                        **chosen,
                        "camera": "synthetic" if "cameras" in spec else chosen["camera"],
                        "side_camera": None if "cameras" in spec else side_choice,
                    },
                    [] if "arms" in spec else preset["hardware"],
                )
            if "arms" in spec or "cameras" in spec:
                if "settings" not in spec:
                    result["settings"] = settings
            if spec.get("mock_motion") and (preset["hardware"] or chosen["leader"] != "mock"):
                raise CellSpecError("mock_motion drives the mock leader; it needs a mock leader.")
            return result, preset_id
    raise CellSpecError(explain_incompatibility(chosen))


def explain_incompatibility(chosen):
    if (chosen["follower"] == "gazebo") != (chosen["camera"] == "gazebo_scene"):
        return (
            "The rendered tabletop camera only exists inside the Gazebo follower scene, and a Gazebo "
            "follower needs it. Pair them, or use the mock follower with the synthetic camera."
        )
    if chosen["follower"] == "real" and chosen["leader"] != "real":
        return (
            "A real follower can only be driven by the real leader arm. Choose the real leader, or "
            "keep the follower mock while you test."
        )
    return "No supported deployment preset matches this combination of components."


def describe():
    return {
        "components": COMPONENTS,
        "tasks": TASKS,
        "presets": {k: {kk: vv for kk, vv in v.items()} for k, v in PRESETS.items()},
        "policies": POLICIES,
        "runtimes": RUNTIMES,
        "arms": arms.describe(),
        "cameras": cameras.describe(),
        "default": DEFAULT_SPEC,
    }
