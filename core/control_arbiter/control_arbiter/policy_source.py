"""Build fresh policy observations from ROS topics and publish bounded intents."""

import base64
from concurrent.futures import ThreadPoolExecutor
import json
import urllib.request
import uuid

from control_arbiter.arbitration import is_fresh
from control_arbiter.intent import build_joint_intent
from control_arbiter.policy_validation import validate_action
from control_arbiter.teleop_source import ordered_positions
from platform_control_interfaces.msg import JointIntent
import rclpy
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    qos_profile_sensor_data,
    QoSProfile,
    ReliabilityPolicy,
)
from sensor_msgs.msg import CompressedImage, JointState
from std_msgs.msg import String

JOINTS = [
    'shoulder_pan_joint',
    'shoulder_lift_joint',
    'elbow_flex_joint',
    'wrist_flex_joint',
    'wrist_roll_joint',
    'gripper_joint',
]


def stamp_ns(stamp):
    return stamp.sec * 1_000_000_000 + stamp.nanosec


def post(url, path, body, timeout):
    data = json.dumps(body).encode()
    request = urllib.request.Request(
        url + path, data=data, headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read(65536))


class PolicySource(Node):
    def __init__(self):
        super().__init__('policy_source')
        defaults = {
            'server_url': 'http://127.0.0.1:8092',
            'joint_states_topic': '/joint_states',
            'camera_topic': '/image/compressed',
            'target_id': 'so101',
            'max_age_ms': 150,
            'max_skew_ms': 25,
            'max_delta_rad': 0.15,
            'request_timeout_ms': 150,
            'rate_hz': 10.0,
            'validity_ms': 80,
        }
        for key, value in defaults.items():
            self.declare_parameter(key, value)
        self.url = str(self.get_parameter('server_url').value).rstrip('/')
        self.target = str(self.get_parameter('target_id').value)
        self.max_age = int(self.get_parameter('max_age_ms').value) * 1_000_000
        self.max_skew = int(self.get_parameter('max_skew_ms').value) * 1_000_000
        self.max_delta = float(self.get_parameter('max_delta_rad').value)
        self.timeout = int(self.get_parameter('request_timeout_ms').value) / 1000
        self.validity = int(self.get_parameter('validity_ms').value)
        rate = float(self.get_parameter('rate_hz').value)
        if (
            self.max_age <= 0
            or self.max_skew < 0
            or not 0 < self.max_delta <= 0.15
            or self.timeout <= 0
            or rate <= 0
            or not 1 <= self.validity <= 100
        ):
            raise ValueError('invalid policy source limits')
        self.active = False
        self.generation = 0
        self.state = self.image = None
        self.pending = None
        self.needs_reset = True
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.publisher = self.create_publisher(
            JointIntent, '/platform/control/sources/policy/joint_intent', 10
        )
        self.create_subscription(
            JointState,
            str(self.get_parameter('joint_states_topic').value),
            self.on_state,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            CompressedImage,
            str(self.get_parameter('camera_topic').value),
            self.on_image,
            qos_profile_sensor_data,
        )
        qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.create_subscription(
            String, '/platform/control/active_source', self.on_active, qos
        )
        self.create_timer(1.0 / rate, self.tick)

    def on_active(self, message):
        active = message.data == 'policy'
        if active != self.active:
            self.active = active
            self.generation += 1
            self.needs_reset = True

    def on_state(self, message):
        positions = ordered_positions(message.name, message.position, JOINTS)
        if positions is not None:
            self.state = (stamp_ns(message.header.stamp), positions)

    def on_image(self, message):
        if (
            message.data
            and len(message.data) <= 2 * 1024 * 1024
            and 'jpeg' in message.format.lower()
        ):
            self.image = (stamp_ns(message.header.stamp), bytes(message.data))

    def fresh(self, stamp):
        return is_fresh(stamp, self.get_clock().now().nanoseconds, self.max_age)

    def tick(self):
        if self.pending and self.pending[0].done():
            future, kind, generation, request_id, image_stamp = self.pending
            self.pending = None
            try:
                result = future.result()
                if generation != self.generation or not self.active:
                    return
                if kind == 'reset':
                    if result != {'reset': True}:
                        raise ValueError('invalid reset response')
                    self.needs_reset = False
                else:
                    if (
                        result.get('request_id') != request_id
                        or result.get('image_stamp_ns') != image_stamp
                    ):
                        raise ValueError('mismatched response')
                    if (
                        not self.state
                        or not self.fresh(self.state[0])
                        or not self.fresh(image_stamp)
                    ):
                        raise ValueError('stale inference result')
                    action = validate_action(
                        result['action'], self.state[1], self.max_delta
                    )
                    self.publisher.publish(
                        build_joint_intent(
                            JOINTS,
                            action,
                            self.get_clock().now().to_msg(),
                            'policy',
                            self.target,
                            self.validity,
                        )
                    )
            except Exception as exc:
                self.needs_reset = True
                self.get_logger().warning(f'Policy request rejected: {exc}')
        if not self.active or self.pending:
            return
        if self.needs_reset:
            self.pending = (
                self.executor.submit(post, self.url, '/reset', {}, self.timeout),
                'reset',
                self.generation,
                None,
                None,
            )
            return
        if (
            not self.state
            or not self.image
            or not self.fresh(self.state[0])
            or not self.fresh(self.image[0])
            or abs(self.state[0] - self.image[0]) > self.max_skew
        ):
            self.needs_reset = True
            return
        request_id = str(uuid.uuid4())
        image_stamp, image = self.image
        body = {
            'request_id': request_id,
            'image_stamp_ns': image_stamp,
            'state': self.state[1],
            'image_jpeg': base64.b64encode(image).decode('ascii'),
        }
        self.pending = (
            self.executor.submit(post, self.url, '/act', body, self.timeout),
            'act',
            self.generation,
            request_id,
            image_stamp,
        )


def main(args=None):
    rclpy.init(args=args)
    node = PolicySource()
    try:
        rclpy.spin(node)
    finally:
        node.executor.shutdown(wait=False, cancel_futures=True)
        node.destroy_node()
        rclpy.shutdown()
