"""ROS-independent source selection and handover state."""
# flake8: noqa: Q000

from __future__ import annotations

import math


def is_fresh(issued_ns: int, now_ns: int, max_age_ns: int) -> bool:
    return issued_ns > 0 and max_age_ns > 0 and 0 <= now_ns - issued_ns <= max_age_ns


def valid_intent_time(issued_ns: int, until_ns: int, now_ns: int) -> bool:
    return issued_ns > 0 and issued_ns <= now_ns <= until_ns


def smooth_handover(joint_names, positions, follower_positions, step):
    """Move at most step radians per joint from the latest simulated state."""
    return [
        follower_positions[name]
        + max(-step, min(step, value - follower_positions[name]))
        for name, value in zip(joint_names, positions)
    ]


class Arbitration:
    def __init__(
        self,
        sources: tuple[str, ...],
        active_source: str,
        joint_names: tuple[str, ...],
        max_handover_jump_rad: float,
        source_timeout_ns: int,
    ) -> None:
        self.sources = frozenset(sources)
        if active_source != "none" and active_source not in self.sources:
            raise ValueError(f"unknown source: {active_source}")
        if not joint_names or len(set(joint_names)) != len(joint_names):
            raise ValueError("joint_names must be non-empty and unique")
        if not math.isfinite(max_handover_jump_rad) or max_handover_jump_rad < 0:
            raise ValueError("max_handover_jump_rad must be finite and non-negative")
        if source_timeout_ns <= 0:
            raise ValueError("source_timeout_ns must be positive")

        self.active_source = active_source
        self.joint_names = tuple(joint_names)
        self.max_handover_jump_rad = max_handover_jump_rad
        self.source_timeout_ns = source_timeout_ns
        self.armed = False
        self.last_active_input_ns: int | None = None

    def select_source(self, source: str) -> None:
        if source != "none" and source not in self.sources:
            raise ValueError(f"unknown source: {source}")
        if source != self.active_source:
            self.active_source = source
            self.armed = False
            self.last_active_input_ns = None

    def accept_intent(
        self,
        source: str,
        joint_names: tuple[str, ...],
        positions: tuple[float, ...],
        now_ns: int,
        follower_positions: dict[str, float],
    ) -> bool:
        if source != self.active_source or source == "none":
            return False

        if (
            len(joint_names) != len(self.joint_names)
            or len(joint_names) != len(positions)
            or len(set(joint_names)) != len(joint_names)
            or set(joint_names) != set(self.joint_names)
        ):
            return False
        if set(follower_positions) != set(self.joint_names):
            return False

        candidate = dict(zip(joint_names, positions))
        if any(not math.isfinite(value) for value in candidate.values()):
            return False
        self.last_active_input_ns = now_ns
        if self.armed:
            return True
        if any(not math.isfinite(value) for value in follower_positions.values()):
            return False
        if any(
            abs(candidate[name] - follower_positions[name]) > self.max_handover_jump_rad
            for name in self.joint_names
        ):
            return False

        self.armed = True
        return True

    def check_watchdog(self, now_ns: int) -> bool:
        """Return true once when an active source times out."""
        if self.last_active_input_ns is None:
            return False
        if now_ns - self.last_active_input_ns <= self.source_timeout_ns:
            return False

        self.last_active_input_ns = None
        self.armed = False
        return True
