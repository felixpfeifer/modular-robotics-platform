"""ROS node: moves the simulated leader with motion_planner while the arbiter has teleop active.

In a multi-arm cell one instance runs per mock leader; MOCK_MOTION_STATE_TOPIC (the follower it
tracks) and MOCK_MOTION_COMMAND_TOPIC (the leader's position controller) point it at its pair.
"""

import os

import motion_planner as mp
import rclpy
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray, String

JOINTS = [
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_flex_joint",
    "wrist_flex_joint",
    "wrist_roll_joint",
    "gripper_joint",
]
RATE_HZ = 50.0

planner = mp.MotionPlanner(
    seed=int(os.environ.get("MOCK_MOTION_SEED", "0")),
    speed=float(os.environ.get("MOCK_MOTION_SPEED", "1.0")),
    mode=os.environ.get("MOCK_MOTION_MODE", "waypoints"),
)
rclpy.init()
node = rclpy.create_node(os.environ.get("MOCK_MOTION_NODE", "mock_leader_motion"))
follower = list(mp.ZERO)
teleop = {"on": False}


def on_state(message):
    positions = dict(zip(message.name, message.position))
    if all(name in positions for name in JOINTS):
        follower[:] = [positions[name] for name in JOINTS]


def on_active(message):
    teleop["on"] = message.data == "teleop"


latched = QoSProfile(
    depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL
)
node.create_subscription(
    JointState, os.environ.get("MOCK_MOTION_STATE_TOPIC", "/joint_states"), on_state, qos_profile_sensor_data
)
node.create_subscription(String, "/platform/control/active_source", on_active, latched)
publisher = node.create_publisher(
    Float64MultiArray,
    os.environ.get("MOCK_MOTION_COMMAND_TOPIC", "/leader/forward_position_controller/commands"),
    10,
)


def tick():
    message = Float64MultiArray()
    message.data = planner.step(1.0 / RATE_HZ, teleop["on"], follower)
    publisher.publish(message)


node.create_timer(1.0 / RATE_HZ, tick)
try:
    rclpy.spin(node)
finally:
    node.destroy_node()
    rclpy.shutdown()
