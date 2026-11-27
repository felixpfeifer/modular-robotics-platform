#!/usr/bin/env python3
"""Generate a minimal SPDX SBOM and declared dependency license inventory."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    packages = []
    dependencies: set[str] = set()
    for manifest_path in sorted(ROOT.glob("platform_*_interfaces/package.xml")):
        root = ET.parse(manifest_path).getroot()
        name = root.findtext("name", "")
        version = root.findtext("version", "")
        license_name = root.findtext("license", "NOASSERTION")
        package_dependencies = sorted(
            {
                child.text.strip()
                for child in root
                if child.tag.endswith("depend") and child.text
            }
        )
        dependencies.update(package_dependencies)
        packages.append(
            {
                "SPDXID": f"SPDXRef-Package-{name}",
                "name": name,
                "versionInfo": version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": license_name,
                "licenseDeclared": license_name,
                "copyrightText": "NOASSERTION",
            }
        )

    namespace_seed = hashlib.sha256(f"{packages!r}".encode()).hexdigest()
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "platform-ros-interfaces",
        "documentNamespace": f"https://global-dynamics.example/spdx/{namespace_seed}",
        "creationInfo": {
            "created": dt.datetime.now(dt.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "creators": ["Tool: generate_release_evidence.py"],
        },
        "packages": packages,
    }
    (args.output_dir / "sbom.spdx.json").write_text(
        json.dumps(sbom, indent=2, sort_keys=True) + "\n"
    )

    known_licenses = {
        "ament_cmake": "Apache-2.0",
        "builtin_interfaces": "Apache-2.0",
        "diagnostic_msgs": "Apache-2.0",
        "geometry_msgs": "Apache-2.0",
        "platform_common_interfaces": "Apache-2.0",
        "rosidl_default_generators": "Apache-2.0",
        "rosidl_default_runtime": "Apache-2.0",
        "std_msgs": "Apache-2.0",
        "unique_identifier_msgs": "BSD-3-Clause",
    }
    inventory = {
        "schema_version": "1.0",
        "dependencies": [
            {
                "name": dependency,
                "declared_license": known_licenses.get(dependency, "REVIEW_REQUIRED"),
            }
            for dependency in sorted(dependencies)
        ],
    }
    (args.output_dir / "license-inventory.json").write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
