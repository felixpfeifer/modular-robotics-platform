#!/usr/bin/env python3
from __future__ import annotations

import math
import uuid
from pathlib import Path

import rclpy
from control_msgs.action import GripperCommand, ParallelGripperCommand
from platform_control_interfaces.msg import CommandRejection, JointIntent
from rclpy.action import ActionClient
from rclpy.node import Node
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

from episode_recorder_py.configuration import load_robot_config


# Fixture-compatible defaults; the running bridge always consumes robot_config.
JOINTS = [
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_flex_joint",
    "wrist_flex_joint",
    "wrist_roll_joint",
    "gripper_joint",
]
LIMITS = {
    "shoulder_pan_joint": (-1.91986, 1.91986),
    "shoulder_lift_joint": (-1.74533, 1.74533),
    "elbow_flex_joint": (-1.69, 1.54),
    "wrist_flex_joint": (-1.6, 1.6),
    "wrist_roll_joint": (-2.3, 2.3),
    "gripper_joint": (0.0, 1.70),
}


def time_ns(stamp) -> int:
    return int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)


def validate_joint_intent(
    message: JointIntent,
    now_ns: int,
    target_id: str,
    joint_names: list[str] | None = None,
    limits: dict[str, tuple[float, float]] | None = None,
    future_tolerance_ns: int = 0,
) -> tuple[dict[str, float] | None, str]:
    """Validate an intent. ``future_tolerance_ns`` covers simulated-clock skew only.

    Separate nodes may have processed different ``/clock`` ticks, so a fresh
    intent can look a few milliseconds ahead. Expiry is never relaxed.
    """
    joint_names = JOINTS if joint_names is None else joint_names
    limits = LIMITS if limits is None else limits
    issued_ns = time_ns(message.issued_at)
    valid_ns = time_ns(message.valid_until)
    if message.target_id and message.target_id != target_id:
        return None, "JointIntent target does not match this bridge"
    if issued_ns <= 0:
        return None, "zero JointIntent timestamp"
    if issued_ns > now_ns + future_tolerance_ns:
        return (
            None,
            f"JointIntent issued {(issued_ns - now_ns) / 1e6:.1f} ms in the future",
        )
    if now_ns > valid_ns:
        return None, f"JointIntent expired {(now_ns - valid_ns) / 1e6:.1f} ms ago"
    if len(message.joint_names) != len(set(message.joint_names)) or set(
        message.joint_names
    ) != set(joint_names):
        return (
            None,
            f"JointIntent must contain the exact configured joint set ({len(joint_names)} joints)",
        )
    if len(message.positions) != len(message.joint_names) or not all(
        math.isfinite(value) for value in message.positions
    ):
        return None, "JointIntent positions are malformed or non-finite"
    values = dict(zip(message.joint_names, message.positions))
    for name, value in values.items():
        lower, upper = limits[name]
        if not lower <= value <= upper:
            return None, f"JointIntent position violates {name} limits"
    return values, ""


class JointIntentBridge(Node):
    """Configuration-driven adapter from canonical JointIntent to robot controllers."""

    def __init__(self) -> None:
        super().__init__("joint_intent_bridge")
        self.declare_parameter("robot_config", "")
        self.declare_parameter("future_tolerance_ms", 0)
        config_path = Path(str(self.get_parameter("robot_config").value))
        if not str(config_path) or not config_path.is_file():
            raise ValueError("robot_config must name a readable robot-config/v1 file")
        self.robot = load_robot_config(config_path)
        self.target_id = str(self.robot["target_id"])
        self.joint_names = [joint["name"] for joint in self.robot["joints"]]
        self.limits = {
            joint["name"]: (float(joint["lower"]), float(joint["upper"]))
            for joint in self.robot["joints"]
        }
        self.groups = self.robot["command_adapter"]["groups"]
        self.trajectory_publishers = {}
        self.gripper_clients = {}
        self.last_gripper: dict[str, float] = {}
        for group in self.groups:
            if group["transport"] == "joint_trajectory_topic":
                self.trajectory_publishers[group["name"]] = self.create_publisher(
                    JointTrajectory, group["endpoint"], 10
                )
            elif group["transport"] in {"gripper_action", "parallel_gripper_action"}:
                if len(group["joints"]) != 1:
                    raise ValueError("gripper action groups require exactly one joint")
                action_type = (
                    ParallelGripperCommand
                    if group["transport"] == "parallel_gripper_action"
                    else GripperCommand
                )
                self.gripper_clients[group["name"]] = ActionClient(
                    self, action_type, group["endpoint"]
                )
        self.rejection_pub = self.create_publisher(
            CommandRejection, "/platform/control/command_rejections", 10
        )
        self.subscription = self.create_subscription(
            JointIntent, self.robot["action"]["topic"], self.on_intent, 50
        )
        self.future_tolerance_ns = (
            int(self.get_parameter("future_tolerance_ms").value) * 1_000_000
        )
        if not 0 <= self.future_tolerance_ns <= 20_000_000:
            raise ValueError("future_tolerance_ms must be between 0 and 20")
        self.rejected = 0
        self.get_logger().info(
            f"loaded robot adapter {self.robot['id']} with {len(self.joint_names)} joints"
        )

    def on_intent(self, message: JointIntent) -> None:
        now_ns = self.get_clock().now().nanoseconds
        values, reason = validate_joint_intent(
            message,
            now_ns,
            self.target_id,
            self.joint_names,
            self.limits,
            self.future_tolerance_ns,
        )
        if values is None:
            self.reject(message, reason)
            return
        for group in self.groups:
            if group["transport"] not in {"gripper_action", "parallel_gripper_action"}:
                continue
            name = group["name"]
            value = values[group["joints"][0]]
            changed = (
                name not in self.last_gripper
                or abs(value - self.last_gripper[name]) > 1e-4
            )
            if changed and not self.gripper_clients[name].server_is_ready():
                self.reject(message, f"{name} action server is unavailable")
                return

        for group in self.groups:
            name = group["name"]
            if group["transport"] == "joint_trajectory_topic":
                trajectory = JointTrajectory()
                trajectory.header.stamp = self.get_clock().now().to_msg()
                trajectory.joint_names = list(group["joints"])
                point = JointTrajectoryPoint()
                point.positions = [values[joint] for joint in trajectory.joint_names]
                duration_ms = int(group.get("duration_ms", 40))
                point.time_from_start.sec = duration_ms // 1000
                point.time_from_start.nanosec = (duration_ms % 1000) * 1_000_000
                trajectory.points.append(point)
                self.trajectory_publishers[name].publish(trajectory)
            elif group["transport"] in {"gripper_action", "parallel_gripper_action"}:
                joint = group["joints"][0]
                value = values[joint]
                if (
                    name in self.last_gripper
                    and abs(value - self.last_gripper[name]) <= 1e-4
                ):
                    continue
                if group["transport"] == "parallel_gripper_action":
                    goal = ParallelGripperCommand.Goal()
                    goal.command.name = [joint]
                    goal.command.position = [value]
                    goal.command.effort = [float(group.get("max_effort", 10.0))]
                else:
                    goal = GripperCommand.Goal()
                    goal.command.position = value
                    goal.command.max_effort = float(group.get("max_effort", 10.0))
                future = self.gripper_clients[name].send_goal_async(goal)
                future.add_done_callback(
                    lambda completed, original=message, group_name=name: (
                        self._gripper_response(completed, original, group_name)
                    )
                )
                self.last_gripper[name] = value

    def _gripper_response(self, future, original: JointIntent, group_name: str) -> None:
        try:
            if not future.result().accepted:
                self.reject(original, f"{group_name} controller rejected command")
        except Exception as error:
            self.reject(original, f"{group_name} action failed: {error}")

    def reject(self, original: JointIntent, reason: str) -> None:
        self.rejected += 1
        rejection = CommandRejection()
        rejection.header.stamp = self.get_clock().now().to_msg()
        rejection.rejection_id.uuid = list(uuid.uuid4().bytes)
        rejection.command_id = original.command_id
        rejection.source_id = f"{self.robot['id']}.joint_intent_bridge"
        rejection.target_id = self.target_id
        rejection.reason_code = 1
        rejection.reason = reason[:256]
        self.rejection_pub.publish(rejection)
        self.get_logger().error(f"rejected JointIntent: {reason}")


def main() -> None:
    rclpy.init()
    node = JointIntentBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
