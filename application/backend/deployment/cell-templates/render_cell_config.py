#!/usr/bin/env python3
"""Render the recorder/arbiter configuration for one cell start from the project's settings.

Runs inside the robot image with no network (see deployment/devices.py:render_cell_config), reads
the JSON parameters from argv and writes plain YAML into the shared workspace volume that the
recorder, command bridge, exporter and the application read. Standard library only.

    render_cell_config.py OUT_DIR PARAMS_JSON [CALIBRATION_DIR FILE...] [--robots DIR]

Prints the calibration hash that becomes the recordings' provenance. Invalid input exits non-zero.

A cell with more than one leader or follower (``params["arms"]``) is presented to the arbiter and the
recorder as one combined robot: joints are prefixed with the arm id, ``arms.json`` tells the arm
adapter how to merge states and split intents, and every follower gets its own bridge robot config
under ``robots/``. Those are derived from the recorder's robot configs in ``--robots DIR``, read with
PyYAML when it is installed (it is in the robot image) and otherwise with a strict reader for that
format. Generated robot configs are written as JSON, which YAML readers accept.
"""

import hashlib
import json
import math
import re
import sys
from pathlib import Path

MOCK_CALIBRATION = {
    "id": "mock-so101-identity-v1",
    "hash": "sha256:49ad1203d777fb1c0ed6386d8590bda28e202ceef39bc8b754ca00e218fd209a",
}
OPTIONAL_TOPICS = ("/platform/control/safety_events", "/platform/control/command_rejections")
DEFAULT_INSTRUCTIONS = {
    "pipeline_check": "Exercise mock leader/follower tracking and camera recording. No physical task is performed.",
}
FREE_INSTRUCTION = "Free teleoperation. Record the demonstration the operator performs."

ID = re.compile(r"[a-z][a-z0-9_]{0,39}")
TOPIC = re.compile(r"/[A-Za-z0-9_]+(/[A-Za-z0-9_]+)*")
JOINT = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")
FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,60}\.ya?ml")
ROBOT_ID = re.compile(r"[a-z][a-z0-9_]{0,30}")
TELEOP_DEFAULTS = {
    "validity_ms": 80,
    "max_leader_age_ms": 200,
    "source_timeout_ms": 200,
    "max_handover_jump_rad": 0.15,
}
TELEOP_RANGES = {
    "validity_ms": (20, 100), "max_leader_age_ms": (20, 2000),
    "source_timeout_ms": (50, 5000), "max_handover_jump_rad": (0.01, 0.5),
}  # fmt: skip
MAPPING_KEYS = ("leader_joint", "scale", "leader_reference_rad", "follower_reference_rad")
MAX_CAMERAS = 6
MAX_ARMS = 8
ARM_ID = re.compile(r"[a-z][a-z0-9_]{0,15}")
MERGED_STATE, MERGED_LEADER = "/joint_states", "/leader/joint_states"
COMBINED_INTENT = "/platform/control/joint_intent"


def fail(message):
    sys.exit(f"render_cell_config: {message}")


def number(value, label, low, high, integer=False):
    if isinstance(value, bool) or not isinstance(value, int if integer else (int, float)):
        fail(f"{label} must be a {'whole ' if integer else ''}number")
    if not math.isfinite(value) or not low <= value <= high:
        fail(f"{label} must be from {low} to {high}")
    return value


def flt(value):
    return repr(float(value))


def profile_of(raw):
    if not isinstance(raw, dict):
        fail("robot_profile is required")
    ident, joints, topics = raw.get("id"), raw.get("joint_names"), raw.get("topics")
    configs = raw.get("recorder_robot_config")
    if not isinstance(ident, str) or not ROBOT_ID.fullmatch(ident):
        fail("robot_profile.id is invalid")
    if (
        not isinstance(joints, list)
        or not 1 <= len(joints) <= 32
        or len(set(joints)) != len(joints)
        or not all(isinstance(j, str) and JOINT.fullmatch(j) for j in joints)
    ):
        fail("robot_profile.joint_names is invalid")
    if not isinstance(topics, dict) or not all(
        isinstance(topics.get(k), str) and TOPIC.fullmatch(topics[k])
        for k in ("joint_states", "leader_joint_states")
    ):
        fail("robot_profile.topics is invalid")
    if not isinstance(configs, dict) or not all(
        isinstance(configs.get(k), str) and FILE.fullmatch(configs[k]) for k in ("sim", "real")
    ):
        fail("robot_profile.recorder_robot_config is invalid")
    return {"id": ident, "joint_names": list(joints), "topics": topics, "recorder_robot_config": configs}


def teleop_settings(raw, joint_names):
    raw = {} if raw is None else raw
    if not isinstance(raw, dict) or set(raw) - set(TELEOP_DEFAULTS) - {"joint_mapping"}:
        fail("teleop settings contain an unknown key")
    settings = dict(TELEOP_DEFAULTS)
    for key, (low, high) in TELEOP_RANGES.items():
        if key in raw:
            settings[key] = number(raw[key], key, low, high, integer=key.endswith("_ms"))
    mapping = raw.get("joint_mapping") or {}
    if not isinstance(mapping, dict):
        fail("teleop.joint_mapping must be a mapping")
    clean = {}
    for joint, entry in mapping.items():
        if joint not in joint_names or not isinstance(entry, dict) or set(entry) - set(MAPPING_KEYS):
            fail(f"teleop.joint_mapping.{joint} is not valid for this robot")
        item = {}
        for key in MAPPING_KEYS:
            if key not in entry:
                continue
            value = entry[key]
            if key == "leader_joint":
                if value not in joint_names:
                    fail(f"teleop.joint_mapping.{joint}.leader_joint is not a joint of this robot")
                item[key] = value
            elif key == "scale":
                item[key] = float(number(value, f"{joint}.scale", -10.0, 10.0))
                if abs(item[key]) < 0.01:
                    fail(f"teleop.joint_mapping.{joint}.scale must not be zero")
            else:
                item[key] = float(number(value, f"{joint}.{key}", -6.3, 6.3))
        clean[joint] = item
    settings["joint_mapping"] = clean
    return settings


def control_params(profile, settings):
    """ROS parameters per node, as the arbiter and teleop source read them."""
    source = {
        "leader_joint_states_topic": profile["topics"]["leader_joint_states"],
        "intent_topic": "/platform/control/sources/teleop/joint_intent",
        "joint_names": list(profile["joint_names"]),
        "target_id": profile["id"],
        "source_id": "teleop",
        "validity_ms": settings["validity_ms"],
        "max_leader_age_ms": settings["max_leader_age_ms"],
    }
    if settings["joint_mapping"]:
        source["joint_mapping"] = settings["joint_mapping"]
    if profile.get("joint_limits"):
        source["joint_limits"] = profile["joint_limits"]
    arbiter = {
        "active_source": "none",
        "sources": ["teleop", "policy"],
        "joint_names": list(profile["joint_names"]),
        "joint_states_topic": profile["topics"]["joint_states"],
        "output_topic": "/platform/control/joint_intent",
        "source_timeout_ms": settings["source_timeout_ms"],
        "max_handover_jump_rad": float(settings["max_handover_jump_rad"]),
    }
    return {"teleop_source": source, "control_arbiter": arbiter}


def control_files(profile, settings, simulated_follower=False):
    nodes = control_params(profile, settings)
    arbiter = dict(nodes["control_arbiter"])
    if simulated_follower:
        arbiter["mock_handover_rate"] = 0.5
    joints = arbiter.pop("joint_names")
    arbiter_text = ["control_arbiter:", "  ros__parameters:"]
    for key, item in arbiter.items():
        if key == "sources":
            arbiter_text.append(f"    sources: [{', '.join(item)}]")
        else:
            arbiter_text.append(f"    {key}: {flt(item) if isinstance(item, float) else item}")
        if key == "sources":
            arbiter_text.append(f"    joint_names: [{', '.join(joints)}]")
    teleop = nodes["teleop_source"]
    text = ["teleop_source:", "  ros__parameters:"]
    for key, item in teleop.items():
        if key == "joint_names":
            text += ["    joint_names:", *(f"      - {j}" for j in item)]
        elif key == "joint_limits":
            text.append("    joint_limits:")
            for joint, limits in item.items():
                text.append(f"      {joint}:")
                text += [f"        {k}: {flt(v)}" for k, v in limits.items()]
        elif key == "joint_mapping":
            text.append("    joint_mapping:")
            for joint, entry in item.items():
                text.append(f"      {joint}:")
                text += [f"        {k}: {flt(v) if isinstance(v, float) else v}" for k, v in entry.items()]
        else:
            text.append(f"    {key}: {item}")
    return {"arbiter.yaml": "\n".join(arbiter_text) + "\n", "teleop.yaml": "\n".join(text) + "\n"}


def cameras_of(raw):
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_CAMERAS:
        fail(f"1 to {MAX_CAMERAS} cameras are required")
    cameras, names = [], set()
    for entry in raw:
        if not isinstance(entry, dict):
            fail("camera entry is invalid")
        name, topic = entry.get("name"), entry.get("topic")
        if not isinstance(name, str) or not ID.fullmatch(name) or name in names:
            fail("camera name is invalid or repeated")
        if not isinstance(topic, str) or not TOPIC.fullmatch(topic):
            fail("camera topic is invalid")
        names.add(name)
        cameras.append({
            "name": name, "topic": topic,
            "width": number(entry.get("width"), "camera width", 160, 1920, True),
            "height": number(entry.get("height"), "camera height", 120, 1080, True),
            "fps": float(number(entry.get("fps"), "camera fps", 5, 60)),
        })  # fmt: skip
    return cameras


def camera_text(camera, gap_ms):
    automatic = max(75.0, round(2.25 * 1000.0 / camera["fps"], 1))
    gap = float(gap_ms) if gap_ms else automatic
    return "\n".join([
        "schema_version: camera-config/v1", "camera:",
        f"  name: {camera['name']}", f"  topic: {camera['topic']}", "  type: sensor_msgs/msg/CompressedImage",
        f"  width: {camera['width']}", f"  height: {camera['height']}", "  format: jpeg",
        f"  fps: {flt(camera['fps'])}", "  fps_tolerance: 0.6", "  minimum_coverage: 0.98",
        f"  maximum_gap_ms: {flt(gap)}",
    ]) + "\n"  # fmt: skip


def calibration_provenance(robot, directory, *names):
    """Calibration id and digest for the recordings; mock cells use the fixed identity calibration."""
    if robot != "real":
        return dict(MOCK_CALIBRATION)
    if not 2 <= len(names) <= MAX_ARMS or len(set(names)) != len(names):
        fail("calibration needs 2 to 8 distinct files")
    digest = hashlib.sha256()
    for name in names:
        if not isinstance(name, str) or not FILE.fullmatch(name):
            fail("calibration file name is invalid")
        path = Path(directory) / name
        if not path.is_file() or path.is_symlink():
            fail(f"calibration file {name} is missing")
        digest.update(name.encode() + b"\0" + path.read_bytes() + b"\0")
    return {"id": f"so101-real-{digest.hexdigest()[:12]}", "hash": f"sha256:{digest.hexdigest()}"}


def _scalar(text):
    text = text.strip()
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", text):
        return float(text)
    if text in ("true", "false"):
        return text == "true"
    if text[:1] in "\"'" and text[-1:] == text[:1]:
        return text[1:-1]
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", text):
        fail(f"unsupported robot config value {text!r}")
    return text


def _flow(text):
    inner = text.strip()[1:-1].strip()
    items = [item.strip() for item in inner.split(",")] if inner else []
    if text.strip().startswith("["):
        return [_scalar(item) for item in items]
    pairs = [item.split(":", 1) for item in items]
    if any(len(pair) != 2 for pair in pairs):
        fail("unsupported robot config mapping")
    return {key.strip(): _scalar(value) for key, value in pairs}


def _value(text):
    text = text.strip()
    return _flow(text) if text[:1] in "[{" else _scalar(text)


def read_robot_config(text):
    """robot-config/v1 as a dict. Strict block-YAML subset for hosts without PyYAML."""
    try:
        import yaml
    except ImportError:
        yaml = None
    if yaml is not None:
        return yaml.safe_load(text)
    lines = []
    for raw in text.splitlines():
        body = raw.split(" #", 1)[0].rstrip()
        if body.strip() and not body.strip().startswith("#"):
            lines.append((len(body) - len(body.lstrip(" ")), body.strip()))

    def block(index, indent):
        if lines[index][1].startswith("- "):
            items = []
            while index < len(lines) and lines[index][0] == indent and lines[index][1].startswith("- "):
                item = lines[index][1][2:]
                if item.startswith("{") or ":" not in item:
                    items.append(_value(item))
                    index += 1
                else:  # a mapping whose first key shares the dash line
                    lines[index] = (indent + 2, item)
                    value, index = block(index, indent + 2)
                    items.append(value)
            return items, index
        mapping = {}
        while index < len(lines) and lines[index][0] == indent and not lines[index][1].startswith("- "):
            key, _, rest = lines[index][1].partition(":")
            if not _ or not re.fullmatch(r"[A-Za-z0-9_]+", key):
                fail(f"unsupported robot config line {lines[index][1]!r}")
            index += 1
            if rest.strip():
                mapping[key] = _value(rest)
            elif index < len(lines) and lines[index][0] > indent:
                mapping[key], index = block(index, lines[index][0])
            else:
                mapping[key] = None
        return mapping, index

    document, index = block(0, 0) if lines else ({}, 0)
    if index != len(lines):
        fail("unsupported robot config layout")
    return document


def base_robot(robots_dir, name, joint_names):
    path = Path(robots_dir) / name
    if not FILE.fullmatch(name) or not path.is_file():
        fail(f"robot config {name} is missing")
    document = read_robot_config(path.read_text(encoding="utf-8"))
    robot = document.get("robot") if isinstance(document, dict) else None
    if document.get("schema_version") != "robot-config/v1" or not isinstance(robot, dict):
        fail(f"{name} is not a robot-config/v1 file")
    joints = [joint.get("name") for joint in robot.get("joints") or [] if isinstance(joint, dict)]
    if joints != list(joint_names):
        fail(f"{name} joints do not match the robot profile")
    return robot


def arms_of(raw, joint_names):
    if not isinstance(raw, list) or not 2 <= len(raw) <= MAX_ARMS:
        fail("arms must list 2 to 8 arms")
    arms, ids = [], set()
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) - {"id", "role", "robot", "leader", "joint_mapping"}:
            fail("arm entry is invalid")
        ident, role = entry.get("id"), entry.get("role")
        if not isinstance(ident, str) or not ARM_ID.fullmatch(ident) or ident in ids:
            fail("arm id is invalid or repeated")
        if role not in ("leader", "follower") or entry.get("robot") not in ("sim", "real"):
            fail(f"arm {ident}: role or robot is invalid")
        ids.add(ident)
        arms.append(dict(entry))
    leaders = {a["id"] for a in arms if a["role"] == "leader"}
    followers = [a for a in arms if a["role"] == "follower"]
    if not leaders or not followers:
        fail("arms need at least one leader and one follower")
    for follower in followers:
        if follower.get("leader") not in leaders:
            fail(f"arm {follower['id']}: leader is not a leader arm")
    names = [f"{a['id']}_{j}" for a in arms for j in joint_names]
    if len(set(names)) != len(names) or not all(JOINT.fullmatch(n) for n in names):
        fail("prefixed joint names collide or are too long")
    return arms


def multi_arm_files(out, profile, arms, settings, robots_dir):
    """Combined recorder robot, one bridge robot per follower, the adapter map and the control files."""
    joints, rid = profile["joint_names"], profile["id"]
    configs = profile["recorder_robot_config"]
    base = {kind: base_robot(robots_dir, configs[kind], joints) for kind in ("sim", "real")}
    combined_id = f"{rid}_cell"
    (out / "robots").mkdir(parents=True, exist_ok=True)
    followers = [a for a in arms if a["role"] == "follower"]
    combined_joints, combined_groups, adapter = [], [], {"followers": [], "leaders": []}
    for arm in arms:
        namespace = f"/arm_{arm['id']}"
        robot = base[arm["robot"]]
        entry = {
            "id": arm["id"], "state_topic": f"{namespace}/joint_states",
            "joints": list(joints), "prefixed": [f"{arm['id']}_{j}" for j in joints],
        }  # fmt: skip
        if arm["role"] == "leader":
            adapter["leaders"].append(entry)
            continue
        target = f"{rid}_{arm['id']}"
        intent = f"/platform/control/arms/{arm['id']}/joint_intent"
        groups = [
            {**group, "endpoint": namespace + "/" + str(group["endpoint"]).lstrip("/")}
            for group in robot["command_adapter"]["groups"]
        ]
        own = {
            **robot, "id": f"{robot['id']}_{arm['id']}", "target_id": target,
            "state": {**robot["state"], "topic": entry["state_topic"]},
            "action": {**robot["action"], "topic": intent},
            "command_adapter": {**robot["command_adapter"], "groups": groups},
        }  # fmt: skip
        document = {"schema_version": "robot-config/v1", "robot": own}
        (out / "robots" / f"{arm['id']}.yaml").write_text(
            json.dumps(document, indent=2) + "\n", encoding="utf-8"
        )
        adapter["followers"].append({**entry, "intent_topic": intent, "target_id": target})
        rename = dict(zip(joints, entry["prefixed"]))
        combined_joints += [{**joint, "name": rename[joint["name"]]} for joint in robot["joints"]]
        combined_groups += [
            {**group, "name": f"{arm['id']}_{group['name']}", "joints": [rename[j] for j in group["joints"]]}
            for group in groups
        ]
    real = any(a["robot"] == "real" for a in followers)
    first = base["real" if real else "sim"]
    skew = max(float(base[a["robot"]]["state"].get("maximum_skew_ms", 25.0)) for a in followers)
    combined = {
        "id": f"{first['id']}_cell", "robot_type": first["robot_type"], "target_id": combined_id,
        "state": {**first["state"], "topic": MERGED_STATE, "maximum_skew_ms": skew},
        "action": {**first["action"], "topic": COMBINED_INTENT},
        "joints": combined_joints,
        "command_adapter": {"groups": combined_groups},
    }  # fmt: skip
    document = {"schema_version": "robot-config/v1", "robot": combined}
    (out / "robots" / "cell.yaml").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    adapter.update(
        schema_version="mrp-arm-adapter/v1", target_id=combined_id, intent_topic=COMBINED_INTENT,
        merged_state_topic=MERGED_STATE, merged_leader_topic=MERGED_LEADER,
    )  # fmt: skip
    (out / "arms.json").write_text(json.dumps(adapter, indent=2) + "\n", encoding="utf-8")
    # One teleop source and one arbiter over the combined joints. Each follower joint follows the
    # same-named joint of its own leader unless the follower's joint_mapping says otherwise.
    mapping = {}
    for arm in followers:
        own = teleop_settings({"joint_mapping": arm.get("joint_mapping") or {}}, joints)["joint_mapping"]
        for joint in joints:
            item = dict(own.get(joint, {}))
            item["leader_joint"] = f"{arm['leader']}_{item.get('leader_joint', joint)}"
            mapping[f"{arm['id']}_{joint}"] = item
    combined_profile = {
        "id": combined_id,
        "joint_names": [f"{a['id']}_{j}" for a in followers for j in joints],
        "joint_limits": {j["name"]: {"lower": j["lower"], "upper": j["upper"]} for j in combined_joints},
        "topics": {"joint_states": MERGED_STATE, "leader_joint_states": MERGED_LEADER},
    }
    return combined_profile, {**settings, "joint_mapping": mapping}


def render(out, params, calibration, robots_dir=None):
    if not isinstance(params, dict):
        fail("parameters must be an object")
    robot = params.get("robot")
    if robot not in ("sim", "real"):
        fail("robot must be sim or real")
    profile = profile_of(params.get("robot_profile"))
    settings = teleop_settings(params.get("teleop"), profile["joint_names"])
    task = params.get("task_id")
    if not isinstance(task, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", task):
        fail("task_id is invalid")
    instruction = params.get("instruction") or ""
    if not isinstance(instruction, str) or len(instruction) > 400:
        fail("instruction must be text up to 400 characters")
    instruction = " ".join(instruction.split()) or DEFAULT_INSTRUCTIONS.get(task, FREE_INSTRUCTION)
    recording = params.get("recording")
    if not isinstance(recording, dict):
        fail("recording settings are required")
    minimum = number(recording.get("minimum_duration_seconds"), "minimum_duration_seconds", 1.0, 600.0)
    free_gib = number(recording.get("preflight_min_free_gib", 10.0), "preflight_min_free_gib", 0.5, 1000.0)
    gap = recording.get("maximum_camera_gap_ms", 0)
    if gap != 0:
        gap = number(gap, "maximum_camera_gap_ms", 50, 1000)
    cameras = cameras_of(params.get("cameras"))
    if not (
        isinstance(calibration, dict)
        and calibration.get("id")
        and str(calibration.get("hash", "")).startswith("sha256:")
    ):
        fail("calibration provenance is missing")

    mock_handover = params.get("mock_handover", False)
    if not isinstance(mock_handover, bool) or (mock_handover and robot != "sim"):
        fail("mock_handover requires simulated followers")
    prefix, rid = ("mock" if robot == "sim" else "real"), profile["id"]
    profile_id = f"{prefix}_{rid}_webcam_v1"
    robot_config = f"../../core/recorder/config/robots/{profile['recorder_robot_config'][robot]}"
    out = Path(out)
    (out / "control").mkdir(parents=True, exist_ok=True)
    control_profile = profile
    if params.get("arms") is not None:
        if settings["joint_mapping"]:
            fail("multi-arm cells keep the joint mapping per follower")
        arms = arms_of(params["arms"], profile["joint_names"])
        if robot != ("real" if any(a["robot"] == "real" for a in arms if a["role"] == "follower") else "sim"):
            fail("robot must be real exactly when a follower is real")
        control_profile, settings = multi_arm_files(out, profile, arms, settings, robots_dir or "/robots")
        profile_id = f"{prefix}_{rid}_cell_v1"
        robot_config = "robots/cell.yaml"
    else:
        if robots_dir:
            robot_limits = base_robot(
                robots_dir, profile["recorder_robot_config"][robot], profile["joint_names"]
            )
            control_profile = {
                **profile,
                "joint_limits": {
                    j["name"]: {"lower": j["lower"], "upper": j["upper"]} for j in robot_limits["joints"]
                },
            }
        for stale in ("arms.json",):
            (out / stale).unlink(missing_ok=True)
    for camera in cameras:
        (out / f"{camera['name']}.yaml").write_text(camera_text(camera, gap), encoding="utf-8")
    (out / "recording_profiles.yaml").write_text("\n".join([
        "schema_version: recording-profile/v2", "profiles:", f"  {profile_id}:",
        f"    robot_config: {robot_config}",
        f"    camera_configs: [{', '.join(c['name'] + '.yaml' for c in cameras)}]",
        f"    timeline_camera: {cameras[0]['name']}",
        f"    minimum_duration_seconds: {flt(minimum)}", "    maximum_source_receipt_offset_ms: 1000.0",
        "    optional_topics:", *(f"      - {topic}" for topic in OPTIONAL_TOPICS),
    ]) + "\n", encoding="utf-8")  # fmt: skip
    (out / "tasks.yaml").write_text("\n".join([
        "schema_version: task-catalog/v1", f"catalog_id: {prefix}_{rid}_tasks_v1", "tasks:", f"  {task}:",
        f"    instruction: {json.dumps(instruction, ensure_ascii=False)}",
        f"    recording_profile_id: {profile_id}", f"    minimum_duration_seconds: {flt(minimum)}",
    ]) + "\n", encoding="utf-8")  # fmt: skip
    (out / "workspace.yaml").write_text("\n".join([
        "schema_version: workspace-config/v1", "workspace:", f"  id: {prefix}_{rid}_webcam",
        "  # One recordings library for mock and real cells; episodes carry their own provenance.",
        f"  dataset_dir: /data/datasets/mock_{rid}", "  recording_profiles: recording_profiles.yaml",
        f"  recording_profile_id: {profile_id}", "  task_catalog: tasks.yaml", f"  task_id: {task}",
        "  calibration:", f"    id: {calibration['id']}", f"    hash: {calibration['hash']}",
        "  producer:", f"    source_revision: {prefix}-{rid}-config-v1",
        "  recorder:", f"    preflight_min_free_gib: {flt(free_gib)}", "    runtime_reserve_gib: 5.0",
        "  command_bridge_enabled: false",
    ]) + "\n", encoding="utf-8")  # fmt: skip
    for name, text in control_files(control_profile, settings, simulated_follower=mock_handover).items():
        (out / "control" / name).write_text(text, encoding="utf-8")


def main(argv):
    argv = list(argv)
    robots_dir = None
    if "--robots" in argv:
        at = argv.index("--robots")
        robots_dir = argv[at + 1] if at + 1 < len(argv) else fail("--robots needs a directory")
        del argv[at : at + 2]
    if len(argv) < 3 or len(argv) == 4:
        fail("usage: render_cell_config.py OUT_DIR PARAMS_JSON [CALIBRATION_DIR FILE...] [--robots DIR]")
    try:
        params = json.loads(argv[2])
    except ValueError:
        fail("parameters are not valid JSON")
    robot = params.get("robot") if isinstance(params, dict) else None
    calibration = calibration_provenance(robot, *argv[3:]) if len(argv) > 4 else dict(MOCK_CALIBRATION)
    render(argv[1], params, calibration, robots_dir)
    print(calibration["hash"])


if __name__ == "__main__":
    main(sys.argv)
