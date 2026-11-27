from pathlib import Path

import pytest

from episode_recorder_py.configuration import (
    load_recording_profile,
    load_robot_config,
    load_workspace_config,
    recording_profile_hash,
)


ROOT = Path(__file__).parents[1]


def test_checked_in_workspace_resolves_robot_camera_and_stable_hashes():
    workspace = load_workspace_config(ROOT / "config/workspaces/local_so101.yaml")
    profile = workspace["profile"]
    assert profile["robot_type"] == "so101"
    assert profile["timeline_camera"] == "top"
    assert len(profile["joints"]) == 6
    assert profile["cameras"][0]["fps"] == 30.0
    assert profile["contract_hash"] == recording_profile_hash(
        ROOT / "config/recording_profiles.yaml", "so101_vla_rgb_30_v1"
    )
    assert workspace["configuration_hash"].startswith("sha256:")


def test_non_so_robot_and_different_camera_resolve_without_code_changes(tmp_path: Path):
    (tmp_path / "robot.yaml").write_text(
        """schema_version: robot-config/v1
robot:
  id: test_humanoid
  robot_type: humanoid
  target_id: humanoid_01
  state: {topic: /humanoid/joint_states, type: sensor_msgs/msg/JointState, maximum_skew_ms: 20, p99_skew_ms: 10}
  action: {topic: /platform/control/joint_intent, type: platform_control_interfaces/msg/JointIntent}
  joints:
    - {name: left_shoulder, unit: rad, lower: -2.0, upper: 2.0}
    - {name: right_shoulder, unit: rad, lower: -2.0, upper: 2.0}
    - {name: torso_yaw, unit: rad, lower: -1.0, upper: 1.0}
  command_adapter:
    groups:
      - {name: upper_body, transport: joint_trajectory_topic, endpoint: /upper_body/trajectory, duration_ms: 20, joints: [left_shoulder, right_shoulder]}
      - {name: torso, transport: joint_trajectory_topic, endpoint: /torso/trajectory, duration_ms: 20, joints: [torso_yaw]}
""",
        encoding="utf-8",
    )
    camera_path = tmp_path / "camera.yaml"
    camera_path.write_text(
        """schema_version: camera-config/v1
camera: {name: chest, topic: /chest/image/compressed, type: sensor_msgs/msg/CompressedImage, width: 320, height: 240, format: jpeg, fps: 15.0, fps_tolerance: 0.2, minimum_coverage: 0.98, maximum_gap_ms: 100}
""",
        encoding="utf-8",
    )
    profiles = tmp_path / "profiles.yaml"
    profiles.write_text(
        """schema_version: recording-profile/v2
profiles:
  humanoid_chest_v1:
    robot_config: robot.yaml
    camera_configs: [camera.yaml]
    timeline_camera: chest
    minimum_duration_seconds: 2.0
""",
        encoding="utf-8",
    )
    profile = load_recording_profile(profiles, "humanoid_chest_v1")
    assert [joint["name"] for joint in profile["joints"]] == [
        "left_shoulder",
        "right_shoulder",
        "torso_yaw",
    ]
    assert profile["cameras"][0]["width"] == 320
    original_hash = profile["contract_hash"]
    camera_path.write_text(
        camera_path.read_text(encoding="utf-8").replace("fps: 15.0", "fps: 20.0"),
        encoding="utf-8",
    )
    assert recording_profile_hash(profiles, "humanoid_chest_v1") != original_hash


def test_robot_adapter_rejects_missing_or_duplicate_joint_coverage(tmp_path: Path):
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text(
        """schema_version: robot-config/v1
robot:
  id: bad
  robot_type: bad
  target_id: bad
  state: {topic: /joint_states, type: sensor_msgs/msg/JointState}
  action: {topic: /intent, type: platform_control_interfaces/msg/JointIntent}
  joints:
    - {name: a, unit: rad, lower: -1, upper: 1}
    - {name: b, unit: rad, lower: -1, upper: 1}
  command_adapter:
    groups:
      - {name: arm, transport: joint_trajectory_topic, endpoint: /arm, joints: [a]}
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="partition"):
        load_robot_config(invalid)
