"""Download a LeRobot checkpoint from the Hugging Face Hub into the training runs volume."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import uuid
from pathlib import Path

from . import job

REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*")
REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,127}")
SUBFOLDER = re.compile(r"[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Import a LeRobot checkpoint from the Hugging Face Hub"
    )
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--revision", default=None)
    parser.add_argument("--subfolder", default="")
    parser.add_argument("--label", default="")
    args = parser.parse_args(argv)
    if not REPO.fullmatch(args.repo_id):
        parser.error("repo-id must use namespace/name syntax")
    try:
        if str(uuid.UUID(args.run_id)) != args.run_id:
            raise ValueError
    except ValueError:
        parser.error("run-id must be a canonical UUID")
    if args.revision is not None and (
        not REVISION.fullmatch(args.revision) or ".." in args.revision
    ):
        parser.error("invalid revision")
    if args.subfolder and (
        not SUBFOLDER.fullmatch(args.subfolder) or ".." in args.subfolder.split("/")
    ):
        parser.error("invalid subfolder")
    if len(args.label) > 80 or any(ord(c) < 32 for c in args.label):
        parser.error("label must be at most 80 printable characters")
    return args


def download(args, destination: Path, token):
    # huggingface_hub reads the offline switch at import time.
    os.environ["HF_HUB_OFFLINE"] = "0"
    from huggingface_hub import snapshot_download

    pattern = f"{args.subfolder}/*" if args.subfolder else None
    return Path(
        snapshot_download(
            repo_id=args.repo_id,
            revision=args.revision,
            token=token,
            local_dir=str(destination),
            allow_patterns=[pattern] if pattern else None,
        )
    )


def run(args, fetch=download):
    runs = args.runs_dir.expanduser().resolve()
    runs.mkdir(parents=True, exist_ok=True)
    run_dir = runs / args.run_id
    run_dir.mkdir(exist_ok=False)
    meta = {
        "schema_version": "mrp-training-job/v1",
        "run_id": args.run_id,
        "status": "running",
        "started_unix": time.time(),
        "framework": "lerobot",
        "imported": True,
        "label": args.label,
        "source": {
            "repo_id": args.repo_id,
            "revision": args.revision,
            "subfolder": args.subfolder,
        },
    }
    job.write_json(run_dir / "job.json", meta)
    scratch = run_dir / ".download"
    final = run_dir / "output" / "checkpoints" / "last" / "pretrained_model"
    try:
        root = fetch(args, scratch, os.environ.get("HF_TOKEN") or None)
        source = (
            (Path(root) / args.subfolder).resolve()
            if args.subfolder
            else Path(root).resolve()
        )
        if not source.is_relative_to(scratch.resolve()):
            raise ValueError("subfolder escapes the download directory")
        if any(p.is_symlink() for p in source.rglob("*")):
            raise ValueError("checkpoint may not contain symbolic links")
        info = job.inspect_base_model(source)
        final.parent.mkdir(parents=True)
        shutil.copytree(source, final, ignore=shutil.ignore_patterns(".cache"))
        meta.update(
            {
                "status": "complete",
                "finished_unix": time.time(),
                "exit_code": 0,
                "checkpoint": str(final),
                "base_model": info,
                "policy": json.loads((final / "config.json").read_text()).get("type"),
            }
        )
    except (
        Exception
    ) as error:  # Report the failure without echoing request details or credentials.
        meta.update(
            {
                "status": "failed",
                "finished_unix": time.time(),
                "error": type(error).__name__,
            }
        )
        print(f"Model import failed ({type(error).__name__}).", file=sys.stderr)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    job.write_json(run_dir / "job.json", meta)
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "status": meta["status"],
                "run_dir": str(run_dir),
                "checkpoint": meta.get("checkpoint"),
            }
        ),
        flush=True,
    )
    return 0 if meta["status"] == "complete" else 1
