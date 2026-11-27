import math

from platform_control_interfaces.msg import JointIntent

from episode_recorder_py.joint_intent_bridge import JOINTS, validate_joint_intent


def _message(now_ns: int) -> JointIntent:
    message = JointIntent()
    message.target_id = "so101"
    message.issued_at.sec = now_ns // 1_000_000_000
    message.issued_at.nanosec = now_ns % 1_000_000_000
    valid_ns = now_ns + 50_000_000
    message.valid_until.sec = valid_ns // 1_000_000_000
    message.valid_until.nanosec = valid_ns % 1_000_000_000
    message.joint_names = list(JOINTS)
    message.positions = [0.0, 0.0, 0.0, 0.0, 0.0, 0.8]
    return message


def test_bridge_accepts_exact_fresh_six_joint_intent():
    now_ns = 10_000_000_000
    values, reason = validate_joint_intent(_message(now_ns), now_ns, "so101")
    assert reason == ""
    assert values is not None and list(values) == JOINTS


def test_bridge_rejects_expired_duplicate_nonfinite_and_limit_violations():
    now_ns = 10_000_000_000
    expired = _message(now_ns)
    assert validate_joint_intent(expired, now_ns + 100_000_000, "so101")[0] is None

    duplicate = _message(now_ns)
    duplicate.joint_names[-1] = duplicate.joint_names[0]
    assert validate_joint_intent(duplicate, now_ns, "so101")[0] is None

    nonfinite = _message(now_ns)
    nonfinite.positions[0] = math.nan
    assert validate_joint_intent(nonfinite, now_ns, "so101")[0] is None

    outside = _message(now_ns)
    outside.positions[0] = 99.0
    values, reason = validate_joint_intent(outside, now_ns, "so101")
    assert values is None and "limits" in reason


def test_bridge_validation_accepts_an_arbitrary_robot_joint_contract():
    now_ns = 10_000_000_000
    message = _message(now_ns)
    message.target_id = "ur_cell_1"
    message.joint_names = ["axis_1", "axis_2", "axis_3"]
    message.positions = [0.2, -0.3, 0.4]
    names = ["axis_1", "axis_2", "axis_3"]
    limits = {name: (-1.0, 1.0) for name in names}
    values, reason = validate_joint_intent(message, now_ns, "ur_cell_1", names, limits)
    assert reason == ""
    assert values == {"axis_1": 0.2, "axis_2": -0.3, "axis_3": 0.4}


def test_bridge_tolerates_only_configured_future_skew_and_never_expiry():
    now_ns = 10_000_000_000
    ahead = _message(now_ns + 2_000_000)
    assert validate_joint_intent(ahead, now_ns, "so101")[0] is None
    assert (
        validate_joint_intent(ahead, now_ns, "so101", future_tolerance_ns=5_000_000)[0]
        is not None
    )
    assert (
        validate_joint_intent(
            _message(now_ns + 6_000_000), now_ns, "so101", future_tolerance_ns=5_000_000
        )[0]
        is None
    )
    assert (
        validate_joint_intent(
            _message(now_ns),
            now_ns + 100_000_000,
            "so101",
            future_tolerance_ns=5_000_000,
        )[0]
        is None
    )
