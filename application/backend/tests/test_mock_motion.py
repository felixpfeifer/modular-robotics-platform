"""Closed-loop test of the mock leader against the control arbiter's real handover gate.

This is the check that was missing: unit tests of each part passed while the cell as a whole
never reached "Action ready", because a leader that drifts away on its own can never hand
over to a follower that only moves after the handover.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] if len(Path(__file__).resolve().parents) > 3 else None
if ROOT is None or not (ROOT / "core/control_arbiter").is_dir():
    raise unittest.SkipTest("MRP workspace not available")
sys.path[:0] = [str(ROOT / "core/control_arbiter"), str(ROOT / "application/backend/deployment/mock-cell")]
try:
    from control_arbiter.arbitration import Arbitration
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"control arbiter not importable: {exc}") from exc
import motion_planner as mp  # noqa: E402 - the workspace path is configured above

JOINTS = (
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_flex_joint",
    "wrist_flex_joint",
    "wrist_roll_joint",
    "gripper_joint",
)
DT = 0.02


class Cell:
    """Planner + real arbiter gate + a follower that moves only when intents are forwarded."""

    def __init__(self, planner, follower=None):
        self.planner = planner
        self.follower = list(follower or mp.ZERO)
        self.arbiter = Arbitration(("teleop",), "none", JOINTS, 0.15, 200_000_000)
        self.now = 1_000_000_000
        self.accepted = 0
        self.rejected = 0
        self.travel = 0.0
        self.first_accept = None
        self.t = 0.0

    def set_teleop(self, on):
        self.arbiter.select_source("teleop" if on else "none")
        self.teleop = on

    def run(self, seconds):
        steps = int(seconds / DT)
        for _ in range(steps):
            self.t += DT
            self.now += int(DT * 1e9)
            leader = self.planner.step(DT, self.teleop, self.follower)
            ok = self.arbiter.accept_intent(
                "teleop", JOINTS, tuple(leader), self.now, dict(zip(JOINTS, self.follower))
            )
            if ok:
                self.accepted += 1
                self.first_accept = self.first_accept if self.first_accept is not None else self.t
                self.travel += sum(abs(a - b) for a, b in zip(leader, self.follower))
                self.follower = list(leader)  # a mock follower tracks forwarded commands
            else:
                self.rejected += 1
            self.arbiter.check_watchdog(self.now)


class MockMotionHandoverTests(unittest.TestCase):
    def check_cell(self, mode, follower=None, seed=0, speed=1.0):
        cell = Cell(mp.MotionPlanner(seed=seed, speed=speed, mode=mode), follower)
        cell.set_teleop(True)
        cell.run(40)
        self.assertTrue(cell.arbiter.armed, f"{mode}: the handover gate never armed")
        self.assertLess(cell.first_accept, mp.ARM_SECONDS + 0.5, "hands over right after enabling teleop")
        self.assertEqual(cell.rejected, 0, "no intent is dropped after the first handover")
        self.assertGreater(cell.travel, 3.0, "the follower actually moves, so the data is useful")
        return cell

    def test_both_modes_hand_over_and_keep_moving_from_zero(self):
        for mode in ("waypoints", "sine"):
            with self.subTest(mode=mode):
                self.check_cell(mode)

    def test_hands_over_from_a_follower_that_is_not_at_zero(self):
        pose = [0.4, -0.3, 0.5, 0.2, -0.6, 0.8]
        for mode in ("waypoints", "sine"):
            with self.subTest(mode=mode):
                self.check_cell(mode, follower=pose)

    def test_settings_extremes_still_hand_over(self):
        for mode in ("waypoints", "sine"):
            for speed in (0.2, 1, 3):  # whole numbers are valid settings too
                with self.subTest(mode=mode, speed=speed):
                    self.check_cell(mode, speed=speed, seed=2**31 - 1)

    def test_commands_stay_inside_the_joint_limits(self):
        for mode in ("waypoints", "sine"):
            planner = mp.MotionPlanner(mode=mode)
            for _ in range(int(60 / DT)):
                pose = planner.step(DT, True, [0.0] * 6)
                for value, (low, high) in zip(pose, mp.LIMITS):
                    self.assertTrue(low <= value <= high, (mode, pose))

    def test_waits_for_teleop_and_mirrors_the_follower_meanwhile(self):
        planner = mp.MotionPlanner()
        follower = [0.1, 0.2, 0.3, 0.0, 0.0, 0.5]
        for _ in range(100):  # teleop off: never leaves the follower's pose
            self.assertEqual(planner.step(DT, False, follower), mp.clamp(follower))

    def test_disabling_and_reenabling_teleop_hands_over_again_at_the_new_pose(self):
        cell = Cell(mp.MotionPlanner(mode="sine"))
        cell.set_teleop(True)
        cell.run(15)
        self.assertTrue(cell.arbiter.armed)
        cell.set_teleop(False)  # the follower stays wherever it was
        cell.run(2)
        self.assertNotEqual(cell.follower, mp.ZERO)
        cell.set_teleop(True)
        before = cell.accepted
        cell.run(5)
        self.assertTrue(cell.arbiter.armed)
        self.assertGreater(cell.accepted, before)

    def test_a_leader_that_ignores_the_follower_never_hands_over(self):
        """Documents the original bug: drifting away from the follower prevents the handover."""

        class Drifting(mp.MotionPlanner):
            def step(self, dt, teleop_active, follower=None):
                self.output = mp.clamp([0.5 * min(1.0, self.state_time / 3)] * 6)  # drifts away, stays away
                self.state_time += dt
                return list(self.output)

        cell = Cell(Drifting())
        cell.set_teleop(False)
        cell.run(5)  # the leader has already drifted away when the operator enables teleop
        cell.set_teleop(True)
        cell.run(10)
        self.assertFalse(cell.arbiter.armed)
        self.assertEqual(cell.accepted, 0)  # "Action" would stay not ready forever


if __name__ == "__main__":
    unittest.main()
