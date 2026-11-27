#!/usr/bin/env python3
"""Validate repository policy without requiring a host ROS installation."""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = (
    "platform_common_interfaces",
    "platform_device_interfaces",
    "platform_control_interfaces",
    "platform_episode_interfaces",
)
DOMAIN_PACKAGES = set(PACKAGES[1:])
INTERFACE_DIRS = {"msg", "srv", "action"}
TYPE_NAME = re.compile(r"^[A-Z][A-Za-z0-9]*$")
FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
CONSTANT_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def discover_interfaces() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for package in PACKAGES:
        for kind in sorted(INTERFACE_DIRS):
            directory = ROOT / package / kind
            if not directory.exists():
                continue
            for path in sorted(directory.glob(f"*.{kind}")):
                found[f"{package}/{kind}/{path.stem}"] = path
    return found


def parse_dependencies(package_xml: Path) -> set[str]:
    root = ET.parse(package_xml).getroot()
    tags = {
        "depend",
        "build_depend",
        "build_export_depend",
        "exec_depend",
        "test_depend",
    }
    return {
        element.text.strip()
        for element in root
        if element.tag in tags and element.text and element.text.strip()
    }


def validate_field_syntax(type_name: str, path: Path, errors: list[str]) -> None:
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.split("#", 1)[0].strip()
        if not line or line == "---":
            continue
        parts = line.split()
        if len(parts) != 2:
            errors.append(
                f"{path.relative_to(ROOT)}:{number}: expected '<type> <name>'"
            )
            continue
        field_type, field_name = parts
        is_constant = "=" in field_name
        name = field_name.split("=", 1)[0]
        pattern = CONSTANT_NAME if is_constant else FIELD_NAME
        if not pattern.fullmatch(name):
            errors.append(
                f"{path.relative_to(ROOT)}:{number}: invalid "
                f"{'constant' if is_constant else 'field'} name {name!r}"
            )
        base_type = field_type.split("[", 1)[0]
        if base_type in {"string", "wstring"}:
            errors.append(
                f"{path.relative_to(ROOT)}:{number}: {name} uses an unbounded string"
            )
        if field_type.endswith("[]") or "[<=]" in field_type:
            errors.append(
                f"{path.relative_to(ROOT)}:{number}: {name} uses an unbounded sequence"
            )

    if not TYPE_NAME.fullmatch(type_name):
        errors.append(
            f"{path.relative_to(ROOT)}: invalid interface type name {type_name!r}"
        )


def main() -> int:
    errors: list[str] = []
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    interfaces = discover_interfaces()

    catalog_data = load_json(ROOT / "docs/contracts/catalog.json")
    examples_data = load_json(ROOT / "examples/contract_examples.json")
    assert isinstance(catalog_data, dict)
    assert isinstance(examples_data, dict)
    catalog_entries = catalog_data.get("contracts", [])
    example_entries = examples_data.get("examples", [])
    catalog = {entry.get("type"): entry for entry in catalog_entries}
    examples = {entry.get("type"): entry for entry in example_entries}

    if catalog_data.get("repository_version") != version:
        errors.append("catalog repository_version does not match VERSION")

    disk_types = set(interfaces)
    if set(catalog) != disk_types:
        missing = sorted(disk_types - set(catalog))
        extra = sorted(set(catalog) - disk_types)
        if missing:
            errors.append(f"catalog is missing types: {', '.join(missing)}")
        if extra:
            errors.append(f"catalog contains unknown types: {', '.join(extra)}")
    if set(examples) != disk_types:
        missing = sorted(disk_types - set(examples))
        extra = sorted(set(examples) - disk_types)
        if missing:
            errors.append(f"examples are missing types: {', '.join(missing)}")
        if extra:
            errors.append(f"examples contain unknown types: {', '.join(extra)}")

    for contract_type, entry in catalog.items():
        for key in ("owner", "producers", "consumers", "purpose", "semantics"):
            if not entry.get(key):
                errors.append(f"{contract_type}: catalog field {key!r} is required")
        if not isinstance(entry.get("producers"), list):
            errors.append(f"{contract_type}: producers must be a list")
        if not isinstance(entry.get("consumers"), list):
            errors.append(f"{contract_type}: consumers must be a list")

    for contract_type, entry in examples.items():
        valid = entry.get("valid")
        invalid = entry.get("invalid")
        if not isinstance(valid, dict) or "payload" not in valid:
            errors.append(f"{contract_type}: one valid payload is required")
        if not isinstance(invalid, list) or len(invalid) < 2:
            errors.append(
                f"{contract_type}: at least two invalid payloads are required"
            )
        elif any("reason" not in item or "payload" not in item for item in invalid):
            errors.append(
                f"{contract_type}: each invalid example needs reason and payload"
            )

    for contract_type, path in interfaces.items():
        validate_field_syntax(path.stem, path, errors)
        cmake = (ROOT / contract_type.split("/", 1)[0] / "CMakeLists.txt").read_text(
            encoding="utf-8"
        )
        relative_definition = "/".join(contract_type.split("/")[1:])
        suffix = path.suffix
        expected = f'"{relative_definition}{suffix}"'
        if expected not in cmake:
            errors.append(f"{contract_type}: {expected} is absent from CMakeLists.txt")

    for package in PACKAGES:
        package_dir = ROOT / package
        manifest = ET.parse(package_dir / "package.xml").getroot()
        manifest_name = manifest.findtext("name")
        manifest_version = manifest.findtext("version")
        if manifest_name != package:
            errors.append(f"{package}: package.xml name is {manifest_name!r}")
        if manifest_version != version:
            errors.append(
                f"{package}: package.xml version {manifest_version!r} != {version!r}"
            )
        dependencies = parse_dependencies(package_dir / "package.xml")
        first_party = {
            dependency
            for dependency in dependencies
            if dependency.startswith("platform_")
        }
        if package == "platform_common_interfaces" and first_party:
            errors.append(f"{package}: common must not have first-party dependencies")
        if package in DOMAIN_PACKAGES:
            forbidden = first_party - {"platform_common_interfaces"}
            if forbidden:
                errors.append(
                    f"{package}: forbidden domain dependency: {', '.join(sorted(forbidden))}"
                )
        if "rosidl_default_runtime" not in dependencies:
            errors.append(f"{package}: rosidl_default_runtime dependency is required")

    cz_text = (ROOT / ".cz.toml").read_text(encoding="utf-8")
    if f'version = "{version}"' not in cz_text:
        errors.append(".cz.toml version does not match VERSION")
    for package in PACKAGES:
        if f'"{package}/package.xml:version"' not in cz_text:
            errors.append(f".cz.toml does not update {package}/package.xml")

    if errors:
        print("Contract validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(
        f"Contract validation passed: {len(interfaces)} public types, "
        f"{len(PACKAGES)} packages, version {version}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
