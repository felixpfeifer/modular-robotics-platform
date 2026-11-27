#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import json
import math
import shutil
import uuid
from pathlib import Path

import cv2
import numpy as np

from episode_recorder_py.configuration import (
    load_workspace_config,
    recording_profile_hash,
)
from episode_recorder_py.validation import (
    image_is_unusable,
    load_contract,
    read_episode_bag,
    sha256_file,
)


def _time_ns(stamp) -> int:
    return int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)


def _state_at(
    states, timestamp: int, joint_names: list[str], times=None
) -> tuple[np.ndarray, int]:
    if times is None:
        times = [sample[1] for sample in states]
    index = bisect.bisect_left(times, timestamp)
    candidates = [i for i in (index - 1, index) if 0 <= i < len(states)]
    if not candidates:
        raise ValueError("no robot state samples")
    chosen = states[min(candidates, key=lambda i: abs(times[i] - timestamp))]
    values = dict(zip(chosen[2].name, chosen[2].position))
    return np.asarray([values[name] for name in joint_names], dtype=np.float32), chosen[
        1
    ]


def _action_at(
    actions, timestamp: int, joint_names: list[str], issued=None
) -> tuple[np.ndarray, int]:
    if issued is None:
        issued = [_time_ns(sample[2].issued_at) for sample in actions]
    index = bisect.bisect_right(issued, timestamp) - 1
    if index < 0 or timestamp > _time_ns(actions[index][2].valid_until):
        raise ValueError(f"no causal action covers image timestamp {timestamp}")
    message = actions[index][2]
    values = dict(zip(message.joint_names, message.positions))
    return np.asarray([values[name] for name in joint_names], dtype=np.float32), issued[
        index
    ]


def _image_at(samples, times, timestamp: int, camera):
    index = bisect.bisect_left(times, timestamp)
    candidates = [i for i in (index - 1, index) if 0 <= i < len(samples)]
    if not candidates:
        return None
    selected = min(candidates, key=lambda i: abs(times[i] - timestamp))
    if abs(times[selected] - timestamp) > 0.5e9 / float(camera["fps"]):
        return None
    encoded = np.frombuffer(bytes(samples[selected][2].data), dtype=np.uint8)
    if not encoded.size:
        return None
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    expected_shape = (int(camera["height"]), int(camera["width"]), 3)
    if image is None or image.shape != expected_shape or image_is_unusable(image):
        return None
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def load_accepted_manifest(
    path: Path,
    dataset_dir: Path,
    recording_profiles: Path | None = None,
    task_catalog: Path | None = None,
) -> list[tuple[Path, dict]]:
    selection = json.loads(path.read_text(encoding="utf-8"))
    if selection.get("schema_version") != "accepted-episodes/v1":
        raise ValueError("unsupported accepted episode manifest")
    episodes = []
    for item in selection.get("episodes", []):
        episode_id = str(uuid.UUID(item["episode_id"]))
        if episode_id != item["episode_id"]:
            raise ValueError(
                f"episode ID is not a canonical UUID: {item['episode_id']}"
            )
        episodes_root = (dataset_dir / "episodes").resolve()
        episode = dataset_dir / "episodes" / episode_id
        if episode.is_symlink() or episode.resolve().parent != episodes_root:
            raise ValueError(f"episode path escapes the dataset: {episode_id}")
        status = json.loads((episode / "status.json").read_text(encoding="utf-8"))
        validation = json.loads(
            (episode / "validation/validation.json").read_text(encoding="utf-8")
        )
        manifest = json.loads((episode / "manifest.json").read_text(encoding="utf-8"))
        mcap_files = list(episode.rglob("*.mcap"))
        if len(mcap_files) != 1:
            raise ValueError(f"episode must contain exactly one MCAP: {episode_id}")
        mcap = mcap_files[0]
        if status.get("status") != "accepted" or not validation.get("valid"):
            raise ValueError(f"episode is not accepted: {episode_id}")
        if validation.get("schema_version") != "episode-validation/v1":
            raise ValueError("unknown validation report version")
        if (
            item["content_hash"] != manifest.get("content_hash")
            or validation.get("artifact_hash") != item["content_hash"]
            or sha256_file(mcap) != item["content_hash"]
        ):
            raise ValueError(f"stale or changed artifact: {episode_id}")
        if validation.get("recording_profile_hash") != manifest.get(
            "recording_profile_hash"
        ) or validation.get("task_catalog_hash") != manifest.get("task_catalog_hash"):
            raise ValueError(f"validation contract changed: {episode_id}")
        if recording_profiles and manifest.get(
            "recording_profile_hash"
        ) != recording_profile_hash(
            recording_profiles, manifest["recording_profile_id"]
        ):
            raise ValueError(f"unknown recording profile version: {episode_id}")
        if task_catalog and manifest.get("task_catalog_hash") != sha256_file(
            task_catalog
        ):
            raise ValueError(f"unknown task catalog version: {episode_id}")
        episodes.append((episode, manifest))
    if not episodes:
        raise ValueError("accepted episode manifest is empty")
    expected_order = sorted(
        episodes, key=lambda item: (item[1]["started_ns"], item[0].name)
    )
    if episodes != expected_order:
        raise ValueError(
            "accepted episode manifest is not ordered by acquisition time and UUID"
        )
    return episodes


def export(args: argparse.Namespace) -> None:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from torch.utils.data import DataLoader

    episodes = load_accepted_manifest(
        args.accepted_manifest,
        args.dataset_dir,
        args.recording_profiles,
        args.task_catalog,
    )
    first_manifest = episodes[0][1]
    reference_profile, _ = load_contract(
        args.recording_profiles,
        args.task_catalog,
        first_manifest["recording_profile_id"],
        first_manifest["task_id"],
    )
    joint_names = [joint["name"] for joint in reference_profile["joints"]]
    cameras = reference_profile["cameras"]
    timeline_camera = next(
        camera
        for camera in cameras
        if camera["name"] == reference_profile["timeline_camera"]
    )
    downsample_ratio = getattr(args, "downsample_hz_ratio", 1)
    if downsample_ratio < 1:
        raise ValueError("downsample_hz_ratio must be >= 1")
    output_fps = float(timeline_camera["fps"]) / downsample_ratio
    if output_fps < 1 or not math.isclose(output_fps, round(output_fps), abs_tol=1e-6):
        raise ValueError("downsample ratio must produce a positive integer frame rate")
    if args.output_dir.exists():
        if not args.force:
            raise FileExistsError(f"output exists: {args.output_dir}")
        shutil.rmtree(args.output_dir)
    features = {
        **{
            f"observation.images.{camera['name']}": {
                "dtype": "video",
                "shape": (int(camera["height"]), int(camera["width"]), 3),
                "names": ["height", "width", "channels"],
            }
            for camera in cameras
        },
        "observation.state": {
            "dtype": "float32",
            "shape": (len(joint_names),),
            "names": joint_names,
        },
        "action": {
            "dtype": "float32",
            "shape": (len(joint_names),),
            "names": joint_names,
        },
        "observation.source_timestamp_ns": {
            "dtype": "int64",
            "shape": (1,),
            "names": ["camera"],
        },
        "observation.receive_timestamp_ns": {
            "dtype": "int64",
            "shape": (1,),
            "names": ["camera"],
        },
        "observation.state_skew_ms": {
            "dtype": "float32",
            "shape": (1,),
            "names": ["state"],
        },
        "action.skew_ms": {"dtype": "float32", "shape": (1,), "names": ["action"]},
    }
    dataset = LeRobotDataset.create(
        repo_id=args.repo_id,
        root=args.output_dir,
        fps=int(round(output_fps)),
        robot_type=reference_profile["robot_type"],
        features=features,
        use_videos=True,
        image_writer_threads=4,
    )
    expected_frames = 0
    expected_tasks: set[str] = set()
    source_index = []
    for episode, manifest in sorted(
        episodes, key=lambda item: (item[1]["started_ns"], item[0].name)
    ):
        profile, task = load_contract(
            args.recording_profiles,
            args.task_catalog,
            manifest["recording_profile_id"],
            manifest["task_id"],
        )
        signature = (
            profile["robot_type"],
            tuple(joint["name"] for joint in profile["joints"]),
            tuple(
                (camera["name"], camera["width"], camera["height"], camera["fps"])
                for camera in profile["cameras"]
            ),
            profile["timeline_camera"],
        )
        reference_signature = (
            reference_profile["robot_type"],
            tuple(joint["name"] for joint in reference_profile["joints"]),
            tuple(
                (camera["name"], camera["width"], camera["height"], camera["fps"])
                for camera in reference_profile["cameras"]
            ),
            reference_profile["timeline_camera"],
        )
        if signature != reference_signature:
            raise ValueError(
                "accepted episodes have incompatible robot/camera feature contracts"
            )
        expected_tasks.add(task["instruction"])
        _, streams = read_episode_bag(episode)
        images_by_camera = {
            camera["name"]: streams[camera["topic"]] for camera in cameras
        }
        images = images_by_camera[timeline_camera["name"]]
        camera_times = {
            name: [sample[1] for sample in samples]
            for name, samples in images_by_camera.items()
        }
        states = streams[profile["state"]["topic"]]
        actions = streams[profile["action"]["topic"]]
        state_times = [sample[1] for sample in states]
        action_times = [_time_ns(sample[2].issued_at) for sample in actions]
        episode_frames = 0
        usable_ticks = 0
        for receive_ns, source_ns, _ in images:
            state, state_ns = _state_at(states, source_ns, joint_names, state_times)
            action, action_ns = _action_at(
                actions, source_ns, joint_names, action_times
            )
            if (
                abs(source_ns - state_ns)
                > float(profile["state"]["maximum_skew_ms"]) * 1e6
            ):
                continue
            frame = {
                "observation.state": state,
                "action": action,
                "observation.source_timestamp_ns": np.asarray(
                    [source_ns], dtype=np.int64
                ),
                "observation.receive_timestamp_ns": np.asarray(
                    [receive_ns], dtype=np.int64
                ),
                "observation.state_skew_ms": np.asarray(
                    [abs(source_ns - state_ns) / 1e6], dtype=np.float32
                ),
                "action.skew_ms": np.asarray(
                    [(source_ns - action_ns) / 1e6], dtype=np.float32
                ),
                "task": task["instruction"],
            }
            for camera in cameras:
                image = _image_at(
                    images_by_camera[camera["name"]],
                    camera_times[camera["name"]],
                    source_ns,
                    camera,
                )
                if image is None:
                    break
                frame[f"observation.images.{camera['name']}"] = image
            else:
                keep_frame = usable_ticks % downsample_ratio == 0
                usable_ticks += 1
                if not keep_frame:
                    continue
                if not np.isfinite(state).all() or not np.isfinite(action).all():
                    raise ValueError("non-finite validated data reached exporter")
                dataset.add_frame(frame)
                episode_frames += 1
                continue
            continue
        if not episode_frames:
            raise ValueError(
                f"episode has no usable synchronized frames: {episode.name}"
            )
        dataset.save_episode()
        source_index.append(
            {
                "episode_index": len(source_index),
                "episode_id": episode.name,
                "content_hash": manifest["content_hash"],
            }
        )
        expected_frames += episode_frames
    dataset.finalize()
    (args.output_dir / "meta/source_episodes.json").write_text(
        json.dumps(source_index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    reopened = LeRobotDataset(args.repo_id, root=args.output_dir)
    if len(reopened) != expected_frames:
        raise RuntimeError(
            f"LeRobot round trip returned {len(reopened)} frames, expected {expected_frames}"
        )
    actual_tasks = set(reopened.meta.tasks.index.tolist())
    if actual_tasks != expected_tasks:
        raise RuntimeError(
            f"LeRobot round trip changed task mappings: {actual_tasks} != {expected_tasks}"
        )
    iterated_frames = 0
    last_source_timestamp: dict[int, int] = {}
    loader = DataLoader(reopened, batch_size=8, shuffle=False, num_workers=0)
    for batch in loader:
        batch_size = int(batch["observation.state"].shape[0])
        iterated_frames += batch_size
        if tuple(batch["observation.state"].shape[1:]) != (len(joint_names),) or tuple(
            batch["action"].shape[1:]
        ) != (len(joint_names),):
            raise RuntimeError("LeRobot round trip changed state/action shapes")
        for camera in cameras:
            expected_shape = (3, int(camera["height"]), int(camera["width"]))
            if (
                tuple(batch[f"observation.images.{camera['name']}"].shape[1:])
                != expected_shape
            ):
                raise RuntimeError(
                    f"LeRobot round trip changed {camera['name']} decoded video shape"
                )
        for key in (
            "observation.state",
            "action",
            "observation.source_timestamp_ns",
            "observation.receive_timestamp_ns",
            "observation.state_skew_ms",
            "action.skew_ms",
        ):
            if not bool(batch[key].isfinite().all()):
                raise RuntimeError(f"non-finite {key} after LeRobot round trip")
        if set(batch["task"]) - expected_tasks:
            raise RuntimeError("LeRobot round trip changed a frame task mapping")
        episode_indices = batch["episode_index"].reshape(-1).tolist()
        source_timestamps = (
            batch["observation.source_timestamp_ns"].reshape(-1).tolist()
        )
        receive_timestamps = (
            batch["observation.receive_timestamp_ns"].reshape(-1).tolist()
        )
        for episode_index, source_ns, receive_ns in zip(
            episode_indices, source_timestamps, receive_timestamps, strict=True
        ):
            episode_index, source_ns, receive_ns = (
                int(episode_index),
                int(source_ns),
                int(receive_ns),
            )
            if source_ns <= 0 or receive_ns <= 0:
                raise RuntimeError("LeRobot round trip produced a zero timestamp")
            if source_ns <= last_source_timestamp.get(episode_index, 0):
                raise RuntimeError(
                    "LeRobot round trip changed camera timestamp ordering"
                )
            last_source_timestamp[episode_index] = source_ns
    if iterated_frames != expected_frames:
        raise RuntimeError(
            f"DataLoader iterated {iterated_frames} frames, expected {expected_frames}"
        )
    print(
        f"exported and verified {len(source_index)} episodes / {expected_frames} frames at {args.output_dir}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export accepted MCAP episodes to LeRobot Dataset v3"
    )
    parser.add_argument("--workspace-config", type=Path)
    parser.add_argument("--dataset-dir", type=Path)
    parser.add_argument("--accepted-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--recording-profiles", type=Path)
    parser.add_argument("--task-catalog", type=Path)
    parser.add_argument("--downsample-hz-ratio", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.workspace_config:
        workspace = load_workspace_config(args.workspace_config)
        args.dataset_dir = args.dataset_dir or Path(workspace["dataset_dir"])
        args.recording_profiles = args.recording_profiles or Path(
            workspace["recording_profiles_path"]
        )
        args.task_catalog = args.task_catalog or Path(workspace["task_catalog_path"])
    if not args.dataset_dir or not args.recording_profiles or not args.task_catalog:
        parser.error(
            "provide --workspace-config or all of --dataset-dir, --recording-profiles and --task-catalog"
        )
    export(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
