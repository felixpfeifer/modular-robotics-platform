import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mrp_app import configbundle
from mrp_app.catalog import DEFAULT_SPEC
from mrp_app.runtime import DemoRuntime
from mrp_app.service import AppError, Application

CALIBRATION = "joints:\n" + "".join(
    f"  {n}: {{id: {i}, homing_offset: {i * 10}}}\n"
    for i, n in enumerate(
        ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"], 1
    )
)
ROBOT = {
    "schema_version": "robot-profile/v1",
    "id": "so101",
    "label": "SO-101",
    "joint_names": ["a", "b"],
    "topics": {"joint_states": "/joint_states"},
}
REAL = {
    "leader": "real",
    "follower": "real",
    "camera": "synthetic",
    "task_id": "free_teleop",
    "devices": {
        "leader": {"port": "/dev/ttyACM1", "calibration": "leader.yaml"},
        "follower": {"port": "/dev/ttyACM0", "calibration": "follower.yaml"},
    },
}


def project(name="Cell A", spec=None, preset="mock-so101", layout=None):
    return {"name": name, "cell_spec": spec or dict(DEFAULT_SPEC), "preset": preset, "cell_layout": layout}


def repack(data, edit):
    """Rewrite a bundle's files with ``edit(files)`` (keeping the old manifest unless edit changes it)."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        files = {m.name: archive.extractfile(m).read() for m in archive}
    edit(files)
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return out.getvalue()


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, data, name="bundle.tar.gz"):
        path = self.dir / name
        path.write_bytes(data)
        return path

    def build(self, **kw):
        args = {
            "calibrations": {"leader.yaml": CALIBRATION, "follower.yaml": CALIBRATION},
            "projects": [project(), project("Real", REAL, "real-so101")],
            "robots": {"so101": ROBOT},
            "app_version": "0.1.0",
        }
        return configbundle.build_bundle(**{**args, **kw})

    def read(self, data, calibrations=None, robots=None, names=()):
        return configbundle.read_bundle(
            self.write(data), calibrations or {}, {"so101": ROBOT} if robots is None else robots, names
        )

    def test_round_trip_is_valid_and_lists_everything(self):
        report = self.read(self.build())
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual([c["status"] for c in report["items"]["calibrations"]], ["new", "new"])
        self.assertEqual(report["items"]["robots"][0]["status"], "known")
        self.assertEqual(len(report["payload"]["projects"]), 2)
        self.assertTrue(any("USB ports" in w for w in report["warnings"]))

    def test_conflicting_and_identical_calibrations_are_reported(self):
        other = CALIBRATION.replace("homing_offset: 10", "homing_offset: 11")
        report = self.read(self.build(), {"leader.yaml": other, "follower.yaml": CALIBRATION})
        status = {c["name"]: c["status"] for c in report["items"]["calibrations"]}
        self.assertEqual(status, {"follower.yaml": "identical", "leader.yaml": "conflict"})

    def test_existing_project_names_are_renamed_not_replaced(self):
        report = self.read(self.build(), names=["cell a"])
        self.assertEqual(report["items"]["projects"][0]["name"], "Cell A (imported)")

    def test_tampered_file_fails_the_checksum(self):
        data = repack(
            self.build(),
            lambda f: f.update({"calibration/leader.yaml": CALIBRATION.replace("10", "99").encode()}),
        )
        with self.assertRaisesRegex(configbundle.BundleError, "checksum"):
            self.read(data)

    def test_unlisted_and_unexpected_files_are_rejected(self):
        extra = repack(self.build(), lambda f: f.update({"projects/9.json": b"{}"}))
        with self.assertRaisesRegex(configbundle.BundleError, "manifest"):
            self.read(extra)
        evil = repack(self.build(), lambda f: f.update({"../evil.sh": b"x"}))
        with self.assertRaisesRegex(configbundle.BundleError, "unexpected file"):
            self.read(evil)

    def test_links_and_non_archives_are_rejected(self):
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w:gz") as archive:
            info = tarfile.TarInfo("manifest.json")
            info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
            archive.addfile(info)
        with self.assertRaisesRegex(configbundle.BundleError, "plain file"):
            self.read(out.getvalue())
        with self.assertRaisesRegex(configbundle.BundleError, "readable"):
            self.read(b"not a tarball")

    def test_oversize_file_is_rejected(self):
        data = repack(
            self.build(), lambda f: f.update({"calibration/big.yaml": b"x" * (configbundle.MAX_FILE + 1)})
        )
        with self.assertRaisesRegex(configbundle.BundleError, "too large"):
            self.read(data)

    def resign(self, data, edit):
        """Edit files and keep the manifest consistent, to test content validation rather than checksums."""

        def apply(files):
            edit(files)
            manifest = json.loads(files["manifest.json"])
            manifest["files"] = {
                n: {"sha256": configbundle._digest(c), "bytes": len(c)}
                for n, c in files.items()
                if n != "manifest.json"
            }
            files["manifest.json"] = json.dumps(manifest).encode()

        return repack(data, apply)

    def test_invalid_contents_are_errors_and_withhold_the_payload(self):
        bad_cal = self.resign(
            self.build(), lambda f: f.update({"calibration/leader.yaml": b"joints:\n  evil: 1\n"})
        )
        report = self.read(bad_cal)
        self.assertFalse(report["valid"])
        self.assertIsNone(report["payload"])
        self.assertTrue(any("leader.yaml" in e for e in report["errors"]))

        def bad_project(files):
            doc = json.loads(files["projects/1.json"])
            doc["cell"]["leader"] = "does-not-exist"
            files["projects/1.json"] = json.dumps(doc).encode()

        report = self.read(self.resign(self.build(), bad_project))
        self.assertTrue(any("Unknown leader" in e for e in report["errors"]))

        def wrong_preset(files):
            doc = json.loads(files["projects/1.json"])
            doc["preset"] = "sim-so101"
            files["projects/1.json"] = json.dumps(doc).encode()

        report = self.read(self.resign(self.build(), wrong_preset))
        self.assertTrue(any("does not match" in e for e in report["errors"]))

    def test_unknown_robot_is_a_warning_not_an_error(self):
        report = self.read(self.build(), robots={})
        self.assertTrue(report["valid"])
        self.assertTrue(any("not installed" in w for w in report["warnings"]))


class ImportApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = Application(self.root, DemoRuntime(), agent_url="http://agent.invalid")
        self.stored = {}
        self.calls = []

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def fake_remote(self, base, path, payload=None, timeout=10):
        self.calls.append(path)
        if path == "/api/v1/calibrations":
            return dict(self.stored)
        if path == "/api/v1/robots":
            return {"so101": ROBOT}
        if path == "/api/v1/devices/import-calibration":
            self.stored[payload["name"]] = payload["content"]
            return {"name": payload["name"]}
        raise AssertionError(path)

    def bundle(self):
        data = configbundle.build_bundle(
            {"leader.yaml": CALIBRATION}, [project("Shared", REAL, "real-so101")], {"so101": ROBOT}, "0.1.0"
        )
        path = self.root / "in.tar.gz"
        path.write_bytes(data)
        return path

    def test_validate_does_not_write_and_import_adds_project_and_calibration(self):
        with patch("mrp_app.service.remote_json", self.fake_remote):
            report = self.app.config_import(self.bundle())
            self.assertFalse(report["applied"])
            self.assertEqual(self.app.store.rows("SELECT id FROM projects"), [])
            self.assertEqual(self.stored, {})
            done = self.app.config_import(self.bundle(), apply=True)
        self.assertTrue(done["applied"])
        self.assertEqual(done["result"]["calibrations_stored"], ["leader.yaml"])
        self.assertEqual(self.app.store.rows("SELECT name,preset FROM projects")[0]["preset"], "real-so101")
        self.assertNotIn("payload", done)

    def test_existing_calibration_is_kept_unless_overwrite_is_chosen(self):
        self.stored["leader.yaml"] = CALIBRATION.replace("homing_offset: 10", "homing_offset: 12")
        with patch("mrp_app.service.remote_json", self.fake_remote):
            kept = self.app.config_import(self.bundle(), apply=True)
            self.assertEqual(kept["result"]["calibrations_kept"], ["leader.yaml"])
            self.assertIn("homing_offset: 12", self.stored["leader.yaml"])
            over = self.app.config_import(self.bundle(), apply=True, overwrite_calibrations=True)
        self.assertEqual(over["result"]["calibrations_stored"], ["leader.yaml"])
        self.assertIn("homing_offset: 10", self.stored["leader.yaml"])

    def test_invalid_bundle_changes_nothing(self):
        path = self.root / "bad.tar.gz"
        path.write_bytes(b"garbage")
        with patch("mrp_app.service.remote_json", self.fake_remote), self.assertRaises(AppError):
            self.app.config_import(path, apply=True)
        self.assertEqual(self.app.store.rows("SELECT id FROM projects"), [])

    def test_export_saves_to_user_data_and_can_be_listed_and_deleted(self):
        self.stored["leader.yaml"] = CALIBRATION
        self.app.create_project({"name": "One"})
        with patch("mrp_app.service.remote_json", self.fake_remote):
            result = self.app.config_export()
        self.assertEqual(result["counts"], {"calibrations": 1, "projects": 1, "robots": 1})
        self.assertTrue((self.root / "user_data/backups" / result["name"]).is_file())
        self.assertEqual([b["name"] for b in self.app.config_backups()["backups"]], [result["name"]])
        with self.assertRaises(AppError):
            self.app.config_backup_path("../application.sqlite3")
        self.app.delete_config_backup(result["name"])
        self.assertEqual(self.app.config_backups()["backups"], [])

    def test_exported_bundle_imports_cleanly(self):
        self.app.create_project({"name": "One"})
        with patch("mrp_app.service.remote_json", self.fake_remote):
            name = self.app.config_export()["name"]
            report = self.app.config_import(self.app.config_backup_path(name))
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["items"]["projects"][0]["name"], "One (imported)")


if __name__ == "__main__":
    unittest.main()
