#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import yaml

from episode_recorder_py.configuration import recording_profile_hash
from episode_recorder_py.validation import sha256_file, validate_episode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert one legacy SQLite episode to immutable MCAP, then validate it"
    )
    parser.add_argument("--legacy-bag", required=True, type=Path)
    parser.add_argument("--dataset-dir", required=True, type=Path)
    parser.add_argument("--recording-profiles", required=True, type=Path)
    parser.add_argument("--task-catalog", required=True, type=Path)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--configuration-hash", required=True)
    parser.add_argument("--calibration-id", required=True)
    parser.add_argument("--calibration-hash", required=True)
    parser.add_argument("--producer-revision", required=True)
    parser.add_argument(
        "--operator-success",
        action="store_true",
        help="Attest that the legacy demonstration succeeded",
    )
    args = parser.parse_args()

    episode_id = str(uuid.uuid4())
    staging = args.dataset_dir / ".staging" / episode_id
    final = args.dataset_dir / "episodes" / episode_id
    if staging.exists() or final.exists():
        raise FileExistsError(episode_id)
    staging.mkdir(parents=True)
    (args.dataset_dir / "episodes").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="episode-migration-") as temporary:
        options = Path(temporary) / "convert.yaml"
        options.write_text(
            yaml.safe_dump(
                {
                    "output_bags": [
                        {
                            "uri": str(staging / "bag"),
                            "storage_id": "mcap",
                            "max_bagfile_size": 0,
                            "max_bagfile_duration": 0,
                            "all_topics": True,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        subprocess.run(
            ["ros2", "bag", "convert", "-i", str(args.legacy_bag), "-o", str(options)],
            check=True,
        )
    mcap_files = list(staging.rglob("*.mcap"))
    if len(mcap_files) != 1:
        raise RuntimeError(f"migration produced {len(mcap_files)} MCAP files")
    content_hash = sha256_file(mcap_files[0])
    now_ns = time.time_ns()
    manifest = {
        "schema_version": "episode-manifest/v1",
        "episode_id": episode_id,
        "artifact_id": episode_id,
        "content_hash": content_hash,
        "recording_profile_id": args.profile_id,
        "recording_profile_hash": recording_profile_hash(
            args.recording_profiles, args.profile_id
        ),
        "task_id": args.task_id,
        "task_catalog_hash": sha256_file(args.task_catalog),
        "workcell_id": "legacy-import",
        "configuration_hash": args.configuration_hash,
        "calibration_ids": [args.calibration_id],
        "producers": [
            {
                "component_id": "episode_recorder.legacy_migration",
                "semantic_version": "0.2.0",
                "source_revision": args.producer_revision,
                "build_id": args.producer_revision,
                "configuration_hash": args.configuration_hash,
                "calibration_id": args.calibration_id,
                "calibration_hash": args.calibration_hash,
            }
        ],
        "started_ns": now_ns,
        "finalized_ns": now_ns,
        "operator_success": args.operator_success,
        "canceled": False,
        "writer_dropped": False,
        "writer_error": False,
        "reason": "explicit legacy SQLite migration",
        "storage_id": "mcap",
    }
    (staging / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    staging.replace(final)
    result = validate_episode(
        final, args.recording_profiles, args.task_catalog, content_hash
    )
    print(f"migrated {args.legacy_bag} to {final}; valid={result.valid}")
    return 0 if result.valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
