# flake8: noqa: Q000
from contextlib import ExitStack
from unittest.mock import Mock

import pytest
import rclpy
from sensor_msgs.msg import JointState

from control_arbiter.teleop_source import JointMapping, TeleopSource, ordered_positions


JOINTS = ["j1", "j2"]


def test_positions_are_reordered_to_configured_joint_order():
    assert ordered_positions(["j2", "j1"], [2.0, 1.0], JOINTS) == [1.0, 2.0]


def test_malformed_or_non_finite_joint_states_are_rejected():
    assert ordered_positions(["j1"], [1.0, 2.0], JOINTS) is None
    assert ordered_positions(["j1", "j1"], [1.0, 2.0], JOINTS) is None
    assert ordered_positions(["j1"], [1.0], JOINTS) is None
    assert ordered_positions(["j1", "j2"], [1.0, float("nan")], JOINTS) is None


def test_mapping_defaults_to_identity_and_can_reverse_around_reference_poses():
    assert JointMapping("j1").target(0.25) == 0.25
    mapping = JointMapping("other_leader_joint", -1.0, 0.20, -0.10)
    assert mapping.target(0.20) == pytest.approx(-0.10)
    assert mapping.target(0.30) == pytest.approx(-0.20)


@pytest.mark.parametrize(
    "values", [("", 1.0), ("j1", 0.0), ("j1", float("nan")), ("j1", 1.0, float("inf"))]
)
def test_mapping_rejects_invalid_values(values):
    with pytest.raises(ValueError):
        JointMapping(*values)


def test_ros_yaml_mapping_is_applied_to_the_published_intent(tmp_path, monkeypatch):
    config = tmp_path / "teleop.yaml"
    config.write_text(
        """teleop_source:
  ros__parameters:
    joint_names: [shoulder_pan_joint, wrist_roll_joint, gripper_joint]
    joint_mapping:
      shoulder_pan_joint:
        scale: -1.0
        leader_reference_rad: 0.2
        follower_reference_rad: -0.1
      wrist_roll_joint:
        leader_joint: leader_wrist_roll
"""
    )
    with ExitStack() as cleanup:
        rclpy.init(args=["--ros-args", "--params-file", str(config)])
        cleanup.callback(rclpy.shutdown)
        node = TeleopSource()
        cleanup.callback(node.destroy_node)
        publisher = Mock()
        patch = cleanup.enter_context(monkeypatch.context())
        patch.setattr(node, "publisher", publisher)
        state = JointState()
        state.name = ["leader_wrist_roll", "gripper_joint", "shoulder_pan_joint"]
        state.position = [0.4, 0.6, 0.3]
        state.header.stamp = node.get_clock().now().to_msg()
        node.on_joint_state(state)

        publisher.publish.assert_called_once()
        intent = publisher.publish.call_args.args[0]
        assert list(intent.joint_names) == [
            "shoulder_pan_joint",
            "wrist_roll_joint",
            "gripper_joint",
        ]
        assert list(intent.positions) == pytest.approx([-0.2, 0.4, 0.6])


def test_teleop_caps_each_mapped_joint_independently(tmp_path, monkeypatch):
    config = tmp_path / "limits.yaml"
    config.write_text("""teleop_source:
  ros__parameters:
    joint_names: [j1, j2]
    joint_limits:
      j1: {lower: -1.0, upper: 1.0}
      j2: {lower: 0.0, upper: 2.0}
""")
    with ExitStack() as cleanup:
        rclpy.init(args=["--ros-args", "--params-file", str(config)])
        cleanup.callback(rclpy.shutdown)
        node = TeleopSource()
        cleanup.callback(node.destroy_node)
        publisher = Mock()
        cleanup.enter_context(monkeypatch.context()).setattr(
            node, "publisher", publisher
        )
        state = JointState()
        state.name = ["j1", "j2"]
        state.position = [0.4, -0.5]
        state.header.stamp = node.get_clock().now().to_msg()
        node.on_joint_state(state)
        assert list(publisher.publish.call_args.args[0].positions) == pytest.approx(
            [0.4, 0.0]
        )
