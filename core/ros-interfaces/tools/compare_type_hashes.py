#!/usr/bin/env python3
"""Classify current interface shapes against a released hash baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def comparable_hash(entry: dict) -> str:
    return entry.get("ros_type_hash", entry["source_sha256"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fail-on-breaking", action="store_true")
    args = parser.parse_args()

    current = load(args.current)
    current_types = current["types"]
    if args.baseline and args.baseline.exists():
        baseline = load(args.baseline)
        baseline_types = baseline["types"]
        identical = sorted(
            name
            for name in current_types.keys() & baseline_types.keys()
            if comparable_hash(current_types[name])
            == comparable_hash(baseline_types[name])
        )
        changed = sorted(
            name
            for name in current_types.keys() & baseline_types.keys()
            if comparable_hash(current_types[name])
            != comparable_hash(baseline_types[name])
        )
        added = sorted(current_types.keys() - baseline_types.keys())
        removed = sorted(baseline_types.keys() - current_types.keys())
        classification = (
            "breaking" if changed or removed else ("additive" if added else "identical")
        )
        baseline_version = baseline.get("repository_version")
    else:
        identical, changed, removed = [], [], []
        added = sorted(current_types)
        classification = "initial"
        baseline_version = None

    report = {
        "schema_version": "1.0",
        "status": "failed" if classification == "breaking" else "passed",
        "classification": classification,
        "baseline_version": baseline_version,
        "current_version": current.get("repository_version"),
        "identical": identical,
        "added": added,
        "changed": changed,
        "removed": removed,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    temp.replace(args.output)
    print(
        f"compatibility: {classification}; identical={len(identical)}, "
        f"added={len(added)}, changed={len(changed)}, removed={len(removed)}"
    )
    return 1 if args.fail_on_breaking and classification == "breaking" else 0


if __name__ == "__main__":
    raise SystemExit(main())
