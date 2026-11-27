#!/usr/bin/env python3
"""Atomically update one stage in the verification state file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("stage")
    parser.add_argument("status", choices=("passed", "failed", "not_run"))
    args = parser.parse_args()
    data = json.loads(args.path.read_text()) if args.path.exists() else {}
    data[args.stage] = {"status": args.status}
    temporary = args.path.with_suffix(args.path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
