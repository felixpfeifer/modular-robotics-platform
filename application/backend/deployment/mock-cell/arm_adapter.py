"""ROS node: present the arms of a multi-arm cell as one combined robot (see arm_merge.py).

* follower states ``/arm_<id>/joint_states`` -> ``/joint_states`` (prefixed joints)
* leader states  ``/arm_<id>/joint_states`` -> ``/leader/joint_states``
* the arbiter's combined ``/platform/control/joint_intent`` -> one JointIntent per follower on
  ``/platform/control/arms/<id>/joint_intent``, which that follower's own bridge executes.

    arm_adapter.py /workspace/config/mock-so101/arms.json
"""

import json
import sys

import arm_merge
import rclpy
from platform_control_interfaces.msg import CommandRejection, JointIntent
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import JointState

config = arm_merge.load(json.loads(open(sys.argv[1], encoding="utf-8").read()))
rclpy.init()
node = rclpy.create_node("arm_adapter")
log = node.get_logger()


def now_ns():
    return node.get_clock().now().nanoseconds


def merger_node(arms, topic):
    merger = arm_merge.StateMerger(arms)
    publisher = node.create_publisher(JointState, topic, 10)

    def on_state(arm_id):
        def callback(message):
            merged = merger.update(
                arm_id, message.name, message.position, message.velocity, message.effort, now_ns()
            )
            if merged is None:
                return
            out = JointState()
            out.header.stamp = message.header.stamp
            out.name, out.position, out.velocity, out.effort = merged
            publisher.publish(out)

        return callback

    for arm in arms:
        node.create_subscription(JointState, arm["state_topic"], on_state(arm["id"]), qos_profile_sensor_data)


merger_node(config["followers"], config["merged_state_topic"])
merger_node(config["leaders"], config["merged_leader_topic"])
intents = {
    follower["id"]: node.create_publisher(JointIntent, follower["intent_topic"], 50)
    for follower in config["followers"]
}
rejections = node.create_publisher(CommandRejection, "/platform/control/command_rejections", 10)


def reject(message, reason):
    rejection = CommandRejection()
    rejection.header.stamp = node.get_clock().now().to_msg()
    rejection.command_id = message.command_id
    rejection.source_id = message.source_id
    rejection.target_id = message.target_id
    rejection.reason = reason[:256]
    rejections.publish(rejection)
    log.warning(f"rejected combined intent: {reason}")


def on_intent(message):
    if message.target_id != config["target_id"]:
        return reject(message, f"target_id must be {config['target_id']}")
    try:
        parts = arm_merge.split_intent(
            list(message.joint_names), list(message.positions), list(message.velocities), config["followers"]
        )
    except ValueError as error:
        return reject(message, str(error))
    for follower, names, positions, velocities in parts:
        out = JointIntent()
        out.command_id, out.lease_id, out.source_id = message.command_id, message.lease_id, message.source_id
        out.target_id = follower["target_id"]
        out.issued_at, out.valid_until = message.issued_at, message.valid_until
        out.joint_names, out.positions, out.velocities = names, positions, velocities
        intents[follower["id"]].publish(out)


node.create_subscription(JointIntent, config["intent_topic"], on_intent, 50)
log.info(
    f"arm adapter: {len(config['followers'])} followers, {len(config['leaders'])} leaders -> {config['target_id']}"
)
try:
    rclpy.spin(node)
finally:
    node.destroy_node()
