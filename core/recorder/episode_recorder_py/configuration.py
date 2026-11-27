from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml


def _load_yaml(path: Path, schema: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"configuration file does not exist: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != schema:
        raise ValueError(f"{path} must use {schema}")
    return document


def _resolve(owner: Path, reference: str) -> Path:
    path = Path(reference).expanduser()
    return (owner.parent / path).resolve() if not path.is_absolute() else path.resolve()


def _hash_payload(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(re.fullmatch(r"sha256:[0-9a-fA-F]{64}", value))
        and value[7:] != "0" * 64
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def load_robot_config(path: Path) -> dict[str, Any]:
    robot = copy.deepcopy(_load_yaml(path, "robot-config/v1").get("robot"))
    if not isinstance(robot, dict):
        raise ValueError("robot-config/v1 requires a robot mapping")
    required = (
        "id",
        "robot_type",
        "target_id",
        "state",
        "action",
        "joints",
        "command_adapter",
    )
    if any(key not in robot for key in required):
        raise ValueError("robot configuration is incomplete")
    if robot["state"].get("type") != "sensor_msgs/msg/JointState":
        raise ValueError("robot state must use sensor_msgs/msg/JointState")
    if robot["action"].get("type") != "platform_control_interfaces/msg/JointIntent":
        raise ValueError(
            "robot action must use platform_control_interfaces/msg/JointIntent"
        )
    joints = robot["joints"]
    names = [joint.get("name") for joint in joints] if isinstance(joints, list) else []
    if not names or len(names) != len(set(names)) or any(not name for name in names):
        raise ValueError("robot joints must have unique non-empty names")
    for joint in joints:
        if joint.get("unit", "rad") != "rad" or float(joint["lower"]) >= float(
            joint["upper"]
        ):
            raise ValueError(
                f"invalid joint contract for {joint.get('name', '<unknown>')}"
            )
    groups = robot["command_adapter"].get("groups", [])
    commanded = [name for group in groups for name in group.get("joints", [])]
    if len(commanded) != len(set(commanded)) or set(commanded) != set(names):
        raise ValueError(
            "command adapter groups must partition the configured robot joints"
        )
    supported = {
        "joint_trajectory_topic",
        "gripper_action",
        "parallel_gripper_action",
    }
    if any(group.get("transport") not in supported for group in groups):
        raise ValueError("unsupported robot command transport")
    return robot


def load_camera_config(path: Path) -> dict[str, Any]:
    camera = copy.deepcopy(_load_yaml(path, "camera-config/v1").get("camera"))
    if not isinstance(camera, dict):
        raise ValueError("camera-config/v1 requires a camera mapping")
    required = ("name", "topic", "type", "width", "height", "format", "fps")
    if any(key not in camera for key in required):
        raise ValueError("camera configuration is incomplete")
    if (
        int(camera["width"]) <= 0
        or int(camera["height"]) <= 0
        or float(camera["fps"]) <= 0
    ):
        raise ValueError("camera dimensions and rate must be positive")
    if camera["type"] != "sensor_msgs/msg/CompressedImage" or camera[
        "format"
    ].lower() not in {"jpeg", "jpg"}:
        raise ValueError("camera must use JPEG sensor_msgs/msg/CompressedImage")
    return camera


def load_recording_profile(path: Path, profile_id: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    document = _load_yaml(path, "recording-profile/v2")
    try:
        selected = copy.deepcopy(document["profiles"][profile_id])
    except (KeyError, TypeError) as exc:
        raise ValueError(f"unknown recording profile: {profile_id}") from exc
    robot_path = _resolve(path, selected.pop("robot_config"))
    camera_paths = [_resolve(path, item) for item in selected.pop("camera_configs")]
    robot = load_robot_config(robot_path)
    cameras = [load_camera_config(camera_path) for camera_path in camera_paths]
    camera_names = [camera["name"] for camera in cameras]
    if not cameras or len(camera_names) != len(set(camera_names)):
        raise ValueError("recording profile cameras must have unique names")
    timeline = selected.get("timeline_camera", camera_names[0])
    if timeline not in camera_names:
        raise ValueError("timeline_camera must name a configured camera")
    # Use the slowest configured camera as the sampling clock; preserve the
    # configured choice when cameras have the same nominal rate.
    slowest_fps = min(float(camera["fps"]) for camera in cameras)
    if (
        float(next(camera for camera in cameras if camera["name"] == timeline)["fps"])
        > slowest_fps
    ):
        timeline = next(
            camera["name"] for camera in cameras if float(camera["fps"]) == slowest_fps
        )
    effective = {
        **selected,
        "id": profile_id,
        "robot_type": robot["robot_type"],
        "target_id": robot["target_id"],
        "joints": robot["joints"],
        "state": robot["state"],
        "action": robot["action"],
        "command_adapter": robot["command_adapter"],
        "cameras": cameras,
        "timeline_camera": timeline,
        "robot_config_path": str(robot_path),
        "camera_config_paths": [str(item) for item in camera_paths],
        "recording_profiles_path": str(path),
    }
    effective["contract_hash"] = _hash_payload(
        {
            "schema_version": "resolved-recording-profile/v1",
            "profile": selected,
            "profile_id": profile_id,
            "robot": robot,
            "cameras": cameras,
        }
    )
    return effective


def recording_profile_hash(path: Path, profile_id: str) -> str:
    return load_recording_profile(path, profile_id)["contract_hash"]


def load_workspace_config(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    document = _load_yaml(path, "workspace-config/v1")
    workspace = copy.deepcopy(document.get("workspace"))
    if not isinstance(workspace, dict):
        raise ValueError("workspace-config/v1 requires a workspace mapping")
    required = (
        "id",
        "dataset_dir",
        "recording_profiles",
        "recording_profile_id",
        "task_catalog",
        "task_id",
        "calibration",
    )
    if any(key not in workspace for key in required):
        raise ValueError("workspace configuration is incomplete")
    profiles_path = _resolve(path, workspace["recording_profiles"])
    task_path = _resolve(path, workspace["task_catalog"])
    profile = load_recording_profile(profiles_path, workspace["recording_profile_id"])
    tasks = _load_yaml(task_path, "task-catalog/v1")
    try:
        task = tasks["tasks"][workspace["task_id"]]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"unknown workspace task: {workspace['task_id']}") from exc
    if task.get("recording_profile_id") != workspace["recording_profile_id"]:
        raise ValueError("workspace task and recording profile do not match")
    calibration = workspace["calibration"]
    if not calibration.get("id") or not _is_sha256(calibration.get("hash")):
        raise ValueError("workspace calibration provenance is incomplete")
    workspace.update(
        {
            "workspace_config_path": str(path),
            "recording_profiles_path": str(profiles_path),
            "task_catalog_path": str(task_path),
            "profile": profile,
            "task": task,
        }
    )
    workspace["configuration_hash"] = _hash_payload(
        {
            "schema_version": "resolved-workspace/v1",
            "workspace": document["workspace"],
            "recording_profile_hash": profile["contract_hash"],
            "task_catalog_hash": sha256_file(task_path),
        }
    )
    return workspace
