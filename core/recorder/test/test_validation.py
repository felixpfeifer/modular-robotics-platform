import json
from pathlib import Path

import numpy as np

from episode_recorder_py.validation import (
    Finding,
    ValidationResult,
    camera_freeze,
    load_contract,
    sha256_file,
    write_junit,
)


ROOT = Path(__file__).parents[1]


def test_profile_and_task_catalog_are_compatible():
    profile, task = load_contract(
        ROOT / "config/recording_profiles.yaml",
        ROOT / "config/task_catalog.yaml",
        "so101_vla_rgb_30_v1",
        "default_demo",
    )
    assert profile["cameras"][0]["fps"] == 30.0
    assert len(profile["joints"]) == 6
    assert task["instruction"]


def test_sha256_is_algorithm_prefixed(tmp_path):
    artifact = tmp_path / "episode.mcap"
    artifact.write_bytes(b"immutable")
    assert (
        sha256_file(artifact)
        == "sha256:3e58bada6a180c0d7f817bdae51fba96a461575b309bfbc17a6918d20c6617c7"
    )


def test_junit_has_one_case_per_rule(tmp_path):
    result = ValidationResult("123e4567-e89b-42d3-a456-426614174000")
    result.findings = [
        Finding("storage.single_mcap", "info", "ok"),
        Finding("camera.decode", "fatal", "bad image"),
    ]
    output = tmp_path / "validation.xml"
    write_junit(output, result)
    text = output.read_text(encoding="utf-8")
    assert text.count("<testcase") == 2
    assert 'failures="1"' in text
    assert "camera.decode" in text


def test_validation_result_never_treats_warning_as_failure():
    result = ValidationResult("123e4567-e89b-42d3-a456-426614174000")
    result.add("camera.blur_baseline", False, "advisory", "warning")
    assert result.valid
    assert json.loads(json.dumps(result.findings[0].__dict__))["severity"] == "warning"


def test_freeze_detection_accepts_accumulating_small_visible_motion():
    frames = []
    for index in range(70):
        frame = np.zeros((200, 200, 3), dtype=np.uint8)
        frame[35:65, 10 + index : 30 + index] = 255
        frames.append(frame)
    timestamps = [int(i * 1e9 / 30) for i in range(len(frames))]
    assert np.mean(np.abs(frames[0].astype(int) - frames[1].astype(int))) < 0.5
    frozen, _ = camera_freeze(frames, timestamps, lambda _start, _end: True)
    assert not frozen


def test_freeze_detection_rejects_identical_frames_while_robot_moves():
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    timestamps = [int(i * 1e9 / 30) for i in range(70)]
    frozen, duration = camera_freeze(
        [image] * 70, timestamps, lambda _start, _end: True
    )
    assert frozen and duration > 1.0
    stationary, _ = camera_freeze([image] * 70, timestamps, lambda _start, _end: False)
    assert not stationary
