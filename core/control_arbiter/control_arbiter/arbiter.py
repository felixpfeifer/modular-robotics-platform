#!/usr/bin/env python3
# flake8: noqa: Q000
"""Select, hand over, and watchdog command sources."""

from __future__ import annotations

import time
import math

from control_arbiter.arbitration import Arbitration, smooth_handover, valid_intent_time
from platform_control_interfaces.msg import JointIntent
import rclpy
from rcl_interfaces.msg import SetParametersResult
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import JointState
from std_msgs.msg import String


class ControlArbiter(Node):
    def __init__(self) -> None:
        super().__init__("control_arbiter")
        self.declare_parameter("active_source", "none")
        self.declare_parameter("sources", ["teleop", "policy"])
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
        self.declare_parameter("joint_states_topic", "/joint_states")
        self.declare_parameter("output_topic", "/platform/control/joint_intent")
        self.declare_parameter("source_timeout_ms", 200)
        self.declare_parameter("max_handover_jump_rad", 0.15)
        self.declare_parameter("mock_handover_rate", 0.0)
        self.mock_handover_rate = float(self.get_parameter("mock_handover_rate").value)
        self.ramping = False
        self.ramp_time_ns = 0

        source_names = tuple(str(item) for item in self.get_parameter("sources").value)
        joint_names = tuple(
            str(item) for item in self.get_parameter("joint_names").value
        )
        timeout_ms = int(self.get_parameter("source_timeout_ms").value)
        if timeout_ms <= 0:
            raise ValueError("source_timeout_ms must be positive")
        initial_source = str(self.get_parameter("active_source").value)
        self.arbitration = Arbitration(
            source_names,
            initial_source,
            joint_names,
            float(self.get_parameter("max_handover_jump_rad").value),
            timeout_ms * 1_000_000,
        )
        self.follower_positions: dict[str, float] = {}
        self.follower_state_ns: int = 0
        self.source_subscriptions = []

        latched_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.active_source_publisher = self.create_publisher(
            String, "/platform/control/active_source", latched_qos
        )
        self.output_publisher = self.create_publisher(
            JointIntent, str(self.get_parameter("output_topic").value), 10
        )
        self.state_subscription = self.create_subscription(
            JointState,
            str(self.get_parameter("joint_states_topic").value),
            self.on_follower_state,
            10,
        )
        for source in source_names:
            topic = f"/platform/control/sources/{source}/joint_intent"
            self.source_subscriptions.append(
                self.create_subscription(
                    JointIntent,
                    topic,
                    lambda message, name=source: self.on_intent(name, message),
                    10,
                )
            )
        self.add_on_set_parameters_callback(self.on_parameters)
        self.publish_active_source()
        self.watchdog_timer = self.create_timer(
            0.005,
            self.check_watchdog,
            clock=Clock(clock_type=ClockType.STEADY_TIME),
        )

    def on_parameters(self, parameters) -> SetParametersResult:
        for parameter in parameters:
            if parameter.name != "active_source":
                continue
            source = str(parameter.value)
            if source != "none" and source not in self.arbitration.sources:
                return SetParametersResult(
                    successful=False,
                    reason=(
                        f"unknown source '{source}'; allowed: none, "
                        f"{', '.join(sorted(self.arbitration.sources))}"
                    ),
                )
            self.arbitration.select_source(source)
            self.ramping = source == "teleop" and self.mock_handover_rate > 0
            self.ramp_time_ns = time.monotonic_ns()
            self.publish_active_source()
            self.get_logger().info(
                f"active source set to {source}; handover gate armed"
            )
        return SetParametersResult(successful=True)

    def on_follower_state(self, message: JointState) -> None:
        if len(message.name) != len(message.position) or len(message.name) != len(
            set(message.name)
        ):
            return
        values = dict(zip(message.name, message.position))
        if any(name not in values for name in self.arbitration.joint_names):
            return
        self.follower_positions = {
            name: float(values[name]) for name in self.arbitration.joint_names
        }
        self.follower_state_ns = time.monotonic_ns()

    def on_intent(self, source: str, message: JointIntent) -> None:
        issued = int(message.issued_at.sec) * 1_000_000_000 + int(
            message.issued_at.nanosec
        )
        until = int(message.valid_until.sec) * 1_000_000_000 + int(
            message.valid_until.nanosec
        )
        if message.source_id != source or not valid_intent_time(
            issued, until, self.get_clock().now().nanoseconds
        ):
            return
        now_ns = time.monotonic_ns()
        follower_positions = self.follower_positions
        if now_ns - self.follower_state_ns > self.arbitration.source_timeout_ns:
            follower_positions = {}
        if (
            self.ramping
            and source == "teleop"
            and self.arbitration.active_source == source
        ):
            if (
                set(message.joint_names) != set(self.arbitration.joint_names)
                or len(message.joint_names) != len(message.positions)
                or len(set(message.joint_names)) != len(message.joint_names)
                or set(follower_positions) != set(self.arbitration.joint_names)
                or not all(
                    math.isfinite(v)
                    for v in (*message.positions, *follower_positions.values())
                )
            ):
                return
            elapsed = min(max((now_ns - self.ramp_time_ns) / 1e9, 0), 0.05)
            self.ramp_time_ns = now_ns
            step = self.mock_handover_rate * elapsed
            desired = list(message.positions)
            message.positions = smooth_handover(
                message.joint_names, desired, follower_positions, step
            )
            if all(
                abs(value - follower_positions[name])
                <= self.arbitration.max_handover_jump_rad
                for name, value in zip(message.joint_names, desired)
            ):
                self.ramping = False
        accepted = self.arbitration.accept_intent(
            source,
            tuple(message.joint_names),
            tuple(message.positions),
            now_ns,
            follower_positions,
        )
        if accepted:
            self.output_publisher.publish(message)
        elif source == self.arbitration.active_source and not self.arbitration.armed:
            self.get_logger().debug(
                f"waiting for {source} intent within handover tolerance"
            )

    def check_watchdog(self) -> None:
        if self.arbitration.check_watchdog(time.monotonic_ns()):
            self.ramping = (
                self.arbitration.active_source == "teleop"
                and self.mock_handover_rate > 0
            )
            self.ramp_time_ns = time.monotonic_ns()
            self.get_logger().warning(
                f"source {self.arbitration.active_source} timed out; forwarding stopped"
            )

    def publish_active_source(self) -> None:
        message = String()
        message.data = self.arbitration.active_source
        self.active_source_publisher.publish(message)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ControlArbiter()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
