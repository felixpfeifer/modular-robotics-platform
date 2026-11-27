from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from episode_recorder_py.configuration import load_recording_profile
from episode_recorder_py.export_lerobot import _action_at, _image_at, _state_at


def stamp(ns):
    return SimpleNamespace(sec=ns // 1_000_000_000, nanosec=ns % 1_000_000_000)


def test_slowest_camera_is_timeline():
    path = Path(__file__).resolve().parents[1] / "config/recording_profiles.yaml"
    assert (
        load_recording_profile(path, "so101_vla_sim_dual_v1")["timeline_camera"]
        == "wrist"
    )


def test_nearest_state_and_causal_action():
    states = [
        (0, t, SimpleNamespace(name=["joint"], position=[t])) for t in (100, 200, 300)
    ]
    state, source = _state_at(states, 180, ["joint"])
    assert (state.tolist(), source) == ([200], 200)
    actions = [
        (
            0,
            t,
            SimpleNamespace(
                issued_at=stamp(t),
                valid_until=stamp(t + 150),
                joint_names=["joint"],
                positions=[t],
            ),
        )
        for t in (100, 200, 300)
    ]
    action, source = _action_at(actions, 180, ["joint"])
    assert (action.tolist(), source) == ([100], 100)


def test_images_require_nearest_valid_frame_within_half_period():
    camera = {"fps": 30, "width": 8, "height": 8}
    visible = np.zeros((8, 8, 3), dtype=np.uint8)
    visible[:, 4:] = 200

    def sample(timestamp, image):
        ok, data = cv2.imencode(".jpg", image)
        assert ok
        return (timestamp, timestamp, SimpleNamespace(data=data.tobytes()))

    samples = [
        sample(1_000_000_000, visible),
        sample(1_033_333_333, np.zeros_like(visible)),
    ]
    times = [item[1] for item in samples]
    assert _image_at(samples, times, 1_001_000_000, camera) is not None
    assert _image_at(samples, times, 1_033_333_333, camera) is None
    assert _image_at(samples, times, 1_100_000_000, camera) is None
    assert _image_at([], [], 1_000_000_000, camera) is None
