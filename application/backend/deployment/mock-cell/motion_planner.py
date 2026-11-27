"""Mock leader motion that always hands over cleanly to the control arbiter.

The arbiter only accepts the first teleop intent when every leader joint is within the handover
jump of the follower. So the planner mirrors the follower while teleop is off, holds that pose for
ARM_SECONDS after teleop is enabled, and only then moves away. Pure Python (no ROS) so it can be
tested against the real arbitration logic.
"""

import math
import random

ZERO = [0.0] * 6
LIMITS = [(-1.91986, 1.91986), (-1.74533, 1.74533), (-1.69, 1.54), (-1.6, 1.6), (-2.3, 2.3), (0.0, 1.70)]
ARM_SECONDS = 1.0  # real seconds the leader holds the follower's pose after teleop is enabled
LEG_SECONDS = 2.5  # waypoints mode: seconds per move at speed 1.0
MARGIN = 0.25  # fraction of each joint's range kept clear of the limits


def clamp(pose):
    return [min(max(float(v), lo), hi) for v, (lo, hi) in zip(pose, LIMITS)]


def _smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


class MotionPlanner:
    def __init__(self, seed=0, speed=1.0, mode="waypoints"):
        if mode not in ("waypoints", "sine"):
            raise ValueError("mode must be waypoints or sine")
        self.speed = max(0.05, float(speed))
        self.mode = mode
        self.rng = random.Random(int(seed))
        self.state_time = 0.0
        self.output = list(ZERO)
        self.was_active = False
        self.start = list(ZERO)
        self.leg_from = list(ZERO)
        self.leg_to = list(ZERO)
        self.leg = 0.0
        self.phases = [self.rng.uniform(0, 2 * math.pi) for _ in ZERO]

    def _target(self):
        return [lo + (hi - lo) * (MARGIN + (1 - 2 * MARGIN) * self.rng.random()) for lo, hi in LIMITS]

    def step(self, dt, teleop_active, follower=None):
        follower = clamp(follower if follower is not None else ZERO)
        if not teleop_active:
            self.was_active = False
            self.output = follower  # mirror: the leader is always where the follower is
            return list(self.output)
        if not self.was_active:  # teleop just enabled: start again from the follower's pose
            self.was_active = True
            self.state_time = 0.0
            self.start = list(follower)
            self.leg_from, self.leg_to, self.leg = list(follower), self._target(), 0.0
        self.state_time += dt
        moving = self.state_time - ARM_SECONDS
        if moving <= 0:
            self.output = list(self.start)
            return list(self.output)
        virtual = dt * self.speed
        if self.mode == "sine":
            ramp = _smooth(moving * self.speed / 2.0)  # fade the motion in, no jump at the start
            t = moving * self.speed
            pose = [
                s
                + ramp * 0.45 * (hi - lo) / 2 * math.sin(t * (0.5 + 0.12 * i) + p)
                - ramp * 0.45 * (hi - lo) / 2 * math.sin(p)
                for i, (s, (lo, hi), p) in enumerate(zip(self.start, LIMITS, self.phases))
            ]
        else:
            self.leg += virtual / LEG_SECONDS
            if self.leg >= 1.0:
                self.leg_from, self.leg_to, self.leg = self.leg_to, self._target(), self.leg - 1.0
            k = _smooth(self.leg)
            pose = [a + (b - a) * k for a, b in zip(self.leg_from, self.leg_to)]
        self.output = clamp(pose)
        return list(self.output)
