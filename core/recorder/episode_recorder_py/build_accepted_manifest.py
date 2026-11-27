#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create an immutable selection of accepted raw episodes"
    )
    parser.add_argument("--dataset-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    episodes = []
    for episode in (args.dataset_dir / "episodes").glob("*"):
        try:
            if str(uuid.UUID(episode.name)) != episode.name or episode.is_symlink():
                continue
        except ValueError:
            continue
        try:
            status = json.loads((episode / "status.json").read_text(encoding="utf-8"))
            manifest = json.loads(
                (episode / "manifest.json").read_text(encoding="utf-8")
            )
            validation = json.loads(
                (episode / "validation/validation.json").read_text(encoding="utf-8")
            )
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        if status.get("status") == "accepted" and validation.get("valid"):
            episodes.append(
                {
                    "episode_id": episode.name,
                    "content_hash": manifest["content_hash"],
                    "started_ns": manifest["started_ns"],
                }
            )
    episodes.sort(key=lambda item: (item["started_ns"], item["episode_id"]))
    payload = {"schema_version": "accepted-episodes/v1", "episodes": episodes}
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"selected {len(episodes)} accepted episodes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
