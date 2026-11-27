"""Bounded LeRobot inference contract shared by the policy client and server."""

import base64
import binascii
import math
import uuid

JOINTS = (
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_flex_joint",
    "wrist_flex_joint",
    "wrist_roll_joint",
    "gripper_joint",
)
LIMITS = (
    (-1.91986, 1.91986),
    (-1.74533, 1.74533),
    (-1.69, 1.54),
    (-1.6, 1.6),
    (-2.3, 2.3),
    (0.0, 1.70),
)
MAX_IMAGE_BYTES = 2 * 1024 * 1024


def vector(value):
    if not isinstance(value, list) or len(value) != len(JOINTS):
        raise ValueError("Expected exactly six joint positions.")
    if any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        or not math.isfinite(item)
        for item in value
    ):
        raise ValueError("Joint positions must be finite numbers.")
    return [float(item) for item in value]


def observation(body):
    if not isinstance(body, dict) or set(body) != {
        "request_id",
        "image_stamp_ns",
        "state",
        "image_jpeg",
    }:
        raise ValueError("Unexpected observation fields.")
    try:
        if str(uuid.UUID(body["request_id"])) != body["request_id"]:
            raise ValueError("Noncanonical request ID.")
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Request ID must be a canonical UUID.") from exc
    if type(body["image_stamp_ns"]) is not int or body["image_stamp_ns"] <= 0:
        raise ValueError("Invalid camera timestamp.")
    state = vector(body["state"])
    if not isinstance(body["image_jpeg"], str) or len(body["image_jpeg"]) > (
        MAX_IMAGE_BYTES * 4 // 3 + 8
    ):
        raise ValueError("Image exceeds the configured size limit.")
    try:
        image = base64.b64decode(body["image_jpeg"], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Image is not valid base64.") from exc
    if not image or len(image) > MAX_IMAGE_BYTES:
        raise ValueError("Invalid JPEG size.")
    return state, image


def safe_action(values, current, max_delta):
    action = vector(values)
    current = vector(current)
    if not 0 < max_delta <= 0.15:
        raise ValueError("Maximum action delta must be in (0, 0.15] radians.")
    for index, (target, present, limits) in enumerate(
        zip(action, current, LIMITS, strict=True)
    ):
        if not limits[0] <= target <= limits[1]:
            raise ValueError(f"Action violates {JOINTS[index]} limits.")
        if abs(target - present) > max_delta:
            raise ValueError(f"Action exceeds {JOINTS[index]} per-step tolerance.")
    return action
