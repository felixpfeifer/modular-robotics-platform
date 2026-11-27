import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from check_release_policy import validate  # noqa: E402


class RepositoryToolTests(unittest.TestCase):
    def test_contract_catalog_matches_repository(self):
        subprocess.run(
            [sys.executable, str(ROOT / "tools/check_contract_catalog.py")],
            check=True,
            cwd=ROOT,
        )

    def test_hash_comparison_classifies_identical_additive_and_breaking(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            baseline = {
                "repository_version": "0.1.0",
                "types": {"package/msg/One": {"source_sha256": "aaa"}},
            }
            baseline_path = work / "baseline.json"
            baseline_path.write_text(json.dumps(baseline))
            cases = (
                ("identical", baseline["types"]),
                (
                    "additive",
                    {
                        **baseline["types"],
                        "package/msg/Two": {"source_sha256": "bbb"},
                    },
                ),
                (
                    "breaking",
                    {"package/msg/One": {"source_sha256": "changed"}},
                ),
            )
            for expected, current_types in cases:
                current_path = work / f"{expected}-current.json"
                report_path = work / f"{expected}-report.json"
                current_path.write_text(
                    json.dumps(
                        {
                            "repository_version": "0.2.0",
                            "types": current_types,
                        }
                    )
                )
                subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "tools/compare_type_hashes.py"),
                        "--baseline",
                        str(baseline_path),
                        "--current",
                        str(current_path),
                        "--output",
                        str(report_path),
                    ],
                    check=True,
                )
                self.assertEqual(
                    json.loads(report_path.read_text())["classification"], expected
                )

    def test_result_writer_replaces_stale_success_for_failed_and_incomplete_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            results = Path(directory)
            output = results / "interface-test-results.json"
            output.write_text('{"status":"passed"}')
            stage_file = results / "stages.json"
            stage_file.write_text('{"build":{"status":"failed"}}')
            for status in ("failed", "incomplete"):
                subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "tools/write_test_summary.py"),
                        "--results-dir",
                        str(results),
                        "--source-dir",
                        str(ROOT),
                        "--status",
                        status,
                        "--failed-stage",
                        "build",
                        "--started-at",
                        "2026-07-23T00:00:00Z",
                        "--stage-file",
                        str(stage_file),
                    ],
                    check=True,
                )
                result = json.loads(output.read_text())
                self.assertEqual(result["status"], status)
                self.assertEqual(result["failed_stage"], "build")

    def test_release_policy_requires_minor_for_addition_and_migration_for_breaking(
        self,
    ):
        additive = {
            "classification": "additive",
            "baseline_version": "0.1.0",
        }
        self.assertTrue(validate(additive, "0.1.1", None))
        self.assertFalse(validate(additive, "0.2.0", None))

        breaking = {
            "classification": "breaking",
            "baseline_version": "0.2.0",
        }
        self.assertTrue(validate(breaking, "0.3.0", None))
        with tempfile.TemporaryDirectory() as directory:
            migration = Path(directory) / "migration.md"
            migration.write_text("# Migration")
            self.assertFalse(validate(breaking, "0.3.0", migration))


if __name__ == "__main__":
    unittest.main()
