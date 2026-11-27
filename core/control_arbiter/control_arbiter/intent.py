"""Shared builder for time-bounded platform joint intents."""
# flake8: noqa: Q000

from __future__ import annotations

import uuid

from platform_control_interfaces.msg import JointIntent


def build_joint_intent(
    joint_names: list[str],
    positions: list[float],
    stamp,
    source_id: str,
    target_id: str,
    validity_ms: int = 80,
) -> JointIntent:
    if not 1 <= validity_ms <= 100:
        raise ValueError("validity_ms must be between 1 and 100")
    if len(joint_names) != len(positions):
        raise ValueError("joint_names and positions must have equal lengths")

    message = JointIntent()
    message.command_id.uuid = list(uuid.uuid4().bytes)
    message.lease_id.uuid = list(uuid.uuid4().bytes)
    message.source_id = source_id
    message.target_id = target_id
    message.issued_at = stamp
    message.valid_until = type(stamp)(
        sec=stamp.sec + (stamp.nanosec + validity_ms * 1_000_000) // 1_000_000_000,
        nanosec=(stamp.nanosec + validity_ms * 1_000_000) % 1_000_000_000,
    )
    message.joint_names = joint_names
    message.positions = positions
    return message
