from __future__ import annotations

import argparse
import json

import pyarrow.parquet as pq
import pytest

from episode_recorder_py.export_lerobot import export
from episode_recorder_py.upload_lerobot import validate_dataset
from episode_recorder_py.validation import validate_episode
from test_mcap_integration import PROFILE, TASKS, _write_episode


@pytest.mark.parametrize(
    "fault, ratio, expected_frames, expected_episodes",
    [
        (None, 1, 61, 1),
        ("blank_image", 1, 60, 1),
        ("corrupt_image", 1, 60, 1),
        (None, 2, 31, 1),
        ("blank_image", 2, 30, 1),
        ("slow_camera", 1, 61, 1),
    ],
)
def test_official_lerobot_v3_round_trip(
    tmp_path, fault, ratio, expected_frames, expected_episodes
):
    dataset_root = tmp_path / "raw"
    frame_step = 40_000_000 if fault == "slow_camera" else 33_333_334
    episode = _write_episode(dataset_root, fault=fault, frame_step_ns=frame_step)
    outcome = validate_episode(episode, PROFILE, TASKS)
    assert outcome.valid
    manifest = json.loads((episode / "manifest.json").read_text(encoding="utf-8"))
    accepted = tmp_path / "accepted.json"
    accepted.write_text(
        json.dumps(
            {
                "schema_version": "accepted-episodes/v1",
                "episodes": [
                    {
                        "episode_id": episode.name,
                        "content_hash": manifest["content_hash"],
                        "started_ns": manifest["started_ns"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "lerobot-v3"
    export(
        argparse.Namespace(
            dataset_dir=dataset_root,
            accepted_manifest=accepted,
            output_dir=output,
            repo_id="local/so101-vla-ci",
            recording_profiles=PROFILE,
            task_catalog=TASKS,
            force=False,
            downsample_hz_ratio=ratio,
        )
    )
    info = json.loads((output / "meta/info.json").read_text(encoding="utf-8"))
    assert info["fps"] == 30 // ratio
    source_index = json.loads(
        (output / "meta/source_episodes.json").read_text(encoding="utf-8")
    )
    assert source_index == [
        {
            "episode_index": index,
            "episode_id": episode.name,
            "content_hash": manifest["content_hash"],
        }
        for index in range(expected_episodes)
    ]
    verification = validate_dataset(output, repo_id="local/so101-vla-ci")
    assert verification["frames"] == expected_frames
    assert verification["episodes"] == expected_episodes
    timestamps = []
    playback_timestamps = []
    for data_file in sorted((output / "data").rglob("*.parquet")):
        table = pq.read_table(
            data_file, columns=["observation.source_timestamp_ns", "timestamp"]
        )
        timestamps.extend(table.column("observation.source_timestamp_ns").to_pylist())
        playback_timestamps.extend(table.column("timestamp").to_pylist())
    indices = [
        index
        for index in range(61)
        if fault not in ("blank_image", "corrupt_image") or index != 10
    ][::ratio]
    assert timestamps == [10_000_000_000 + index * frame_step for index in indices]
    assert playback_timestamps == pytest.approx(
        [index / info["fps"] for index in range(expected_frames)]
    )
    if fault == "slow_camera":
        assert (timestamps[-1] - timestamps[0]) / 1e9 == pytest.approx(2.4)
        assert playback_timestamps[-1] == pytest.approx(2.0)
    if fault is None and ratio == 2:
        for invalid_ratio in (0, 7, 31):
            with pytest.raises(ValueError, match="downsample"):
                export(
                    argparse.Namespace(
                        dataset_dir=dataset_root,
                        accepted_manifest=accepted,
                        output_dir=output,
                        repo_id="local/so101-vla-ci",
                        recording_profiles=PROFILE,
                        task_catalog=TASKS,
                        force=True,
                        downsample_hz_ratio=invalid_ratio,
                    )
                )
            assert (output / "meta/info.json").is_file()
