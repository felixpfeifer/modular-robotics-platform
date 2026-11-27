#!/usr/bin/env python3
# flake8: noqa: Q000
"""Convert leader joint states to the teleoperation JointIntent source."""

from __future__ import annotations

from dataclasses import dataclass
import math

from control_arbiter.intent import build_joint_intent
from control_arbiter.arbitration import is_fresh
from platform_control_interfaces.msg import JointIntent
from rcl_interfaces.msg import ParameterDescriptor
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState


def ordered_positions(
    names: list[str], positions: list[float], joint_names: list[str]
) -> list[float] | None:
    if len(names) != len(positions) or len(names) != len(set(names)):
        return None
    values = dict(zip(names, positions))
    if any(name not in values for name in joint_names):
        return None
    ordered = [float(values[name]) for name in joint_names]
    if not all(math.isfinite(value) for value in ordered):
        return None
    return ordered


@dataclass(frozen=True)
class JointMapping:
    leader_joint: str
    scale: float = 1.0
    leader_reference_rad: float = 0.0
    follower_reference_rad: float = 0.0

    def __post_init__(self) -> None:
        if not self.leader_joint.strip():
            raise ValueError("leader_joint must be non-empty")
        values = (self.scale, self.leader_reference_rad, self.follower_reference_rad)
        if self.scale == 0.0 or not all(math.isfinite(value) for value in values):
            raise ValueError(
                "joint mapping requires a finite nonzero scale and finite references"
            )

    def target(self, leader_position: float) -> float:
        displacement = leader_position - self.leader_reference_rad
        return self.follower_reference_rad + self.scale * displacement


class TeleopSource(Node):
    def __init__(self) -> None:
        super().__init__("teleop_source")
        self.declare_parameter("leader_joint_states_topic", "/leader/joint_states")
        self.declare_parameter(
            "intent_topic", "/platform/control/sources/teleop/joint_intent"
        )
        self.declare_parameter(
            "joint_names",
            [
                "shoulder_pan_joint",
                "shoulder_lift_joint",
                "elbow_flex_joint",
                "wrist_flex_joint",
                "wrist_roll_joint",
                "gripper_joint",
            ],
        )
        self.declare_parameter("target_id", "so101")
        self.declare_parameter("source_id", "teleop")
        self.declare_parameter("validity_ms", 80)
        self.declare_parameter("max_leader_age_ms", 200)

        self.joint_names = list(self.get_parameter("joint_names").value)
        self.target_id = str(self.get_parameter("target_id").value)
        self.source_id = str(self.get_parameter("source_id").value)
        self.validity_ms = int(self.get_parameter("validity_ms").value)
        self.max_leader_age_ns = (
            int(self.get_parameter("max_leader_age_ms").value) * 1_000_000
        )
        if self.max_leader_age_ns <= 0:
            raise ValueError("max_leader_age_ms must be positive")
        if not 1 <= self.validity_ms <= 100:
            raise ValueError("validity_ms must be between 1 and 100")
        if not self.joint_names or len(set(self.joint_names)) != len(self.joint_names):
            raise ValueError("joint_names must be non-empty and unique")

        self.joint_mapping = [
            self.load_joint_mapping(joint) for joint in self.joint_names
        ]
        self.joint_limits = []
        for joint in self.joint_names:
            lower, upper = self.declare_parameters(
                f"joint_limits.{joint}",
                [("lower", -float("inf")), ("upper", float("inf"))],
            )
            lo, hi = float(lower.value), float(upper.value)
            if math.isnan(lo) or math.isnan(hi) or lo >= hi:
                raise ValueError(f"joint_limits.{joint} must have lower < upper")
            self.joint_limits.append((lo, hi))
        self.leader_joint_names = [
            mapping.leader_joint for mapping in self.joint_mapping
        ]

        self.publisher = self.create_publisher(
            JointIntent, str(self.get_parameter("intent_topic").value), 10
        )
        self.subscription = self.create_subscription(
            JointState,
            str(self.get_parameter("leader_joint_states_topic").value),
            self.on_joint_state,
            10,
        )

    def load_joint_mapping(self, follower_joint: str) -> JointMapping:
        prefix = f"joint_mapping.{follower_joint}"
        values = self.declare_parameters(
            prefix,
            [
                (name, default, ParameterDescriptor(read_only=True))
                for name, default in (
                    ("leader_joint", follower_joint),
                    ("scale", 1.0),
                    ("leader_reference_rad", 0.0),
                    ("follower_reference_rad", 0.0),
                )
            ],
        )
        try:
            return JointMapping(*(parameter.value for parameter in values))
        except ValueError as exc:
            raise ValueError(f"{prefix}: {exc}") from exc

    def on_joint_state(self, message: JointState) -> None:
        issued_ns = int(message.header.stamp.sec) * 1_000_000_000 + int(
            message.header.stamp.nanosec
        )
        if not is_fresh(
            issued_ns, self.get_clock().now().nanoseconds, self.max_leader_age_ns
        ):
            return
        positions = ordered_positions(
            message.name, message.position, self.leader_joint_names
        )
        if positions is None:
            return
        targets = [
            mapping.target(position)
            for mapping, position in zip(self.joint_mapping, positions)
        ]
        if not all(math.isfinite(target) for target in targets):
            return

        targets = [
            max(lower, min(upper, value))
            for value, (lower, upper) in zip(targets, self.joint_limits)
        ]
        intent = build_joint_intent(
            self.joint_names,
            targets,
            self.get_clock().now().to_msg(),
            self.source_id,
            self.target_id,
            self.validity_ms,
        )
        self.publisher.publish(intent)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = TeleopSource()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
