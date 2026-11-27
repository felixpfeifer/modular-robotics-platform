#!/usr/bin/env python3
"""Check that a proposed Commitizen version is strong enough for hash changes."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SEMVER = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


def version(value: str) -> tuple[int, int, int]:
    match = SEMVER.fullmatch(value)
    if not match:
        raise ValueError(f"not a SemVer 2 version: {value}")
    return tuple(int(match.group(name)) for name in ("major", "minor", "patch"))


def validate(report: dict, proposed: str, migration_record: Path | None) -> list[str]:
    errors: list[str] = []
    classification = report["classification"]
    baseline_text = report.get("baseline_version")
    if classification == "initial" or not baseline_text:
        return errors
    baseline = version(baseline_text)
    next_version = version(proposed)
    if next_version <= baseline:
        errors.append(f"proposed version {proposed} does not advance {baseline_text}")
        return errors
    if classification == "additive":
        if next_version[0] == baseline[0] and next_version[1] == baseline[1]:
            errors.append("additive public types require at least a minor version")
    elif classification == "breaking":
        if baseline[0] == 0:
            strong_enough = (
                next_version[0] > baseline[0] or next_version[1] > baseline[1]
            )
        else:
            strong_enough = next_version[0] > baseline[0]
        if not strong_enough:
            errors.append(
                "breaking contract changes require the declared breaking bump"
            )
        if migration_record is None or not migration_record.is_file():
            errors.append("breaking contract changes require a migration ADR")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--proposed-version", required=True)
    parser.add_argument("--migration-record", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    errors = validate(report, args.proposed_version, args.migration_record)
    if errors:
        for error in errors:
            print(f"release policy: {error}")
        return 1
    print(
        f"release policy: {report['classification']} is compatible with "
        f"{args.proposed_version}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
