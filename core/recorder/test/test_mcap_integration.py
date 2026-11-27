from __future__ import annotations

import gc
import json
import math
import shutil
import uuid
from pathlib import Path

import cv2
import numpy as np
import pytest
import rosbag2_py
from platform_control_interfaces.msg import CommandRejection, JointIntent, SafetyEvent
from platform_episode_interfaces.msg import EpisodeEvent, EpisodeMetadata
from rclpy.serialization import serialize_message
from sensor_msgs.msg import CompressedImage, JointState

from episode_recorder_py.configuration import recording_profile_hash
from episode_recorder_py.validation import sha256_file, validate_episode
from episode_recorder_py.export_lerobot import load_accepted_manifest


ROOT = Path(__file__).parents[1]
PROFILE = ROOT / "config/recording_profiles.yaml"
TASKS = ROOT / "config/task_catalog.yaml"
MCAP_OPTIONS = ROOT / "config/mcap_writer_options.yaml"
JOINTS = [
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_flex_joint",
    "wrist_flex_joint",
    "wrist_roll_joint",
    "gripper_joint",
]


def _stamp(target, nanoseconds: int) -> None:
    target.sec = nanoseconds // 1_000_000_000
    target.nanosec = nanoseconds % 1_000_000_000


def _topic(name: str, type_name: str) -> rosbag2_py.TopicMetadata:
    return rosbag2_py.TopicMetadata(
        id=0,
        name=name,
        type=type_name,
        serialization_format="cdr",
    )


def _frame(index: int, source_ns: int) -> CompressedImage:
    x = np.linspace(20, 220, 640, dtype=np.uint8)
    gray = np.tile(x, (480, 1))
    image = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    cv2.circle(image, (70 + (index * 29) % 500, 240), 60, (20, 230, 80), -1)
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    assert ok
    message = CompressedImage()
    _stamp(message.header.stamp, source_ns)
    message.header.frame_id = "top_camera"
    message.format = "jpeg"
    message.data = encoded.tobytes()
    return message


def _state(index: int, source_ns: int, moving: bool = True) -> JointState:
    message = JointState()
    _stamp(message.header.stamp, source_ns)
    message.name = list(JOINTS)
    motion = 0.1 * math.sin(index / 30.0) if moving else 0.0
    message.position = [motion, -motion, motion / 2, -motion / 2, motion, 0.8 + motion]
    return message


def _action(
    index: int, source_ns: int, expired: bool = False, moving: bool = True
) -> JointIntent:
    message = JointIntent()
    message.command_id.uuid = list(uuid.uuid4().bytes)
    message.lease_id.uuid = list(uuid.uuid4().bytes)
    message.source_id = "synthetic-ci"
    message.target_id = "so101"
    _stamp(message.issued_at, source_ns)
    _stamp(message.valid_until, source_ns - 1 if expired else source_ns + 50_000_000)
    message.joint_names = list(JOINTS)
    motion = 0.1 * math.sin(index / 10.0) if moving else 0.0
    message.positions = [motion, -motion, motion / 2, -motion / 2, motion, 0.8 + motion]
    return message


def _write_episode(
    root: Path,
    *,
    operator_success: bool = True,
    expired_actions: bool = False,
    frozen_camera: bool = False,
    moving_robot: bool = True,
    fault: str | None = None,
    recording_profile: Path = PROFILE,
    profile_id: str = "so101_vla_rgb_30_v1",
    extra_camera_topic: str | None = None,
    frame_step_ns: int = 33_333_334,
) -> Path:
    episode_id = str(uuid.uuid4())
    episode_dir = root / "episodes" / episode_id
    bag_dir = episode_dir / "bag"
    episode_dir.mkdir(parents=True)
    writer = rosbag2_py.SequentialWriter()
    writer.open(
        rosbag2_py.StorageOptions(
            uri=str(bag_dir),
            storage_id="mcap",
            max_bagfile_size=0,
            max_bagfile_duration=0,
            storage_config_uri=str(MCAP_OPTIONS),
        ),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    topics = {
        "/image/compressed": "sensor_msgs/msg/CompressedImage",
        "/joint_states": "sensor_msgs/msg/JointState",
        "/platform/control/joint_intent": "platform_control_interfaces/msg/JointIntent",
        "/platform/episode/metadata": "platform_episode_interfaces/msg/EpisodeMetadata",
        "/platform/episode/events": "platform_episode_interfaces/msg/EpisodeEvent",
    }
    if extra_camera_topic:
        topics[extra_camera_topic] = "sensor_msgs/msg/CompressedImage"
    if fault == "safety_error":
        topics["/platform/control/safety_events"] = (
            "platform_control_interfaces/msg/SafetyEvent"
        )
    if fault == "command_rejection":
        topics["/platform/control/command_rejections"] = (
            "platform_control_interfaces/msg/CommandRejection"
        )
    omitted_topic = {
        "missing_camera": "/image/compressed",
        "missing_state": "/joint_states",
        "missing_action": "/platform/control/joint_intent",
    }.get(fault)
    for name, type_name in topics.items():
        if name == omitted_topic:
            continue
        writer.create_topic(_topic(name, type_name))

    base_ns = 10_000_000_000
    records: list[tuple[int, int, str, object]] = []
    metadata = EpisodeMetadata()
    metadata.episode_id.uuid = list(uuid.UUID(episode_id).bytes)
    metadata.workcell_id = "synthetic-ci"
    metadata.task_id = "default_demo"
    metadata.recording_profile_id = profile_id
    records.append(
        (
            base_ns - 1_000_000,
            base_ns - 1_000_000,
            "/platform/episode/metadata",
            metadata,
        )
    )

    frame_step = frame_step_ns
    frame_count = 31 if fault == "short" else 61
    for index in range(frame_count):
        gap_ns = 100_000_000 if fault == "camera_gap" and index >= 30 else 0
        source_ns = base_ns + index * frame_step + gap_ns
        receipt_offset = 2_000_000_000 if fault == "clock_domain" else 1_000_000
        image = _frame(0 if frozen_camera else index, source_ns)
        if fault == "corrupt_image" and index == 10:
            image.data = b"not-a-jpeg"
        elif fault in {"wrong_size_image", "blank_image"} and index == 10:
            pixels = (
                np.zeros((240, 320, 3), dtype=np.uint8)
                if fault == "wrong_size_image"
                else np.zeros((480, 640, 3), dtype=np.uint8)
            )
            ok, encoded = cv2.imencode(".jpg", pixels)
            assert ok
            image.data = encoded.tobytes()
        if omitted_topic != "/image/compressed":
            records.append(
                (source_ns + receipt_offset, source_ns, "/image/compressed", image)
            )
        if extra_camera_topic:
            extra_image = _frame(0 if frozen_camera else index + 7, source_ns)
            extra_image.header.frame_id = "extra_camera"
            records.append(
                (
                    source_ns + receipt_offset + 100_000,
                    source_ns,
                    extra_camera_topic,
                    extra_image,
                )
            )
        if omitted_topic != "/platform/control/joint_intent":
            action_source = (
                source_ns + 1_000_000 if fault == "future_action" else source_ns
            )
            action = _action(index, action_source, expired_actions, moving_robot)
            if fault == "duplicate_action_joint" and index == 10:
                action.joint_names[-1] = action.joint_names[0]
            elif fault == "nonfinite_action" and index == 10:
                action.positions[0] = math.nan
            elif fault == "action_limit" and index == 10:
                action.positions[0] = 100.0
            records.append(
                (
                    source_ns + 2_000_000,
                    source_ns,
                    "/platform/control/joint_intent",
                    action,
                )
            )
    for index in range((frame_count - 1) * frame_step // 10_000_000 + 2):
        source_ns = base_ns + index * 10_000_000
        state = _state(index, source_ns, moving_robot)
        if fault == "duplicate_state_joint" and index == 10:
            state.name[-1] = state.name[0]
        elif fault == "nonfinite_state" and index == 10:
            state.position[0] = math.inf
        elif fault == "state_limit" and index == 10:
            state.position[0] = 100.0
        if omitted_topic != "/joint_states":
            receipt_offset = 2_000_000_000 if fault == "clock_domain" else 500_000
            records.append(
                (source_ns + receipt_offset, source_ns, "/joint_states", state)
            )

    event = EpisodeEvent()
    _stamp(event.header.stamp, base_ns + frame_count * frame_step)
    event.episode_id.uuid = list(uuid.UUID(episode_id).bytes)
    event.event_id.uuid = list(uuid.uuid4().bytes)
    event.source_id = "synthetic-ci"
    event.kind = EpisodeEvent.KIND_OPERATOR
    event.event_code = 0
    event.summary = "operator marked success"
    records.append(
        (
            base_ns + frame_count * frame_step + 1_000_000,
            base_ns + frame_count * frame_step,
            "/platform/episode/events",
            event,
        )
    )

    if fault == "safety_error":
        safety = SafetyEvent()
        _stamp(safety.header.stamp, base_ns + frame_step)
        safety.event_id.uuid = list(uuid.uuid4().bytes)
        safety.source_id = "synthetic-ci"
        safety.target_id = "so101"
        safety.severity = SafetyEvent.SEVERITY_ERROR
        safety.summary = "synthetic safety error"
        records.append(
            (
                base_ns + frame_step + 1_000_000,
                base_ns + frame_step,
                "/platform/control/safety_events",
                safety,
            )
        )
    if fault == "command_rejection":
        rejection = CommandRejection()
        _stamp(rejection.header.stamp, base_ns + frame_step)
        rejection.rejection_id.uuid = list(uuid.uuid4().bytes)
        rejection.source_id = "synthetic-ci"
        rejection.target_id = "so101"
        rejection.reason_code = 1
        rejection.reason = "synthetic rejection"
        records.append(
            (
                base_ns + frame_step + 1_000_000,
                base_ns + frame_step,
                "/platform/control/command_rejections",
                rejection,
            )
        )

    for receive_ns, send_ns, topic_name, message in sorted(records):
        writer.write(topic_name, serialize_message(message), receive_ns, send_ns)
    del writer
    gc.collect()

    mcap_files = list(episode_dir.rglob("*.mcap"))
    assert len(mcap_files) == 1
    manifest = {
        "schema_version": "episode-manifest/v1",
        "episode_id": episode_id,
        "artifact_id": episode_id,
        "content_hash": sha256_file(mcap_files[0]),
        "recording_profile_id": profile_id,
        "recording_profile_hash": recording_profile_hash(recording_profile, profile_id),
        "task_id": "default_demo",
        "task_catalog_hash": sha256_file(TASKS),
        "workcell_id": "synthetic-ci",
        "configuration_hash": sha256_file(PROFILE),
        "calibration_ids": ["synthetic-calibration-v1"],
        "producers": [
            {
                "component_id": "synthetic-fixture",
                "semantic_version": "0.2.0",
                "source_revision": "test-revision",
                "build_id": "test-build",
                "configuration_hash": sha256_file(PROFILE),
                "calibration_id": "synthetic-calibration-v1",
                "calibration_hash": "sha256:" + "1" * 64,
            }
        ],
        "started_ns": base_ns,
        "finalized_ns": base_ns + frame_count * frame_step,
        "operator_success": operator_success,
        "canceled": False,
        "writer_dropped": fault == "writer_drop",
        "writer_error": fault == "writer_error",
        "storage_id": "mcap",
    }
    (episode_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return episode_dir


@pytest.fixture(scope="module")
def valid_episode(tmp_path_factory) -> Path:
    return _write_episode(tmp_path_factory.mktemp("mcap-valid"))


def test_deterministic_mcap_fixture_is_training_eligible(valid_episode: Path):
    result = validate_episode(valid_episode, PROFILE, TASKS)
    failures = {finding.rule_id for finding in result.findings if finding.failing}
    assert result.valid, failures
    assert result.metrics["image_count"] == 61
    assert result.metrics["action_uncovered_frames"] == 0
    assert result.metrics["camera_fps"] == pytest.approx(30.0, rel=1e-5)
    assert (valid_episode / "validation/validation.json").is_file()
    assert (valid_episode / "validation/validation.junit.xml").is_file()


def test_multiple_configured_cameras_are_recorded_and_validated(tmp_path: Path):
    camera = tmp_path / "wrist.yaml"
    camera.write_text(
        """schema_version: camera-config/v1
camera: {name: wrist, topic: /wrist/image/compressed, type: sensor_msgs/msg/CompressedImage, width: 640, height: 480, format: jpeg, fps: 30.0, fps_tolerance: 0.6, minimum_coverage: 0.98, maximum_gap_ms: 75}
""",
        encoding="utf-8",
    )
    profiles = tmp_path / "profiles.yaml"
    profiles.write_text(
        f"""schema_version: recording-profile/v2
profiles:
  so101_two_camera_v1:
    robot_config: {ROOT / "config/robots/so101.yaml"}
    camera_configs: [{ROOT / "config/cameras/top_rgb_30.yaml"}, {camera}]
    timeline_camera: top
    minimum_duration_seconds: 2.0
    maximum_source_receipt_offset_ms: 1000.0
""",
        encoding="utf-8",
    )
    tasks = tmp_path / "tasks.yaml"
    tasks.write_text(
        """schema_version: task-catalog/v1
tasks:
  two_camera_demo:
    instruction: Test both observation cameras.
    recording_profile_id: so101_two_camera_v1
    minimum_duration_seconds: 2.0
""",
        encoding="utf-8",
    )
    episode = _write_episode(
        tmp_path / "dataset",
        recording_profile=profiles,
        profile_id="so101_two_camera_v1",
        extra_camera_topic="/wrist/image/compressed",
    )
    manifest_path = episode / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["task_id"] = "two_camera_demo"
    manifest["task_catalog_hash"] = sha256_file(tasks)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    result = validate_episode(episode, profiles, tasks)
    failures = {finding.rule_id for finding in result.findings if finding.failing}
    assert result.valid, failures
    assert result.metrics["camera_wrist_fps"] == pytest.approx(30.0, rel=1e-5)


def test_missing_terminal_success_has_stable_rejection_rule(
    valid_episode: Path, tmp_path: Path
):
    rejected = tmp_path / valid_episode.name
    shutil.copytree(valid_episode, rejected)
    manifest_path = rejected / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["operator_success"] = False
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    result = validate_episode(rejected, PROFILE, TASKS)
    failures = {finding.rule_id for finding in result.findings if finding.failing}
    assert not result.valid
    assert "episode.operator_success" in failures
    assert json.loads((rejected / "status.json").read_text())["status"] == "rejected"


def test_export_selection_refuses_stale_hash_and_unknown_validation_version(
    valid_episode: Path, tmp_path: Path
):
    validate_episode(valid_episode, PROFILE, TASKS)
    manifest = json.loads((valid_episode / "manifest.json").read_text(encoding="utf-8"))
    selection = tmp_path / "accepted.json"
    payload = {
        "schema_version": "accepted-episodes/v1",
        "episodes": [
            {"episode_id": valid_episode.name, "content_hash": manifest["content_hash"]}
        ],
    }
    selection.write_text(json.dumps(payload), encoding="utf-8")
    dataset_root = valid_episode.parents[1]
    assert len(load_accepted_manifest(selection, dataset_root, PROFILE, TASKS)) == 1

    payload["episodes"][0]["content_hash"] = "sha256:stale"
    selection.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="stale or changed artifact"):
        load_accepted_manifest(selection, dataset_root, PROFILE, TASKS)

    payload["episodes"][0]["content_hash"] = manifest["content_hash"]
    selection.write_text(json.dumps(payload), encoding="utf-8")
    report_path = valid_episode / "validation/validation.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["schema_version"] = "episode-validation/v999"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="unknown validation report version"):
            load_accepted_manifest(selection, dataset_root, PROFILE, TASKS)
    finally:
        report["schema_version"] = "episode-validation/v1"
        report_path.write_text(json.dumps(report), encoding="utf-8")


def test_expired_actions_have_stable_rejection_rule(tmp_path: Path):
    rejected = _write_episode(tmp_path, expired_actions=True)
    result = validate_episode(rejected, PROFILE, TASKS)
    failures = {finding.rule_id for finding in result.findings if finding.failing}
    assert not result.valid
    assert "action.schema_finite_limits" in failures
    assert "sync.action_causal_coverage" in failures
    coverage = next(
        finding
        for finding in result.findings
        if finding.rule_id == "sync.action_causal_coverage"
    )
    assert result.metrics["action_uncovered_frames"] == 61
    assert coverage.summary.startswith("61 of 61 camera frames had no valid robot command.")
    assert "First gap at 0.000 s" in coverage.summary
    assert "the latest command had expired" in coverage.summary


def test_frozen_camera_is_allowed_only_while_robot_is_stationary(tmp_path: Path):
    stationary = _write_episode(
        tmp_path / "stationary", frozen_camera=True, moving_robot=False
    )
    stationary_result = validate_episode(stationary, PROFILE, TASKS)
    assert stationary_result.valid

    moving = _write_episode(tmp_path / "moving", frozen_camera=True, moving_robot=True)
    moving_result = validate_episode(moving, PROFILE, TASKS)
    failures = {
        finding.rule_id for finding in moving_result.findings if finding.failing
    }
    assert not moving_result.valid
    assert "camera.frozen" in failures


@pytest.mark.parametrize(
    ("fault", "rule_id"),
    [
        ("short", "episode.minimum_duration"),
        ("missing_camera", "schema.topic.image_compressed"),
        ("missing_state", "schema.topic.joint_states"),
        ("missing_action", "schema.topic.platform_control_joint_intent"),
        ("wrong_size_image", "camera.dimensions"),
        ("clock_domain", "time.camera.clock_domain"),
        ("duplicate_state_joint", "state.schema_finite_limits"),
        ("nonfinite_state", "state.schema_finite_limits"),
        ("state_limit", "state.schema_finite_limits"),
        ("duplicate_action_joint", "action.schema_finite_limits"),
        ("nonfinite_action", "action.schema_finite_limits"),
        ("action_limit", "action.schema_finite_limits"),
        ("future_action", "sync.action_causal_coverage"),
        ("writer_drop", "writer.no_drops"),
        ("writer_error", "writer.no_errors"),
        ("safety_error", "safety.no_error"),
        ("command_rejection", "command.no_rejection"),
    ],
)
def test_negative_fixtures_have_stable_rule_ids(
    tmp_path: Path, fault: str, rule_id: str
):
    rejected = _write_episode(tmp_path / fault, fault=fault)
    result = validate_episode(rejected, PROFILE, TASKS)
    failures = {finding.rule_id for finding in result.findings if finding.failing}
    assert not result.valid
    assert rule_id in failures
    assert json.loads((rejected / "status.json").read_text())["status"] == "rejected"


def test_damaged_mcap_crc_is_rejected_after_hash_is_recomputed(tmp_path: Path):
    rejected = _write_episode(tmp_path / "damaged")
    mcap = next(rejected.rglob("*.mcap"))
    payload = bytearray(mcap.read_bytes())
    payload[len(payload) // 2] ^= 0xFF
    mcap.write_bytes(payload)
    manifest_path = rejected / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["content_hash"] = sha256_file(mcap)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    result = validate_episode(rejected, PROFILE, TASKS)
    failures = {finding.rule_id for finding in result.findings if finding.failing}
    assert not result.valid
    assert "storage.crc_indexes" in failures
