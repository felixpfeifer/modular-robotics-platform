from __future__ import annotations

import bisect
import ctypes
import ctypes.util
import functools
import json
import math
import re
import struct
import time
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from episode_recorder_py.configuration import (
    load_recording_profile,
    recording_profile_hash,
    sha256_file,
)


@dataclass
class Finding:
    rule_id: str
    severity: str
    summary: str

    @property
    def failing(self) -> bool:
        return self.severity in {"error", "fatal"}


@dataclass
class ValidationResult:
    episode_id: str
    valid: bool = True
    findings: list[Finding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def add(
        self, rule_id: str, ok: bool, summary: str, severity: str = "error"
    ) -> None:
        finding_severity = (
            severity if severity == "warning" else ("info" if ok else severity)
        )
        self.findings.append(Finding(rule_id, finding_severity, summary))
        if not ok and severity in {"error", "fatal"}:
            self.valid = False


def image_is_unusable(frame) -> bool:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return (
        float(np.std(gray)) < 2.0
        or float(np.mean(gray)) <= 5.0
        or float(np.mean(gray)) >= 250.0
    )


def camera_freeze(frames, timestamps_ns, robot_changed, difference_threshold=0.5):
    """Detect a one-second frozen interval while robot state or action changes.

    Compare against the interval's first frame, rather than only the immediately
    preceding frame: small changes can accumulate into visible continuous motion.
    """
    anchor = 0
    maximum_frozen_seconds = 0.0
    for index in range(1, len(frames)):
        difference = float(np.mean(cv2.absdiff(frames[anchor], frames[index])))
        if difference >= difference_threshold:
            anchor = index
            continue
        frozen_seconds = (timestamps_ns[index] - timestamps_ns[anchor]) / 1e9
        maximum_frozen_seconds = max(maximum_frozen_seconds, frozen_seconds)
        if frozen_seconds > 1.0 and robot_changed(
            timestamps_ns[anchor], timestamps_ns[index]
        ):
            return True, maximum_frozen_seconds
    return False, maximum_frozen_seconds


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(re.fullmatch(r"sha256:[0-9a-fA-F]{64}", value))
        and value[7:] != "0" * 64
    )


@functools.lru_cache(maxsize=1)
def _zstd_library():
    library_name = ctypes.util.find_library("zstd")
    if not library_name:
        raise ValueError("libzstd is unavailable")
    library = ctypes.CDLL(library_name)
    library.ZSTD_decompress.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    library.ZSTD_decompress.restype = ctypes.c_size_t
    library.ZSTD_isError.argtypes = [ctypes.c_size_t]
    library.ZSTD_isError.restype = ctypes.c_uint
    return library


def _zstd_decompress(payload: bytes, expected_size: int) -> bytes:
    library = _zstd_library()
    destination = ctypes.create_string_buffer(expected_size)
    source = ctypes.create_string_buffer(payload)
    size = library.ZSTD_decompress(destination, expected_size, source, len(payload))
    if library.ZSTD_isError(size) or size != expected_size:
        raise ValueError("MCAP Zstd chunk decompression failed")
    return destination.raw[:size]


def validate_mcap_integrity(path: Path) -> dict[str, int]:
    """Validate the CRC/index contract independently of rosbag2's permissive reader."""
    magic = b"\x89MCAP0\r\n"
    file_size = path.stat().st_size
    if file_size < 8 + 29 + 8:
        raise ValueError("MCAP is truncated")
    chunk_count = chunk_index_count = message_index_count = statistics_count = 0
    data_crc = zlib.crc32(magic)
    data_section = True
    footer_position = summary_start = summary_offset_start = summary_crc = 0

    with path.open("rb") as stream:
        if stream.read(8) != magic:
            raise ValueError("MCAP opening magic is invalid")
        while stream.tell() < file_size - 8:
            record_position = stream.tell()
            header = stream.read(9)
            if len(header) != 9:
                raise ValueError("MCAP record header is truncated")
            opcode, length = struct.unpack("<BQ", header)
            if length > file_size - stream.tell() - 8:
                raise ValueError("MCAP record length escapes the file")
            if length > 128 * 1024 * 1024:
                raise ValueError("MCAP record exceeds the 128 MiB validation limit")
            payload = stream.read(length)
            if len(payload) != length:
                raise ValueError("MCAP record is truncated")

            if opcode == 0x0F:  # DataEnd
                if length != 4:
                    raise ValueError("MCAP DataEnd has an invalid length")
                expected_data_crc = struct.unpack("<I", payload)[0]
                if expected_data_crc and expected_data_crc != data_crc:
                    raise ValueError("MCAP data-section CRC mismatch")
                data_section = False
            elif data_section:
                data_crc = zlib.crc32(header, data_crc)
                data_crc = zlib.crc32(payload, data_crc)

            if opcode == 0x06:  # Chunk
                chunk_count += 1
                if length < 40:
                    raise ValueError("MCAP chunk is malformed")
                uncompressed_size = struct.unpack_from("<Q", payload, 16)[0]
                expected_chunk_crc = struct.unpack_from("<I", payload, 24)[0]
                compression_length = struct.unpack_from("<I", payload, 28)[0]
                cursor = 32 + compression_length
                if cursor + 8 > len(payload):
                    raise ValueError("MCAP chunk compression field is malformed")
                compression = payload[32:cursor].decode("utf-8")
                compressed_size = struct.unpack_from("<Q", payload, cursor)[0]
                compressed = payload[cursor + 8 :]
                if compressed_size != len(compressed):
                    raise ValueError("MCAP chunk size does not match its payload")
                if expected_chunk_crc == 0:
                    raise ValueError("MCAP chunk CRC is disabled")
                if uncompressed_size > 64 * 1024 * 1024:
                    raise ValueError("MCAP chunk exceeds the 64 MiB validation limit")
                if compression == "zstd":
                    uncompressed = _zstd_decompress(compressed, uncompressed_size)
                elif compression == "":
                    uncompressed = compressed
                else:
                    raise ValueError(
                        f"unsupported MCAP chunk compression: {compression}"
                    )
                if (
                    len(uncompressed) != uncompressed_size
                    or zlib.crc32(uncompressed) != expected_chunk_crc
                ):
                    raise ValueError("MCAP chunk CRC mismatch")
            elif opcode == 0x07:
                message_index_count += 1
            elif opcode == 0x08:  # ChunkIndex
                chunk_index_count += 1
                if length < 56:
                    raise ValueError("MCAP chunk index is malformed")
                offsets_length = struct.unpack_from("<I", payload, 32)[0]
                cursor = 36 + offsets_length
                if (
                    offsets_length == 0
                    or offsets_length % 10
                    or cursor + 8 > len(payload)
                ):
                    raise ValueError("MCAP message index offsets are incomplete")
                if struct.unpack_from("<Q", payload, cursor)[0] == 0:
                    raise ValueError("MCAP message index length is zero")
            elif opcode == 0x0B:
                statistics_count += 1
            elif opcode == 0x02:  # Footer
                footer_position = record_position
                if length != 20:
                    raise ValueError("MCAP footer has an invalid length")
                summary_start, summary_offset_start, summary_crc = struct.unpack(
                    "<QQI", payload
                )
                break

        if footer_position == 0 or stream.read(8) != magic or stream.read(1):
            raise ValueError("MCAP closing magic/footer is invalid")
        if (
            not summary_start
            or not summary_offset_start
            or summary_offset_start < summary_start
        ):
            raise ValueError("MCAP summary offsets are incomplete")
        if (
            chunk_count == 0
            or chunk_index_count != chunk_count
            or message_index_count == 0
            or statistics_count != 1
        ):
            raise ValueError("MCAP chunk/message indexes or statistics are incomplete")
        if summary_crc == 0:
            raise ValueError("MCAP summary CRC is disabled")
        stream.seek(summary_start)
        summary_data = stream.read(footer_position - summary_start)
        calculated_summary_crc = zlib.crc32(summary_data)
        calculated_summary_crc = zlib.crc32(
            struct.pack("<BQQQ", 0x02, 20, summary_start, summary_offset_start),
            calculated_summary_crc,
        )
        if calculated_summary_crc != summary_crc:
            raise ValueError("MCAP summary CRC mismatch")
    return {
        "mcap_chunk_count": chunk_count,
        "mcap_chunk_index_count": chunk_index_count,
        "mcap_message_index_count": message_index_count,
    }


def _time_ns(stamp: Any) -> int:
    return int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)


def _source_time_ns(message: Any, receive_ns: int) -> int:
    if hasattr(message, "header"):
        return _time_ns(message.header.stamp)
    if hasattr(message, "issued_at"):
        return _time_ns(message.issued_at)
    return receive_ns


def _strictly_increasing(values: list[int]) -> bool:
    return bool(values) and all(a < b for a, b in zip(values, values[1:]))


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return math.inf
    return float(np.percentile(np.asarray(values, dtype=np.float64), percentile))


def load_contract(
    profile_path: Path, task_path: Path, profile_id: str, task_id: str
) -> tuple[dict, dict]:
    tasks = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    if tasks.get("schema_version") != "task-catalog/v1":
        raise ValueError("unsupported task catalog schema")
    profile = load_recording_profile(profile_path, profile_id)
    task = tasks["tasks"][task_id]
    if task["recording_profile_id"] != profile_id:
        raise ValueError("task and recording profile do not match")
    return profile, task


def read_episode_bag(
    episode_dir: Path,
) -> tuple[dict[str, str], dict[str, list[tuple[int, int, Any]]]]:
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    bag_dir = episode_dir / "bag"
    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag_dir), storage_id="mcap"),
        rosbag2_py.ConverterOptions(
            input_serialization_format="cdr", output_serialization_format="cdr"
        ),
    )
    topic_types = {item.name: item.type for item in reader.get_all_topics_and_types()}
    message_types = {
        name: get_message(type_name) for name, type_name in topic_types.items()
    }
    messages: dict[str, list[tuple[int, int, Any]]] = {name: [] for name in topic_types}
    while reader.has_next():
        topic_name, raw, receive_ns = reader.read_next()
        message = deserialize_message(raw, message_types[topic_name])
        messages[topic_name].append(
            (receive_ns, _source_time_ns(message, receive_ns), message)
        )
    return topic_types, messages


def validate_episode(
    episode_dir: Path,
    profile_path: Path,
    task_path: Path,
    expected_hash: str | None = None,
) -> ValidationResult:
    manifest_path = episode_dir / "manifest.json"
    episode_id = episode_dir.name
    result = ValidationResult(episode_id)
    result.add(
        "metadata.manifest",
        manifest_path.is_file(),
        "immutable acquisition manifest is present",
        "fatal",
    )
    if not manifest_path.is_file():
        return result
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result.add(
        "metadata.schema",
        manifest.get("schema_version") == "episode-manifest/v1",
        "manifest schema is supported",
    )
    result.add(
        "metadata.identity",
        manifest.get("episode_id") == episode_id,
        "episode UUID matches its directory",
    )
    producers = manifest.get("producers", [])
    producer_provenance_complete = bool(producers) and all(
        producer.get("component_id")
        and producer.get("semantic_version")
        and producer.get("source_revision")
        and producer.get("build_id")
        and _is_sha256(producer.get("configuration_hash"))
        and producer.get("calibration_id")
        and _is_sha256(producer.get("calibration_hash"))
        for producer in producers
    )
    metadata_complete = (
        bool(manifest.get("recording_profile_id"))
        and _is_sha256(manifest.get("recording_profile_hash"))
        and bool(manifest.get("task_id"))
        and _is_sha256(manifest.get("task_catalog_hash"))
        and _is_sha256(manifest.get("configuration_hash"))
        and bool(manifest.get("calibration_ids"))
        and all(
            isinstance(item, str) and item
            for item in manifest.get("calibration_ids", [])
        )
        and producer_provenance_complete
    )
    result.add(
        "metadata.complete",
        metadata_complete,
        "profile, task, configuration and calibration provenance are complete",
    )

    mcap_files = list(episode_dir.rglob("*.mcap"))
    result.add(
        "storage.single_mcap",
        len(mcap_files) == 1,
        f"found {len(mcap_files)} MCAP files",
        "fatal",
    )
    if len(mcap_files) != 1:
        return _write_result(episode_dir, manifest, result)
    actual_hash = sha256_file(mcap_files[0])
    expected = expected_hash or manifest.get("content_hash")
    result.metrics["mcap_bytes"] = mcap_files[0].stat().st_size
    result.add(
        "storage.sha256",
        actual_hash == expected == manifest.get("content_hash"),
        "MCAP SHA-256 matches manifest and request",
        "fatal",
    )

    try:
        result.metrics.update(validate_mcap_integrity(mcap_files[0]))
        result.add(
            "storage.crc_indexes",
            True,
            "MCAP chunk/summary CRCs and complete indexes are valid",
        )
    except Exception as exc:
        result.add(
            "storage.crc_indexes",
            False,
            f"MCAP integrity validation failed: {exc}",
            "fatal",
        )
        return _write_result(episode_dir, manifest, result)

    try:
        profile, task = load_contract(
            profile_path,
            task_path,
            manifest["recording_profile_id"],
            manifest["task_id"],
        )
        result.add(
            "metadata.profile_hash",
            manifest.get("recording_profile_hash")
            == recording_profile_hash(profile_path, manifest["recording_profile_id"]),
            "resolved robot/camera/profile contract hash matches the validator input",
        )
        result.add(
            "metadata.task_catalog_hash",
            manifest.get("task_catalog_hash") == sha256_file(task_path),
            "task catalog hash matches the validator input",
        )
        topic_types, streams = read_episode_bag(episode_dir)
        result.add("storage.readable", True, "MCAP was read completely")
    except Exception as exc:
        result.add(
            "storage.readable", False, f"MCAP/contract read failed: {exc}", "fatal"
        )
        return _write_result(episode_dir, manifest, result)

    timeline_camera = next(
        camera
        for camera in profile["cameras"]
        if camera["name"] == profile["timeline_camera"]
    )
    required = {
        profile["state"]["topic"]: profile["state"]["type"],
        profile["action"]["topic"]: profile["action"]["type"],
        "/platform/episode/metadata": "platform_episode_interfaces/msg/EpisodeMetadata",
        "/platform/episode/events": "platform_episode_interfaces/msg/EpisodeEvent",
    }
    required.update({camera["topic"]: camera["type"] for camera in profile["cameras"]})
    for name, type_name in required.items():
        result.add(
            f"schema.topic.{name.strip('/').replace('/', '_')}",
            topic_types.get(name) == type_name and len(streams.get(name, [])) > 0,
            f"{name} has exact type {type_name} and at least one message",
        )

    images_by_camera = {
        camera["name"]: streams.get(camera["topic"], [])
        for camera in profile["cameras"]
    }
    images = images_by_camera[timeline_camera["name"]]
    states = streams.get(profile["state"]["topic"], [])
    actions = streams.get(profile["action"]["topic"], [])
    timed_streams = [("state", states), ("action", actions)]
    timed_streams.extend(
        (
            "camera"
            if camera["name"] == timeline_camera["name"]
            else f"camera.{camera['name']}",
            images_by_camera[camera["name"]],
        )
        for camera in profile["cameras"]
    )
    for name, samples in timed_streams:
        receipts = [sample[0] for sample in samples]
        source = [sample[1] for sample in samples]
        result.add(
            f"time.{name}.receipt_nonzero",
            bool(receipts) and all(value > 0 for value in receipts),
            f"{name} receipt timestamps are nonzero",
        )
        result.add(
            f"time.{name}.receipt_monotonic",
            _strictly_increasing(receipts),
            f"{name} receipt timestamps are strictly increasing",
        )
        result.add(
            f"time.{name}.nonzero",
            bool(source) and all(value > 0 for value in source),
            f"{name} source timestamps are nonzero",
        )
        result.add(
            f"time.{name}.monotonic",
            _strictly_increasing(source),
            f"{name} source timestamps are strictly increasing",
        )
        maximum_offset_ms = max(
            (abs(receipt - acquisition) / 1e6 for receipt, acquisition, _ in samples),
            default=math.inf,
        )
        result.metrics[f"{name}_source_receipt_offset_max_ms"] = maximum_offset_ms
        result.add(
            f"time.{name}.clock_domain",
            bool(samples)
            and maximum_offset_ms
            <= float(profile.get("maximum_source_receipt_offset_ms", 1000.0)),
            f"{name} maximum source/receipt offset is {maximum_offset_ms:.3f} ms",
        )

    duration = (images[-1][1] - images[0][1]) / 1e9 if len(images) > 1 else 0.0
    minimum_duration = max(
        float(profile["minimum_duration_seconds"]),
        float(task.get("minimum_duration_seconds", 0)),
    )
    result.metrics.update(
        {
            "duration_seconds": duration,
            "image_count": len(images),
            "state_count": len(states),
            "action_count": len(actions),
        }
    )
    result.add(
        "episode.minimum_duration",
        duration >= minimum_duration,
        f"duration {duration:.3f}s >= {minimum_duration:.3f}s",
    )
    result.add(
        "episode.operator_success",
        bool(manifest.get("operator_success")) and not manifest.get("canceled"),
        "operator supplied terminal success",
    )
    result.add(
        "writer.no_drops",
        not manifest.get("writer_dropped", True),
        "writer reported no dropped messages",
    )
    result.add(
        "writer.no_errors",
        not manifest.get("writer_error", True),
        "writer reported no serialization or storage errors",
    )

    decoded_by_camera: dict[str, list[np.ndarray]] = {}
    for camera in profile["cameras"]:
        camera_images = images_by_camera[camera["name"]]
        rule = (
            "camera"
            if camera["name"] == timeline_camera["name"]
            else f"camera.{camera['name']}"
        )
        metric = (
            "camera"
            if camera["name"] == timeline_camera["name"]
            else f"camera_{camera['name']}"
        )
        decoded_frames: list[np.ndarray] = []
        blank_count = 0
        for _, _, message in camera_images:
            encoded = np.frombuffer(bytes(message.data), dtype=np.uint8)
            frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None
            if frame is None:
                continue
            decoded_frames.append(frame)
            if image_is_unusable(frame):
                blank_count += 1
        decoded_by_camera[camera["name"]] = decoded_frames
        result.add(
            f"{rule}.decode",
            len(decoded_frames) == len(camera_images) and bool(camera_images),
            f"every {camera['name']} camera message decodes",
            "warning",
        )
        dimensions_ok_for_camera = bool(decoded_frames) and all(
            frame.shape[:2] == (camera["height"], camera["width"])
            for frame in decoded_frames
        )
        formats_ok = bool(camera_images) and all(
            sample[2].format.strip().lower() in {"jpeg", "jpg"}
            for sample in camera_images
        )
        result.add(
            f"{rule}.dimensions",
            dimensions_ok_for_camera,
            f"all {camera['name']} images are {camera['width']}x{camera['height']}",
        )
        result.add(
            f"{rule}.format",
            formats_ok and camera["format"].lower() in {"jpeg", "jpg"},
            f"all {camera['name']} compressed images declare JPEG",
        )
        result.add(
            f"{rule}.blank",
            blank_count == 0,
            f"{camera['name']} blank or unusable frames: {blank_count}",
            "warning",
        )

        camera_times = [item[1] for item in camera_images]
        camera_duration = (
            (camera_times[-1] - camera_times[0]) / 1e9 if len(camera_times) > 1 else 0.0
        )
        gaps_ms = [(b - a) / 1e6 for a, b in zip(camera_times, camera_times[1:])]
        expected_frames = (
            round(camera_duration * float(camera["fps"])) + 1 if camera_duration else 0
        )
        coverage = len(camera_images) / expected_frames if expected_frames else 0.0
        fps = (len(camera_images) - 1) / camera_duration if camera_duration > 0 else 0.0
        result.metrics.update(
            {
                f"{metric}_fps": fps,
                f"{metric}_coverage": coverage,
                f"{metric}_max_gap_ms": max(gaps_ms, default=math.inf),
                f"{metric}_blank_frames": blank_count,
            }
        )
        result.add(
            f"{rule}.fps",
            abs(fps - float(camera["fps"])) <= float(camera.get("fps_tolerance", 0.6)),
            f"{camera['name']} camera rate is {fps:.3f} FPS; expected {camera['fps']:.3f}",
            "warning",
        )
        result.add(
            f"{rule}.coverage",
            coverage >= float(camera.get("minimum_coverage", 0.98)),
            f"{camera['name']} camera coverage is {coverage:.4f}",
            "warning",
        )
        result.add(
            f"{rule}.max_gap",
            bool(gaps_ms) and max(gaps_ms) <= float(camera.get("maximum_gap_ms", 75.0)),
            f"{camera['name']} maximum camera gap is {max(gaps_ms, default=math.inf):.3f} ms",
            "warning",
        )

    image_times = [item[1] for item in images]

    joint_specs = profile["joints"]
    canonical_names = [joint["name"] for joint in joint_specs]
    state_valid = True
    for _, _, message in states:
        if (
            len(message.name) != len(set(message.name))
            or set(message.name) != set(canonical_names)
            or len(message.position) != len(message.name)
        ):
            state_valid = False
            break
        positions = dict(zip(message.name, message.position))
        for joint in joint_specs:
            value = positions[joint["name"]]
            if (
                not math.isfinite(value)
                or value < joint["lower"] - 0.02
                or value > joint["upper"] + 0.02
            ):
                state_valid = False
                break
    result.add(
        "state.schema_finite_limits",
        bool(states) and state_valid,
        "states have exact joints, finite positions and valid limits",
    )

    action_valid = True
    for _, _, message in actions:
        if (
            len(message.joint_names) != len(set(message.joint_names))
            or set(message.joint_names) != set(canonical_names)
            or len(message.positions) != len(message.joint_names)
        ):
            action_valid = False
            break
        positions = dict(zip(message.joint_names, message.positions))
        if _time_ns(message.issued_at) <= 0 or _time_ns(message.valid_until) < _time_ns(
            message.issued_at
        ):
            action_valid = False
            break
        for joint in joint_specs:
            value = positions[joint["name"]]
            if (
                not math.isfinite(value)
                or value < joint["lower"] - 0.02
                or value > joint["upper"] + 0.02
            ):
                action_valid = False
                break
    result.add(
        "action.schema_finite_limits",
        bool(actions) and action_valid,
        "actions have exact joints, finite positions, valid limits and validity windows",
    )

    state_times = [item[1] for item in states]
    state_skews: list[float] = []
    if state_times:
        for image_time in image_times:
            index = bisect.bisect_left(state_times, image_time)
            candidates = state_times[
                max(0, index - 1) : min(len(state_times), index + 1)
            ]
            state_skews.append(
                min(abs(value - image_time) for value in candidates) / 1e6
            )
    result.metrics.update(
        {
            "state_skew_p99_ms": _percentile(state_skews, 99),
            "state_skew_max_ms": max(state_skews, default=math.inf),
        }
    )
    result.add(
        "sync.state_p99",
        bool(state_skews)
        and _percentile(state_skews, 99) <= float(profile["state"]["p99_skew_ms"]),
        f"state skew p99 is {_percentile(state_skews, 99):.3f} ms",
    )
    result.add(
        "sync.state_max",
        bool(state_skews)
        and max(state_skews) <= float(profile["state"]["maximum_skew_ms"]),
        f"state skew maximum is {max(state_skews, default=math.inf):.3f} ms",
    )

    issued = [_time_ns(item[2].issued_at) for item in actions]
    uncovered = 0
    first_gap = ""
    for image_time in image_times:
        index = bisect.bisect_right(issued, image_time) - 1
        if index >= 0 and image_time <= _time_ns(actions[index][2].valid_until):
            continue
        uncovered += 1
        if uncovered == 1:
            seconds = (image_time - image_times[0]) / 1e9
            cause = (
                "no command had been issued yet"
                if index < 0
                else "the latest command had expired"
            )
            first_gap = f"First gap at {seconds:.3f} s from the first frame ({cause})."
    result.metrics["action_uncovered_frames"] = uncovered
    if not images:
        coverage_summary = "No camera frames were recorded to check against robot commands."
    elif uncovered:
        coverage_summary = (
            f"{uncovered} of {len(images)} camera frames had no valid robot command. {first_gap}"
        )
    else:
        coverage_summary = "every image is covered by a non-future, non-expired JointIntent"
    result.add(
        "sync.action_causal_coverage",
        bool(images) and uncovered == 0,
        coverage_summary,
    )

    safety = streams.get("/platform/control/safety_events", [])
    unsafe = [item for item in safety if item[2].severity >= item[2].SEVERITY_ERROR]
    rejections = streams.get("/platform/control/command_rejections", [])
    result.add(
        "safety.no_error", not unsafe, f"safety error/fatal events: {len(unsafe)}"
    )
    result.add(
        "command.no_rejection", not rejections, f"command rejections: {len(rejections)}"
    )

    def robot_changed(start_ns: int, end_ns: int) -> bool:
        for samples, names_attr in ((states, "name"), (actions, "joint_names")):
            vectors: list[list[float]] = []
            for _, source_ns, message in samples:
                if start_ns <= source_ns <= end_ns:
                    names = list(getattr(message, names_attr))
                    values = list(
                        message.position if names_attr == "name" else message.positions
                    )
                    mapping = dict(zip(names, values))
                    if all(name in mapping for name in canonical_names):
                        vectors.append(
                            [float(mapping[name]) for name in canonical_names]
                        )
            if len(vectors) > 1 and any(
                max(abs(a - b) for a, b in zip(vectors[0], vector)) > 1e-4
                for vector in vectors[1:]
            ):
                return True
        return False

    for camera in profile["cameras"]:
        camera_images = images_by_camera[camera["name"]]
        camera_decoded = decoded_by_camera[camera["name"]]
        camera_times = [item[1] for item in camera_images]
        if (
            len(camera_decoded) != len(camera_images)
            or not camera_decoded
            or not all(
                frame.shape[:2] == (camera["height"], camera["width"])
                for frame in camera_decoded
            )
        ):
            continue
        rule = (
            "camera"
            if camera["name"] == timeline_camera["name"]
            else f"camera.{camera['name']}"
        )
        metric = (
            "" if camera["name"] == timeline_camera["name"] else f"{camera['name']}_"
        )
        frozen_failure, maximum_frozen_seconds = camera_freeze(
            camera_decoded, camera_times, robot_changed
        )
        result.metrics[f"{metric}maximum_frozen_seconds"] = maximum_frozen_seconds
        result.add(
            f"{rule}.frozen",
            not frozen_failure,
            f"no {camera['name']} camera freeze longer than one second occurred while robot state/action changed",
        )
        blur = [
            float(
                cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
            )
            for frame in camera_decoded
        ]
        exposure = [
            float(np.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)))
            for frame in camera_decoded
        ]
        visual_dynamics = [
            float(np.mean(cv2.absdiff(previous, current)))
            for previous, current in zip(camera_decoded, camera_decoded[1:])
        ]
        result.metrics[f"{metric}blur_p05"] = _percentile(blur, 5)
        result.metrics.update(
            {
                f"{metric}exposure_p05": _percentile(exposure, 5),
                f"{metric}exposure_p50": _percentile(exposure, 50),
                f"{metric}exposure_p95": _percentile(exposure, 95),
                f"{metric}visual_dynamics_p50": _percentile(visual_dynamics, 50),
                f"{metric}visual_dynamics_p95": _percentile(visual_dynamics, 95),
            }
        )
        result.add(
            f"{rule}.blur_baseline",
            True,
            f"{camera['name']} blur p05={result.metrics[f'{metric}blur_p05']:.3f}; advisory until HIL calibration",
            "warning",
        )
        result.add(
            f"{rule}.exposure_baseline",
            True,
            f"{camera['name']} exposure p05/p50/p95={result.metrics[f'{metric}exposure_p05']:.3f}/"
            f"{result.metrics[f'{metric}exposure_p50']:.3f}/{result.metrics[f'{metric}exposure_p95']:.3f}; advisory until HIL calibration",
            "warning",
        )
        result.add(
            f"{rule}.dynamics_baseline",
            True,
            f"{camera['name']} visual dynamics p50/p95={result.metrics[f'{metric}visual_dynamics_p50']:.3f}/"
            f"{result.metrics[f'{metric}visual_dynamics_p95']:.3f}; advisory until HIL calibration",
            "warning",
        )

    result.metrics["task_instruction"] = task["instruction"]
    return _write_result(episode_dir, manifest, result)


def _write_result(
    episode_dir: Path, manifest: dict[str, Any], result: ValidationResult
) -> ValidationResult:
    validation_dir = episode_dir / "validation"
    validation_dir.mkdir(exist_ok=True)
    payload = {
        "schema_version": "episode-validation/v1",
        "episode_id": result.episode_id,
        "artifact_hash": manifest.get("content_hash"),
        "recording_profile_id": manifest.get("recording_profile_id"),
        "recording_profile_hash": manifest.get("recording_profile_hash"),
        "task_id": manifest.get("task_id"),
        "task_catalog_hash": manifest.get("task_catalog_hash"),
        "validated_at_unix": time.time(),
        "valid": result.valid,
        "metrics": result.metrics,
        "findings": [finding.__dict__ for finding in result.findings],
    }
    (validation_dir / "validation.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    status = {
        "episode_id": result.episode_id,
        "status": "accepted" if result.valid else "rejected",
        "validated_at_unix": payload["validated_at_unix"],
        "report": "validation/validation.json",
    }
    temporary = episode_dir / "status.json.tmp"
    temporary.write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(episode_dir / "status.json")
    write_junit(validation_dir / "validation.junit.xml", result)
    return result


def write_junit(path: Path, result: ValidationResult) -> None:
    failures = sum(finding.failing for finding in result.findings)
    suite = ET.Element(
        "testsuite",
        name="episode_validation",
        tests=str(len(result.findings)),
        failures=str(failures),
    )
    for finding in result.findings:
        case = ET.SubElement(
            suite, "testcase", classname="episode_validation", name=finding.rule_id
        )
        if finding.failing:
            ET.SubElement(
                case, "failure", message=finding.summary, type=finding.severity
            ).text = finding.summary
        elif finding.severity == "warning":
            ET.SubElement(case, "system-out").text = finding.summary
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)
