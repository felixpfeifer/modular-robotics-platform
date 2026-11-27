"""Leader and follower arm models: the interface a robot driver must satisfy.

A cell picks two independent things per arm role:

* the **backend** (``leader``/``follower`` in the cell spec): ``mock``, ``gazebo`` or ``real``;
* the **model** (``leader_model``/``follower_model``): which device that is, e.g. SO-101 or a UR arm,
  and optionally its **variant** (e.g. UR5e), chosen on the arm module of the workspace layout.

This module is the model side. It describes each supported or planned device by what it
exposes (roles, connection, command interfaces, kinematics, safety prerequisites), and derives
how a leader drives a follower from those capabilities alone, mirroring
``platform_control_interfaces/BindingDescriptor`` (source -> mapper -> solver -> target).

Nothing here starts a container. A model marked ``planned`` is listed in the catalog and the UI
but is rejected by validation until its driver image, robot profile and deployment preset exist
(see docs/architecture/0002-arm-interface.md for the checklist).
"""

import re

AVAILABLE, PLANNED = "available", "planned"
INTERFACE_VERSION = "mrp-arm-interface/v1"
DEFAULT_MODEL = "so101"
ROLES = ("leader", "follower")

# What a leader publishes. Both are read by the teleop source, never by the follower directly.
LEADER_OUTPUTS = {
    "joint_state": {
        "label": "Joint positions",
        "ros_type": "sensor_msgs/msg/JointState",
        "topic": "robot profile topics.leader_joint_states",
    },
    "cartesian_pose": {
        "label": "End-effector pose + gripper",
        "ros_type": "geometry_msgs/msg/PoseStamped",
        "topic": "/leader/pose",
        "note": "Gripper on /leader/gripper (std_msgs/msg/Float64, 0 open .. 1 closed); "
        "the deadman state on /leader/enable (std_msgs/msg/Bool).",
    },
}

# What a follower accepts. Only the control arbiter publishes these (one owner per target).
COMMAND_INTERFACES = {
    "joint": {
        "label": "Joint position intent",
        "ros_type": "platform_control_interfaces/msg/JointIntent",
        "topic": "/platform/control/joint_intent",
        "status": AVAILABLE,
    },
    "cartesian": {
        "label": "Cartesian pose intent",
        "ros_type": "platform_control_interfaces/msg/CartesianIntent",
        "topic": "/platform/control/cartesian_intent",
        "status": PLANNED,
    },
}

# How the device is reached. The fields are what ``devices.<role>`` will hold for that connection.
CONNECTIONS = {
    "usb_serial": {
        "label": "USB serial",
        "status": AVAILABLE,
        "fields": {
            "port": "/dev/ttyACM* or /dev/serial/by-id/*",
            "serial": "adapter serial",
            "calibration": "*.yaml",
        },
    },
    "ethernet": {
        "label": "Ethernet to the robot controller",
        "status": PLANNED,
        "fields": {"host": "controller IPv4 address", "port": "TCP port (driver default if empty)"},
        "note": "Needs host networking or a routed cell network; never exposed beyond the cell host.",
    },
    "wifi_xr": {
        "label": "Wi-Fi from a VR headset",
        "status": PLANNED,
        "fields": {"host": "headset IPv4 address", "pairing": "one-time pairing code"},
        "note": "The headset streams poses to a bridge in the cell; it never talks to the follower.",
    },
}

# Mapper: leader output -> target space. Solver: target space -> follower command interface.
MAPPERS = {
    "joint_mapping": {"label": "Joint mapping (settings.teleop.joint_mapping)", "status": AVAILABLE},
    "pose_retarget": {"label": "Pose retargeting (frame, scale, workspace clamp)", "status": PLANNED},
}
SOLVERS = {
    "none": {"label": "Direct", "status": AVAILABLE},
    "ik": {"label": "Inverse kinematics from the robot description", "status": PLANNED},
}

SAFETY = {
    "operator_confirmation": "An operator confirms before motors are enabled.",
    "handover_gate": "The arbiter forwards nothing until leader and follower poses agree.",
    "deadman": "Motion only while the operator holds an enable button.",
    "protective_stop": "The driver reports the controller's protective/emergency stop state.",
    "speed_scaling": "Commands respect the controller's speed scaling and joint limits.",
    "workspace_limits": "Cartesian targets are clamped to a configured workspace box.",
}

ARMS = {
    "so101": {
        "label": "SO-101",
        "variants": {},
        "vendor": "The Robot Studio / Hugging Face",
        "status": AVAILABLE,
        "roles": ["leader", "follower"],
        "connection": "usb_serial",
        "backends": {"leader": ["mock", "real"], "follower": ["mock", "gazebo", "real"]},
        "kinematics": "so101",
        "dof": 5,
        "gripper": True,
        "leader_output": "joint_state",
        "command_interfaces": ["joint"],
        "robot_profile": "so101",
        "safety": ["operator_confirmation", "handover_gate"],
    },
    "meta_quest": {
        "label": "Meta Quest 3 (hand controllers)",
        "variants": {},
        "vendor": "Meta",
        "status": PLANNED,
        "roles": ["leader"],
        "connection": "wifi_xr",
        "backends": {"leader": ["mock", "real"]},
        "kinematics": None,
        "dof": None,
        "gripper": True,
        "leader_output": "cartesian_pose",
        "command_interfaces": [],
        "robot_profile": None,
        "safety": ["deadman", "workspace_limits"],
        "note": "Needs a headset bridge that publishes controller poses, the grip button as deadman "
        "and the trigger as gripper; followers then need pose retargeting.",
    },
    "ur": {
        "label": "Universal Robots (CB3 / e-Series)",
        "variants": {
            "ur3": "UR3",
            "ur5": "UR5",
            "ur10": "UR10",
            "ur3e": "UR3e",
            "ur5e": "UR5e",
            "ur10e": "UR10e",
            "ur16e": "UR16e",
        },
        "vendor": "Universal Robots",
        "status": PLANNED,
        "roles": ["follower"],
        "connection": "ethernet",
        "backends": {"follower": ["mock", "gazebo", "real"]},
        "kinematics": "ur",
        "dof": 6,
        "gripper": False,
        "leader_output": None,
        "command_interfaces": ["joint", "cartesian"],
        "robot_profile": None,
        "safety": ["operator_confirmation", "handover_gate", "protective_stop", "speed_scaling"],
        "note": "Needs a driver image wrapping the UR ROS 2 driver and the External Control program "
        "on the controller. Gripper is an optional tool-flange add-on.",
    },
    "fanuc": {
        "label": "FANUC industrial arm",
        "variants": {},
        "vendor": "FANUC",
        "status": PLANNED,
        "roles": ["follower"],
        "connection": "ethernet",
        "backends": {"follower": ["mock", "real"]},
        "kinematics": "fanuc",
        "dof": 6,
        "gripper": False,
        "leader_output": None,
        "command_interfaces": ["joint"],
        "robot_profile": None,
        "safety": ["operator_confirmation", "handover_gate", "protective_stop", "speed_scaling"],
        "note": "Needs a driver image for the controller's external motion interface; the matching "
        "controller software option must be licensed. Model-specific profiles per arm.",
    },
    "trossen_x_series": {
        "label": "Trossen Interbotix X-Series (WidowX / ViperX)",
        "variants": {"wx250s": "WidowX 250 6DOF", "vx300s": "ViperX 300 6DOF"},
        "vendor": "Trossen Robotics",
        "status": PLANNED,
        "roles": ["leader", "follower"],
        "connection": "usb_serial",
        "backends": {"leader": ["mock", "real"], "follower": ["mock", "gazebo", "real"]},
        "kinematics": "trossen_x_series",
        "dof": 6,
        "gripper": True,
        "leader_output": "joint_state",
        "command_interfaces": ["joint"],
        "robot_profile": None,
        "safety": ["operator_confirmation", "handover_gate"],
        "note": "Dynamixel bus over a USB adapter. A WidowX leader can drive a same-model follower "
        "with the joint mapping, like SO-101.",
    },
    "trossen_ai": {
        "label": "Trossen AI arms (WidowX AI)",
        "variants": {},
        "vendor": "Trossen Robotics",
        "status": PLANNED,
        "roles": ["leader", "follower"],
        "connection": "ethernet",
        "backends": {"leader": ["mock", "real"], "follower": ["mock", "real"]},
        "kinematics": "trossen_ai",
        "dof": 6,
        "gripper": True,
        "leader_output": "joint_state",
        "command_interfaces": ["joint"],
        "robot_profile": None,
        "safety": ["operator_confirmation", "handover_gate", "protective_stop"],
        "note": "Ethernet-connected controller; leader and follower variants of the same model.",
    },
}


class ArmError(ValueError):
    pass


def models_of(spec):
    """The ``{role: model id}`` a cell spec selects; older specs without models mean SO-101."""
    return {role: spec.get(f"{role}_model", DEFAULT_MODEL) for role in ROLES}


def _arm(role, model_id):
    arm = ARMS.get(model_id) if isinstance(model_id, str) else None
    if arm is None:
        raise ArmError(f"Unknown {role}_model: {model_id!r}.")
    if role not in arm["roles"]:
        raise ArmError(f"{arm['label']} cannot be used as the {role}.")
    if arm["status"] != AVAILABLE:
        raise ArmError(
            f"{role.capitalize()} '{arm['label']}' is planned and cannot be selected yet."
            + (f" {arm['note']}" if arm.get("note") else "")
        )
    return arm


def binding(leader_id, follower_id):
    """How ``leader_id`` drives ``follower_id``, from capabilities only (no status checks).

    Returns ``{mapper, solver, command, status, reason}``; ``status`` is ``planned`` when a step
    in the chain is not implemented yet and ``unsupported`` when no chain exists.
    """
    leader, follower = ARMS[leader_id], ARMS[follower_id]
    output, accepts = leader["leader_output"], follower["command_interfaces"]
    if output == "joint_state":
        if leader["kinematics"] != follower["kinematics"] or "joint" not in accepts:
            return {
                "mapper": None, "solver": None, "command": None, "status": "unsupported",
                "reason": f"A {leader['label']} leader sends joint positions, which only map onto an "
                f"arm with the same kinematics. Use a pose leader for the {follower['label']}.",
            }  # fmt: skip
        chain = ("joint_mapping", "none", "joint")
    elif output == "cartesian_pose":
        chain = (
            ("pose_retarget", "none", "cartesian")
            if "cartesian" in accepts
            else ("pose_retarget", "ik", "joint")
        )
    else:
        raise ArmError(f"{leader['label']} has no leader output.")
    mapper, solver, command = chain
    planned = [
        label
        for label, entry in (
            (MAPPERS[mapper]["label"], MAPPERS[mapper]),
            (SOLVERS[solver]["label"], SOLVERS[solver]),
            (COMMAND_INTERFACES[command]["label"], COMMAND_INTERFACES[command]),
        )
        if entry["status"] != AVAILABLE
    ]
    return {
        "mapper": mapper,
        "solver": solver,
        "command": command,
        "status": PLANNED if planned else AVAILABLE,
        "reason": f"Not implemented yet: {', '.join(planned)}." if planned else "",
    }


def check_variant(model_id, variant):
    """``variant`` is empty or one of the model's variants."""
    arm = ARMS.get(model_id) if isinstance(model_id, str) else None
    if arm is None:
        raise ArmError(f"Unknown model: {model_id!r}.")
    if variant not in (None, "") and variant not in arm["variants"]:
        choices = ", ".join(arm["variants"]) or "none"
        raise ArmError(f"{arm['label']} has no variant {variant!r} (variants: {choices}).")
    return variant or None


def match_model(text):
    """The model id a layout's free-text model stands for (``"SO-101"`` -> ``"so101"``), or None."""
    key = re.sub(r"[^a-z0-9]", "", str(text).lower())
    for model_id, arm in ARMS.items():
        if key in (re.sub(r"[^a-z0-9]", "", model_id), re.sub(r"[^a-z0-9]", "", arm["label"].lower())):
            return model_id
    return None


def check_arm(role, model_id, backend):
    """One arm: the model exists, is available, fits the role and has this backend."""
    arm = _arm(role, model_id)
    if backend not in arm["backends"].get(role, []):
        raise ArmError(f"{arm['label']} has no '{backend}' {role} backend.")
    if backend == "real" and CONNECTIONS[arm["connection"]]["status"] != AVAILABLE:
        raise ArmError(f"{CONNECTIONS[arm['connection']]['label']} connections are not supported yet.")
    return arm


def check_pair(leader_id, follower_id):
    """The leader can drive the follower with what is implemented today."""
    chain = binding(leader_id, follower_id)
    if chain["status"] != AVAILABLE:
        raise ArmError(chain["reason"])
    return chain


def validate_models(spec):
    """Check the selected models against the roles, backends and pairing rules; return them."""
    models = models_of(spec)
    for role in ROLES:
        check_arm(role, models[role], spec[role])
    check_pair(models["leader"], models["follower"])
    return models


def describe():
    """Catalog view, including the derived binding for every leader/follower pair."""
    leaders = [k for k, v in ARMS.items() if "leader" in v["roles"]]
    followers = [k for k, v in ARMS.items() if "follower" in v["roles"]]
    return {
        "interface_version": INTERFACE_VERSION,
        "default": DEFAULT_MODEL,
        "models": ARMS,
        "leader_outputs": LEADER_OUTPUTS,
        "command_interfaces": COMMAND_INTERFACES,
        "connections": CONNECTIONS,
        "mappers": MAPPERS,
        "solvers": SOLVERS,
        "safety": SAFETY,
        "bindings": {f"{lead}->{follow}": binding(lead, follow) for lead in leaders for follow in followers},
    }
