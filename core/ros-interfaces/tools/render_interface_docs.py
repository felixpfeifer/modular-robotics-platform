#!/usr/bin/env python3
"""Render a review-friendly Markdown catalog from the JSON source of truth."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "contract-catalog.md",
    )
    args = parser.parse_args()

    data = json.loads(
        (ROOT / "docs/contracts/catalog.json").read_text(encoding="utf-8")
    )
    examples = json.loads(
        (ROOT / "examples/contract_examples.json").read_text(encoding="utf-8")
    )
    examples_by_type = {item["type"]: item for item in examples["examples"]}

    lines = [
        "# Platform ROS 2 contract catalog",
        "",
        f"Repository version: `{data['repository_version']}`",
        "",
    ]
    for contract in data["contracts"]:
        lines.extend(
            [
                f"## `{contract['type']}`",
                "",
                contract["purpose"],
                "",
                f"- Owner: {contract['owner']}",
                f"- Producers: {', '.join(contract['producers'])}",
                f"- Consumers: {', '.join(contract['consumers'])}",
                f"- Semantics: {contract['semantics']}",
                "",
                "Valid payload:",
                "",
                "```json",
                json.dumps(
                    examples_by_type[contract["type"]]["valid"]["payload"],
                    indent=2,
                    sort_keys=True,
                ),
                "```",
                "",
                "Invalid cases:",
                "",
            ]
        )
        for invalid in examples_by_type[contract["type"]]["invalid"]:
            lines.append(f"- {invalid['reason']}")
        lines.append("")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
