#!/usr/bin/env python3
"""Atomically write the mounted top-level verification result."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


def git_commit(source: Path) -> str:
    value = os.getenv("CI_COMMIT_SHA")
    if value:
        return value
    result = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def git_dirty(source: Path) -> bool | None:
    result = subprocess.run(
        ["git", "-C", str(source), "status", "--porcelain"],
        text=True,
        capture_output=True,
    )
    return bool(result.stdout.strip()) if result.returncode == 0 else None


def junit_counts(results: Path) -> tuple[int, int]:
    total = failed = 0
    for path in results.glob("junit/**/*.xml"):
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
        for suite in suites:
            total += int(suite.attrib.get("tests", 0))
            failed += int(suite.attrib.get("failures", 0))
            failed += int(suite.attrib.get("errors", 0))
    return total, failed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument(
        "--status", required=True, choices=("passed", "failed", "incomplete")
    )
    parser.add_argument("--failed-stage", default="")
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--stage-file", type=Path)
    args = parser.parse_args()

    args.results_dir.mkdir(parents=True, exist_ok=True)
    stages = {}
    if args.stage_file and args.stage_file.exists():
        stages = json.loads(args.stage_file.read_text(encoding="utf-8"))
    total, failed = junit_counts(args.results_dir)
    reports = sorted(
        str(path.relative_to(args.results_dir))
        for path in args.results_dir.rglob("*")
        if path.is_file()
        and path.name not in {"interface-test-results.json", ".gitkeep"}
    )
    result = {
        "schema_version": "1.0",
        "status": args.status,
        "failed_stage": args.failed_stage or None,
        "git_commit": git_commit(args.source_dir),
        "git_dirty": git_dirty(args.source_dir),
        "container_image": os.getenv("CONTAINER_IMAGE", "unknown"),
        "ros_distribution": os.getenv("ROS_DISTRO", "unknown"),
        "rmw_implementation": os.getenv("RMW_IMPLEMENTATION", "unknown"),
        "started_at": args.started_at,
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "build": stages.get("build", {"status": "not_run"}),
        "tests": {
            **stages.get("tests", {"status": "not_run"}),
            "total": total,
            "failed": failed,
        },
        "acceptance": stages.get("acceptance", {"status": "not_run"}),
        "compatibility": stages.get("compatibility", {"status": "not_run"}),
        "report_paths": reports,
    }
    environment = {
        "schema_version": "1.0",
        "os": platform.platform(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "ros_distribution": result["ros_distribution"],
        "configured_rmw": result["rmw_implementation"],
        "ros_domain_id": os.getenv("ROS_DOMAIN_ID", "unset"),
        "container_image": result["container_image"],
        "git_commit": result["git_commit"],
    }
    env_path = args.results_dir / "environment.json"
    env_tmp = env_path.with_suffix(".json.tmp")
    env_tmp.write_text(json.dumps(environment, indent=2, sort_keys=True) + "\n")
    env_tmp.replace(env_path)

    target = args.results_dir / "interface-test-results.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    temporary.replace(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
