import pytest
from platform_common_interfaces.msg import ComponentIdentity
from platform_control_interfaces.msg import JointIntent, SafetyEvent, TeleopState
from platform_episode_interfaces.msg import EpisodeMetadata
from rclpy.serialization import deserialize_message, serialize_message


def serialized_round_trip(message):
    return deserialize_message(serialize_message(message), type(message))


def enforce_generated_bound(message, field):
    """Test-only publish guard driven by generated ROS slot metadata."""
    index = message.__slots__.index(f"_{field}")
    slot_type = message.SLOT_TYPES[index]
    value = getattr(message, field)
    maximum_size = getattr(slot_type, "maximum_size", None)
    if maximum_size is not None and len(value) > maximum_size:
        raise ValueError(f"{type(message).__name__}.{field} exceeds {maximum_size}")
    element_type = getattr(slot_type, "value_type", None)
    element_maximum = getattr(element_type, "maximum_size", None)
    if element_maximum is not None:
        for item in value:
            if len(item) > element_maximum:
                raise ValueError(
                    f"{type(message).__name__}.{field} element exceeds {element_maximum}"
                )


@pytest.mark.parametrize(
    ("message_type", "field", "limit"),
    [
        (ComponentIdentity, "component_id", 64),
        (ComponentIdentity, "semantic_version", 32),
        (TeleopState, "source_id", 64),
        (SafetyEvent, "summary", 256),
        (SafetyEvent, "detail", 1024),
    ],
)
def test_bounded_strings_accept_limit_and_reject_one_over(message_type, field, limit):
    message = message_type()
    value = "x" * limit
    setattr(message, field, value)
    enforce_generated_bound(message, field)
    result = serialized_round_trip(message)
    assert getattr(result, field) == value
    setattr(message, field, "x" * (limit + 1))
    with pytest.raises(ValueError, match=field):
        enforce_generated_bound(message, field)


def test_bounded_joint_sequences_accept_32_and_reject_33():
    message = JointIntent()
    message.joint_names = [f"joint_{index}" for index in range(32)]
    message.positions = [float(index) for index in range(32)]
    enforce_generated_bound(message, "joint_names")
    enforce_generated_bound(message, "positions")
    result = serialized_round_trip(message)
    assert len(result.joint_names) == 32
    assert len(result.positions) == 32
    message.joint_names = [f"joint_{index}" for index in range(33)]
    message.positions = [float(index) for index in range(33)]
    with pytest.raises(ValueError, match="joint_names"):
        enforce_generated_bound(message, "joint_names")
    with pytest.raises(ValueError, match="positions"):
        enforce_generated_bound(message, "positions")


def test_bounded_nested_sequences_accept_32_and_reject_33():
    message = EpisodeMetadata()
    message.calibration_ids = [f"cal-{index}" for index in range(32)]
    enforce_generated_bound(message, "calibration_ids")
    assert len(serialized_round_trip(message).calibration_ids) == 32
    message.calibration_ids = [f"cal-{index}" for index in range(33)]
    with pytest.raises(ValueError, match="calibration_ids"):
        enforce_generated_bound(message, "calibration_ids")
