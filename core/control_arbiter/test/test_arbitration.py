# flake8: noqa: Q000
from control_arbiter.arbitration import Arbitration, is_fresh, valid_intent_time
import pytest


JOINTS = ("j1", "j2")
POSE = {"j1": 0.0, "j2": 0.0}


def make_arbiter(active_source="none", tolerance=0.15):
    return Arbitration(("teleop", "policy"), active_source, JOINTS, tolerance, 200)


def test_source_switch_rearms_gate_and_rejects_unknown_source():
    arbiter = make_arbiter("teleop")
    arbiter.armed = True

    arbiter.select_source("policy")
    assert arbiter.active_source == "policy"
    assert not arbiter.armed
    with pytest.raises(ValueError, match="unknown source"):
        arbiter.select_source("unknown")


def test_handover_requires_all_joints_within_tolerance():
    arbiter = make_arbiter("teleop")

    assert not arbiter.accept_intent("teleop", JOINTS, (0.0, 0.2), 1, POSE)
    assert not arbiter.armed
    assert not arbiter.accept_intent("teleop", ("j1", "j1"), (0.0, 0.0), 2, POSE)
    assert not arbiter.armed
    assert arbiter.accept_intent("teleop", JOINTS, (0.1, -0.15), 3, POSE)
    assert arbiter.armed
    assert not arbiter.accept_intent("policy", JOINTS, (0.0, 0.0), 4, POSE)


def test_handover_waits_for_a_complete_follower_pose_and_finite_values():
    arbiter = make_arbiter("teleop")

    assert not arbiter.accept_intent("teleop", JOINTS, (0.0, 0.0), 1, {"j1": 0.0})
    assert not arbiter.accept_intent("teleop", JOINTS, (float("nan"), 0.0), 2, POSE)
    assert not arbiter.accept_intent("teleop", ("j1",), (0.0,), 3, POSE)
    assert arbiter.accept_intent("teleop", JOINTS, (0.0, 0.0), 4, POSE)


def test_watchdog_times_out_once_and_rearms_handover():
    arbiter = make_arbiter("teleop")
    assert arbiter.accept_intent("teleop", JOINTS, (0.0, 0.0), 100, POSE)

    assert not arbiter.check_watchdog(300)
    assert arbiter.check_watchdog(301)
    assert not arbiter.armed
    assert not arbiter.check_watchdog(500)
    assert not arbiter.accept_intent("teleop", JOINTS, (0.3, 0.0), 501, POSE)
    assert arbiter.accept_intent("teleop", JOINTS, (0.0, 0.0), 502, POSE)


def test_none_does_not_forward_or_timeout():
    arbiter = make_arbiter()
    assert not arbiter.accept_intent("teleop", JOINTS, (0.0, 0.0), 1, POSE)
    assert not arbiter.check_watchdog(10_000)


def test_armed_source_rejects_malformed_commands_and_stale_state():
    arbiter = make_arbiter("teleop")
    assert arbiter.accept_intent("teleop", JOINTS, (0.0, 0.0), 100, POSE)
    assert not arbiter.accept_intent("teleop", JOINTS, (float("nan"), 0.0), 150, POSE)
    assert not arbiter.accept_intent("teleop", ("j1",), (0.0,), 180, POSE)
    assert not arbiter.accept_intent("teleop", JOINTS, (0.0, 0.0), 200, {})
    assert arbiter.check_watchdog(301)
    assert not arbiter.armed


def test_source_timestamps_reject_zero_future_stale_and_expired():
    assert is_fresh(100, 200, 100)
    assert not is_fresh(0, 200, 200)
    assert not is_fresh(201, 200, 100)
    assert not is_fresh(99, 200, 100)
    assert valid_intent_time(100, 200, 150)
    assert not valid_intent_time(100, 200, 201)
    assert not valid_intent_time(100, 200, 99)


def test_smooth_handover_limits_each_joint_step():
    from control_arbiter.arbitration import smooth_handover

    assert smooth_handover(("a", "b"), (2.0, -1.0), {"a": 0.0, "b": 0.2}, 0.01) == [
        0.01,
        0.19,
    ]
    assert smooth_handover(("a",), (0.005,), {"a": 0.0}, 0.01) == [0.005]
