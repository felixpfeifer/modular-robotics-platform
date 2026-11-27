#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import time
import uuid
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Expire finalized rejected episodes; dry-run by default"
    )
    parser.add_argument("--dataset-dir", required=True, type=Path)
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Actually remove eligible rejected directories",
    )
    args = parser.parse_args()
    cutoff = time.time() - args.retention_days * 86400
    eligible = 0
    episodes_root = (args.dataset_dir / "episodes").resolve()
    for episode in sorted((args.dataset_dir / "episodes").glob("*")):
        try:
            uuid.UUID(episode.name)
        except ValueError:
            continue
        if episode.is_symlink() or episode.resolve().parent != episodes_root:
            continue
        status_path = episode / "status.json"
        manifest_path = episode / "manifest.json"
        if not status_path.is_file() or not manifest_path.is_file():
            continue
        status = json.loads(status_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("episode_id") != episode.name or not manifest.get(
            "finalized_ns"
        ):
            continue
        if (
            status.get("status") != "rejected"
            or float(status.get("validated_at_unix", time.time())) > cutoff
        ):
            continue
        eligible += 1
        print(("DELETE " if args.delete else "WOULD DELETE ") + str(episode))
        if args.delete:
            shutil.rmtree(episode)
    print(
        f"eligible rejected episodes: {eligible}; deleted: {eligible if args.delete else 0}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
