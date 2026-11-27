"""Validation of SO-101 policy output."""

import math

LIMITS = [
    (-1.91986, 1.91986),
    (-1.74533, 1.74533),
    (-1.69, 1.54),
    (-1.6, 1.6),
    (-2.3, 2.3),
    (0.0, 1.70),
]


def validate_action(action, state, max_delta):
    if not isinstance(action, list) or len(action) != 6:
        raise ValueError('expected six action values')
    for value, present, (low, high) in zip(action, state, LIMITS):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError('action must contain finite numbers')
        if not low <= value <= high or abs(value - present) > max_delta:
            raise ValueError('action outside joint limits or step tolerance')
    return [float(x) for x in action]
