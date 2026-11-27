from control_arbiter.policy_validation import validate_action
import pytest


def test_action_rejects_limits_and_invalid_numbers():
    state = [0.0] * 6
    assert validate_action(state, state, 0.15) == state
    for value in ([0.16, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, -0.01], [float('nan')] * 6):
        with pytest.raises(ValueError):
            validate_action(value, state, 0.15)
