import math
import os
import subprocess
import time

import rclpy
from platform_control_interfaces.msg import TeleopState
from rclpy.impl.implementation_singleton import rclpy_implementation


def wait_for(predicate, node, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.05)
        if predicate():
            return True
    return False


def test_cpp_to_python_round_trip():
    assert os.environ["RMW_IMPLEMENTATION"] == "rmw_cyclonedds_cpp"
    assert (
        rclpy_implementation.rclpy_get_rmw_implementation_identifier()
        == "rmw_cyclonedds_cpp"
    )
    rclpy.init()
    node = rclpy.create_node("teleop_python_fixture_subscriber")
    received = []
    node.create_subscription(
        TeleopState,
        "/platform_interface_tests/teleop_cpp_to_python",
        received.append,
        10,
    )
    process = subprocess.Popen(
        ["ros2", "run", "platform_interface_transport_tests", "teleop_cpp_publisher"]
    )
    try:
        assert wait_for(lambda: received, node)
        message = received[0]
        assert message.header.stamp.sec == 123
        assert message.header.stamp.nanosec == 456
        assert message.header.frame_id == "world"
        assert list(message.sample_id.uuid) == list(range(1, 17))
        assert message.source_id == "cpp_source"
        assert math.isclose(message.pose.position.x, 1.25)
        assert math.isclose(message.pose.position.y, -2.5)
        assert math.isclose(message.pose.position.z, 0.75)
        assert math.isclose(message.velocity.linear.x, 0.4)
        assert math.isclose(message.velocity.angular.z, -0.3)
        assert math.isclose(message.gripper_position, 0.625)
        assert message.buttons == 0xA5
        assert message.clutch_engaged
        assert message.tracking_valid and message.pose_valid and message.velocity_valid
    finally:
        process.terminate()
        process.wait(timeout=5)
        node.destroy_node()
        rclpy.shutdown()


def test_python_to_cpp_round_trip():
    rclpy.init()
    node = rclpy.create_node("teleop_python_fixture_publisher")
    publisher = node.create_publisher(
        TeleopState, "/platform_interface_tests/teleop_python_to_cpp", 10
    )
    process = subprocess.Popen(
        ["ros2", "run", "platform_interface_transport_tests", "teleop_cpp_subscriber"]
    )
    message = TeleopState()
    message.header.stamp.sec = 321
    message.header.stamp.nanosec = 654
    message.header.frame_id = "base"
    message.sample_id.uuid = list(range(16, 0, -1))
    message.source_id = "python_source"
    message.pose.position.x = -1.5
    message.pose.orientation.w = 1.0
    message.velocity.linear.y = 0.75
    message.velocity.angular.z = -0.25
    message.gripper_position = 0.375
    message.buttons = 0x5A
    message.clutch_engaged = False
    message.tracking_valid = True
    message.pose_valid = True
    message.velocity_valid = True
    try:
        deadline = time.monotonic() + 5
        while process.poll() is None and time.monotonic() < deadline:
            publisher.publish(message)
            rclpy.spin_once(node, timeout_sec=0.05)
        assert process.wait(timeout=2) == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        node.destroy_node()
        rclpy.shutdown()
