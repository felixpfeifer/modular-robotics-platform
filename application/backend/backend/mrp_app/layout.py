"""Modular cell layout: a description of the physical workspace and its ROS interfaces.

The layout is *descriptive* project metadata (what is where, which topics each module
publishes). It never changes what the deployment agent runs; that remains the vetted
preset chosen through the cell catalog. Layouts are stored with the project and
copied into each recording session's snapshot, so an episode records the workspace it
was captured in.

Coordinates are metres in the workspace frame: origin at the front-left corner,
x to the right, y away from the operator, yaw in degrees counter-clockwise.
"""

import math
import re

from . import arms as arm_models
from . import cameras as camera_models

SCHEMA = "mrp-cell-layout/v1"
MAX_MODULES = 64
MAX_TOPICS = 32

ID_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
TOPIC_RE = re.compile(r"/?[A-Za-z0-9_]+(/[A-Za-z0-9_]+)*")
MSG_TYPE_RE = re.compile(r"[A-Za-z0-9_]+/(msg|srv|action)/[A-Za-z0-9_]+")
ROLE_RE = re.compile(r"[A-Za-z0-9_.:-]{0,60}")
FRAME_RE = re.compile(r"[A-Za-z0-9_]{1,40}")


class LayoutError(ValueError):
    pass


# Per-type defaults and the only property keys a module of that type may carry.
# prop spec: ("enum", [...]) | ("int", lo, hi) | ("float", lo, hi) | ("text", max) | ("bool",)
MODULE_TYPES = {
    "arm": {
        "label": "Robot arm",
        "color": "#245c56",
        "size": [0.14, 0.14],
        "properties": {
            # The arm's type (an arm catalogue id) and variant; "other" is descriptive only.
            "model": ("enum", [*arm_models.ARMS, "other"]),
            "variant": ("text", 40),
            "role": ("enum", ["follower", "leader", "standalone"]),
            "dof": ("int", 1, 20),
            "reach_m": ("float", 0.05, 3.0),
            "gripper": ("bool",),
        },
        "defaults": {"model": "so101", "role": "follower", "dof": 6, "reach_m": 0.4, "gripper": True},
    },
    "camera": {
        "label": "Camera",
        "color": "#3a6ea5",
        "size": [0.07, 0.07],
        "properties": {
            # The camera's type (a camera catalogue id) and variant; "other" is descriptive only.
            # A callable: custom and discovered camera models join the choices at runtime.
            "model": ("enum", lambda: [*camera_models.models(), "other"]),
            "variant": ("text", 40),
            "kind": ("enum", ["rgb", "depth", "stereo", "thermal"]),
            "mount": ("enum", ["fixed", "wrist", "mobile"]),
            "fov_deg": ("float", 1, 180),
            "resolution": ("text", 20),
            "fps": ("int", 1, 1000),
        },
        "defaults": {
            "model": "opencv_usb",
            "kind": "rgb",
            "mount": "fixed",
            "fov_deg": 70,
            "resolution": "640x480",
            "fps": 30,
        },  # fmt: skip
    },
    "sensor": {
        "label": "Sensor",
        "color": "#8a5fb0",
        "size": [0.06, 0.06],
        "properties": {
            "kind": ("enum", ["force_torque", "imu", "tactile", "lidar", "encoder", "other"]),
            "model": ("text", 60),
            "rate_hz": ("float", 0.01, 100000),
        },
        "defaults": {"kind": "force_torque"},
    },
    "input": {
        "label": "Operator input",
        "color": "#c8754e",
        "size": [0.12, 0.08],
        "properties": {
            "kind": ("enum", ["leader_arm", "spacemouse", "vr_controller", "gamepad", "keyboard", "other"]),
            "model": ("text", 60),
        },
        "defaults": {"kind": "spacemouse"},
    },
    "fixture": {
        "label": "Table / fixture",
        "color": "#9aa6a1",
        "size": [0.6, 0.4],
        "properties": {"material": ("text", 40)},
        "defaults": {},
    },
    "zone": {
        "label": "Target / work zone",
        "color": "#4f9d69",
        "size": [0.15, 0.1],
        "properties": {"purpose": ("enum", ["target", "pick", "keep_out", "other"])},
        "defaults": {"purpose": "target"},
    },
    "object": {
        "label": "Task object",
        "color": "#c94f4f",
        "size": [0.04, 0.04],
        "properties": {"shape": ("enum", ["cube", "cylinder", "sphere", "irregular"]), "color": ("text", 30)},
        "defaults": {"shape": "cube", "color": "red"},
    },
}

# Default vertical extent (m) per type; the top of a module is z + height.
DEFAULT_HEIGHT = {
    "arm": 0.25, "camera": 0.05, "sensor": 0.03, "input": 0.05,
    "fixture": 0.75, "zone": 0.005, "object": 0.04,
}  # fmt: skip

LIMITS = {"coordinate": 100.0, "height": 10.0, "dimension": (0.005, 50.0)}


def _number(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise LayoutError(f"{label} must be a number.")
    if not low <= value <= high:
        raise LayoutError(f"{label} must be between {low} and {high}.")
    return float(value)


def _text(value, label, maximum, minimum=0):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise LayoutError(f"{label} must contain {minimum}–{maximum} characters.")
    if any(ord(c) < 32 for c in value):
        raise LayoutError(f"{label} must not contain control characters.")
    return value.strip()


def _options(rule):
    """An enum's choices; a callable gives choices that change at runtime (camera models)."""
    return list(rule[1]()) if callable(rule[1]) else rule[1]


def _property(module_type, key, value, spec):
    label = f"{module_type} property '{key}'"
    kind = spec[0]
    if kind == "enum":
        options = _options(spec)
        if value not in options:
            raise LayoutError(f"{label} must be one of: {', '.join(options)}.")
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int) or not spec[1] <= value <= spec[2]:
            raise LayoutError(f"{label} must be an integer from {spec[1]} to {spec[2]}.")
        return value
    if kind == "float":
        return _number(value, label, spec[1], spec[2])
    if kind == "bool":
        if not isinstance(value, bool):
            raise LayoutError(f"{label} must be true or false.")
        return value
    return _text(value, label, spec[1])


def _topics(topics, name):
    if not isinstance(topics, list) or len(topics) > MAX_TOPICS:
        raise LayoutError(f"Module '{name}': topics must be a list of at most {MAX_TOPICS}.")
    clean, seen = [], set()
    for topic in topics:
        if not isinstance(topic, dict) or set(topic) - {"name", "type", "role"}:
            raise LayoutError(f"Module '{name}': each topic has only name, type and role.")
        topic_name = topic.get("name")
        if not isinstance(topic_name, str) or not TOPIC_RE.fullmatch(topic_name):
            raise LayoutError(f"Module '{name}': '{topic_name}' is not a valid ROS topic name.")
        topic_name = "/" + topic_name.lstrip("/")
        if topic_name in seen:
            raise LayoutError(f"Module '{name}': topic {topic_name} is listed twice.")
        seen.add(topic_name)
        msg_type = topic.get("type", "")
        if msg_type and (not isinstance(msg_type, str) or not MSG_TYPE_RE.fullmatch(msg_type)):
            raise LayoutError(f"Module '{name}': '{msg_type}' is not a ROS type like sensor_msgs/msg/Image.")
        role = topic.get("role", "")
        if not isinstance(role, str) or not ROLE_RE.fullmatch(role):
            raise LayoutError(f"Module '{name}': topic role may use letters, digits and . _ : - only.")
        clean.append({"name": topic_name, "type": msg_type, "role": role})
    return clean


def _module(raw, index):
    if not isinstance(raw, dict):
        raise LayoutError(f"Module {index + 1} must be an object.")
    allowed = {
        "id", "type", "name", "x", "y", "z", "yaw_deg", "width", "depth", "height", "parent",
        "enabled", "notes", "namespace", "properties", "topics",
    }  # fmt: skip
    if set(raw) - allowed:
        raise LayoutError(f"Module {index + 1} has unknown fields: {', '.join(sorted(set(raw) - allowed))}.")
    module_type = raw.get("type")
    if module_type not in MODULE_TYPES:
        raise LayoutError(f"Module {index + 1}: unknown type {module_type!r}.")
    spec = MODULE_TYPES[module_type]
    ident = raw.get("id")
    if not isinstance(ident, str) or not ID_RE.fullmatch(ident):
        raise LayoutError(f"Module {index + 1}: id must be 1–40 letters, digits, '_' or '-'.")
    name = _text(raw.get("name"), f"Module {index + 1} name", 60, 1)
    limit = LIMITS["coordinate"]
    low, high = LIMITS["dimension"]
    properties = dict(raw.get("properties", {})) if isinstance(raw.get("properties", {}), dict) else None
    if properties is None:
        raise LayoutError(f"Module '{name}': properties must be an object.")
    legacy_height = properties.pop("height_m", None) if module_type == "fixture" else None
    parent = raw.get("parent") or ""
    if parent and (not isinstance(parent, str) or not ID_RE.fullmatch(parent)):
        raise LayoutError(f"Module '{name}': parent must be the id of another module.")
    if (
        module_type == "arm"
        and "model" in properties
        and properties["model"] not in spec["properties"]["model"][1]
    ):
        # Layouts saved before the model became a choice hold free text such as "SO-101".
        properties["model"] = arm_models.match_model(properties["model"]) or "other"
    clean_props = {}
    for key, value in properties.items():
        if key not in spec["properties"]:
            raise LayoutError(f"Module '{name}': {module_type} has no property '{key}'.")
        clean_props[key] = _property(module_type, key, value, spec["properties"][key])
    _check_variant(module_type, clean_props, name)
    namespace = raw.get("namespace", "")
    if namespace and (not isinstance(namespace, str) or not TOPIC_RE.fullmatch(namespace)):
        raise LayoutError(f"Module '{name}': namespace is not a valid ROS namespace.")
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise LayoutError(f"Module '{name}': enabled must be true or false.")
    return {
        "id": ident,
        "type": module_type,
        "name": name,
        "x": round(_number(raw.get("x", 0), f"Module '{name}' x", -limit, limit), 4),
        "y": round(_number(raw.get("y", 0), f"Module '{name}' y", -limit, limit), 4),
        "z": round(_number(raw.get("z", 0), f"Module '{name}' z", -limit, LIMITS["height"]), 4),
        "yaw_deg": round(_number(raw.get("yaw_deg", 0), f"Module '{name}' yaw", -360, 360), 2),
        "width": round(_number(raw.get("width", spec["size"][0]), f"Module '{name}' width", low, high), 4),
        "depth": round(_number(raw.get("depth", spec["size"][1]), f"Module '{name}' depth", low, high), 4),
        "height": round(
            _number(
                raw.get(
                    "height", legacy_height if legacy_height is not None else DEFAULT_HEIGHT[module_type]
                ),
                f"Module '{name}' height",
                0,
                LIMITS["height"],
            ),
            4,
        ),
        "parent": parent,
        "enabled": enabled,
        "notes": _text(raw.get("notes", ""), f"Module '{name}' notes", 280),
        "namespace": ("/" + namespace.lstrip("/")) if namespace else "",
        "properties": clean_props,
        "topics": _topics(raw.get("topics", []), name),
    }


def _variants(module_type, model):
    catalog = {"arm": arm_models.ARMS, "camera": camera_models.models()}.get(module_type, {})
    return catalog.get(model, {}).get("variants", {})


def _check_variant(module_type, props, name):
    variant = props.get("variant")
    if not variant:
        props.pop("variant", None)
        return
    if variant not in _variants(module_type, props.get("model")):
        choices = ", ".join(_variants(module_type, props.get("model"))) or "none"
        raise LayoutError(
            f"Module '{name}': variant '{variant}' does not belong to this model (variants: {choices})."
        )


def validate_layout(layout):
    """Return the normalised layout or raise LayoutError describing the first problem."""
    if not isinstance(layout, dict) or set(layout) - {"schema_version", "workspace", "modules"}:
        raise LayoutError("Layout has only: schema_version, workspace and modules.")
    if layout.get("schema_version", SCHEMA) != SCHEMA:
        raise LayoutError(f"Unsupported layout schema; expected {SCHEMA}.")
    workspace = layout.get("workspace")
    if not isinstance(workspace, dict) or set(workspace) - {"name", "width_m", "depth_m", "frame_id"}:
        raise LayoutError("Workspace has only: name, width_m, depth_m and frame_id.")
    frame = workspace.get("frame_id", "world")
    if not isinstance(frame, str) or not FRAME_RE.fullmatch(frame):
        raise LayoutError("Workspace frame_id may use letters, digits and underscores (max 40).")
    modules = layout.get("modules", [])
    if not isinstance(modules, list) or len(modules) > MAX_MODULES:
        raise LayoutError(f"A layout holds at most {MAX_MODULES} modules.")
    clean, ids, names = [], set(), set()
    for index, raw in enumerate(modules):
        module = _module(raw, index)
        if module["id"] in ids:
            raise LayoutError(f"Module id '{module['id']}' is used twice.")
        if module["name"].lower() in names:
            raise LayoutError(f"Module name '{module['name']}' is used twice; names identify modules.")
        ids.add(module["id"])
        names.add(module["name"].lower())
        clean.append(module)
    _check_parents(clean)
    return {
        "schema_version": SCHEMA,
        "workspace": {
            "name": _text(workspace.get("name", "Workspace"), "Workspace name", 60, 1),
            "width_m": round(_number(workspace.get("width_m"), "Workspace width", 0.2, 20), 3),
            "depth_m": round(_number(workspace.get("depth_m"), "Workspace depth", 0.2, 20), 3),
            "frame_id": frame,
        },
        "modules": clean,
    }


def _check_parents(modules):
    """'parent' means 'placed on top of': it must exist and the chain must not loop."""
    parents = {m["id"]: m["parent"] for m in modules}
    for module in modules:
        parent = module["parent"]
        if parent and parent not in parents:
            raise LayoutError(f"Module '{module['name']}' is placed on '{parent}', which does not exist.")
        seen, current = {module["id"]}, parent
        while current:
            if current in seen:
                raise LayoutError(f"Module '{module['name']}' is part of a circular 'placed on' chain.")
            seen.add(current)
            current = parents[current]


def _mod(ident, module_type, name, x, y, **extra):
    spec = MODULE_TYPES[module_type]
    module = {
        "id": ident,
        "type": module_type,
        "name": name,
        "x": x,
        "y": y,
        "properties": dict(spec["defaults"]),
    }
    module.update(extra)
    return module


def _template(label, description, width, depth, modules):
    layout = validate_layout(
        {
            "schema_version": SCHEMA,
            "workspace": {"name": label, "width_m": width, "depth_m": depth},
            "modules": modules,
        }
    )
    return {"label": label, "description": description, "layout": layout}


_IMG = "sensor_msgs/msg/CompressedImage"
_JOINTS = "sensor_msgs/msg/JointState"

TEMPLATES = {
    "empty": _template("Empty workspace", "Start from a blank 1.2 × 0.8 m table.", 1.2, 0.8, []),
    "so101_tabletop": _template(
        "SO-101 tabletop",
        "Leader and follower SO-101 with a top camera, a cube and a target zone.",
        1.2,
        0.8,
        [
            _mod("table", "fixture", "Table", 0.6, 0.4, width=1.2, depth=0.8),
            _mod(
                "follower",
                "arm",
                "Follower arm",
                0.6,
                0.12,
                z=0.75,
                parent="table",
                yaw_deg=90,
                namespace="/follower",
                topics=[{"name": "/follower/joint_states", "type": _JOINTS, "role": "observation.state"}],
            ),
            _mod(
                "leader",
                "arm",
                "Leader arm",
                0.2,
                0.12,
                z=0.75,
                parent="table",
                yaw_deg=90,
                namespace="/leader",
                properties={**MODULE_TYPES["arm"]["defaults"], "role": "leader", "gripper": False},
                topics=[{"name": "/leader/joint_states", "type": _JOINTS, "role": "action"}],
            ),
            _mod(
                "top_camera",
                "camera",
                "Top camera",
                0.6,
                0.45,
                z=1.35,
                yaw_deg=-90,
                topics=[
                    {"name": "/top_camera/image/compressed", "type": _IMG, "role": "observation.images.top"}
                ],
            ),
            _mod("cube", "object", "Red cube", 0.45, 0.42, z=0.75, parent="table"),
            _mod("target", "zone", "Green rectangle", 0.8, 0.42, z=0.75, parent="table"),
        ],
    ),  # fmt: skip
    "mock_so101": _template(
        "Mock SO-101 + webcam",
        "The synthetic pipeline-check cell: mock arms and a synthetic webcam.",
        1.0,
        0.6,
        [
            _mod("table", "fixture", "Table", 0.5, 0.3, width=1.0, depth=0.6),
            _mod(
                "follower",
                "arm",
                "Follower arm",
                0.5,
                0.1,
                z=0.75,
                parent="table",
                yaw_deg=90,
                namespace="/follower",
            ),
            _mod(
                "webcam",
                "camera",
                "Webcam",
                0.5,
                0.45,
                z=1.0,
                yaw_deg=-90,
                topics=[
                    {"name": "/webcam/image/compressed", "type": _IMG, "role": "observation.images.webcam"}
                ],
            ),
        ],
    ),  # fmt: skip
    "dual_arm": _template(
        "Dual-arm bench",
        "Two follower arms facing a shared work zone with two cameras.",
        1.6,
        0.9,
        [
            _mod("table", "fixture", "Table", 0.8, 0.45, width=1.6, depth=0.9),
            _mod(
                "arm_left", "arm", "Left arm", 0.4, 0.1, z=0.75, parent="table", yaw_deg=90, namespace="/left"
            ),
            _mod(
                "arm_right",
                "arm",
                "Right arm",
                1.2,
                0.1,
                z=0.75,
                parent="table",
                yaw_deg=90,
                namespace="/right",
            ),
            _mod("cam_top", "camera", "Top camera", 0.8, 0.6, z=1.45, yaw_deg=-90),
            _mod("cam_front", "camera", "Front camera", 0.8, 0.85, z=1.05, yaw_deg=-90),
            _mod(
                "work_zone",
                "zone",
                "Shared work zone",
                0.8,
                0.4,
                width=0.4,
                depth=0.25,
                z=0.75,
                parent="table",
                properties={"purpose": "pick"},
            ),
        ],
    ),  # fmt: skip
}

PRESET_TEMPLATE = {
    "mock-so101": "mock_so101",
    "hwleader-so101": "mock_so101",
    "real-so101": "mock_so101",
    "sim-so101": "so101_tabletop",
}


def default_layout(preset):
    return TEMPLATES[PRESET_TEMPLATE.get(preset, "empty")]["layout"]


def describe():
    return {
        "schema_version": SCHEMA,
        "max_modules": MAX_MODULES,
        "module_types": {
            key: {
                "label": spec["label"],
                "color": spec["color"],
                "size": spec["size"],
                "height": DEFAULT_HEIGHT[key],
                "defaults": spec["defaults"],
                "properties": {
                    name: {"kind": rule[0], **_rule_bounds(rule)} for name, rule in spec["properties"].items()
                },
                **_model_choices(key),
            }
            for key, spec in MODULE_TYPES.items()
        },
        "templates": TEMPLATES,
    }


def _model_choices(module_type):
    """Labels and variants of the ``model`` choices, so the UI can show names and offer variants."""
    catalog = {"arm": arm_models.ARMS, "camera": camera_models.models()}.get(module_type)
    if catalog is None:
        return {}
    models = {
        ident: {"label": entry["label"], "status": entry["status"], "variants": entry["variants"]}
        for ident, entry in catalog.items()
    }
    if module_type == "camera":  # built-in, discovered (labelled local image) or custom (added in the UI)
        for ident, entry in catalog.items():
            models[ident]["origin"] = entry.get("origin", "builtin")
    models["other"] = {"label": "Other (not deployable)", "status": "planned", "variants": {}}
    return {"models": models}


def _rule_bounds(rule):
    if rule[0] == "enum":
        return {"options": _options(rule)}
    if rule[0] in ("int", "float"):
        return {"min": rule[1], "max": rule[2]}
    if rule[0] == "text":
        return {"max_length": rule[1]}
    return {}
