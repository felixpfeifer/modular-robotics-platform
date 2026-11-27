#!/usr/bin/env python3
"""Generate ROS type hashes, with deterministic source hashes for bootstrap."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = tuple(ROOT.glob("platform_*_interfaces"))


def types() -> list[tuple[str, Path]]:
    result: list[tuple[str, Path]] = []
    for package in sorted(PACKAGES):
        for kind in ("msg", "srv", "action"):
            directory = package / kind
            if directory.exists():
                for path in sorted(directory.glob(f"*.{kind}")):
                    result.append((f"{package.name}/{kind}/{path.stem}", path))
    return result


def normalized_source(path: Path) -> bytes:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(" ".join(line.split()))
    return ("\n".join(lines) + "\n").encode()


def description_path(type_name: str, prefixes: list[Path]) -> Path | None:
    package, kind, name = type_name.split("/")
    for prefix in prefixes:
        candidate = prefix / "share" / package / kind / f"{name}.json"
        if candidate.exists():
            return candidate
    return None


def load_ros_description(type_name: str, prefixes: list[Path]) -> tuple[str, dict]:
    path = description_path(type_name, prefixes)
    if path is None:
        raise FileNotFoundError(f"installed type description not found for {type_name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    for item in data["type_hashes"]:
        if item["type_name"] == type_name:
            return item["hash_string"].lower(), data["type_description_msg"]
    raise RuntimeError(f"generated type description has no hash for {type_name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--descriptions-output", type=Path)
    parser.add_argument("--install-prefix", action="append", type=Path, default=[])
    parser.add_argument("--require-ros", action="store_true")
    args = parser.parse_args()

    prefixes = list(args.install_prefix)
    prefixes.extend(
        Path(item)
        for item in os.getenv("AMENT_PREFIX_PATH", "").split(os.pathsep)
        if item
    )

    entries = {}
    descriptions = {}
    qualified = True
    for type_name, path in types():
        source_hash = hashlib.sha256(normalized_source(path)).hexdigest()
        entry = {
            "source_sha256": source_hash,
            "definition": str(path.relative_to(ROOT)),
        }
        try:
            generated_hash, description = load_ros_description(type_name, prefixes)
            entry["ros_type_hash"] = generated_hash
            descriptions[type_name] = description
        except (FileNotFoundError, KeyError, RuntimeError) as error:
            qualified = False
            if args.require_ros:
                raise SystemExit(str(error)) from error
        entries[type_name] = entry

    output = {
        "schema_version": "1.0",
        "repository_version": (ROOT / "VERSION").read_text().strip(),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "qualified": qualified,
        "types": entries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    temporary.replace(args.output)
    if args.descriptions_output:
        args.descriptions_output.parent.mkdir(parents=True, exist_ok=True)
        descriptions_temp = args.descriptions_output.with_suffix(
            args.descriptions_output.suffix + ".tmp"
        )
        descriptions_temp.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "repository_version": output["repository_version"],
                    "types": descriptions,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        descriptions_temp.replace(args.descriptions_output)
    print(f"wrote {len(entries)} type hashes to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
