"""Project management, cell layouts and the recorded-episode library."""

import copy
import hashlib
import json
import struct
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from mrp_app import layout as cell_layout
from mrp_app import mcap
from mrp_app.runtime import DemoRuntime
from mrp_app.service import AppError, Application
from test_api_contract import ApiTestCase


def record(opcode, body):
    return struct.pack("<BQ", opcode, len(body)) + body


def string(text):
    raw = text.encode()
    return struct.pack("<I", len(raw)) + raw


def build_mcap(topics, start=1_000_000_000, end=3_500_000_000, summary=True):
    """Smallest valid MCAP with a summary section: schemas, channels, statistics."""
    out = bytearray(mcap.MAGIC)
    out += record(0x01, string("ros2") + string("test"))  # header
    summary_start = len(out)
    body = bytearray()
    counts = bytearray()
    for index, (topic, schema, messages) in enumerate(topics, start=1):
        body += record(
            0x03, struct.pack("<H", index) + string(schema) + string("ros2msg") + struct.pack("<I", 0)
        )
        body += record(
            0x04, struct.pack("<HH", index, index) + string(topic) + string("cdr") + struct.pack("<I", 0)
        )
        counts += struct.pack("<HQ", index, messages)
    total = sum(t[2] for t in topics)
    body += record(
        0x0B,
        struct.pack("<QHIIIIQQ", total, len(topics), len(topics), 0, 0, 1, start, end)
        + struct.pack("<I", len(counts))
        + bytes(counts),
    )
    out += body if summary else b""
    out += record(0x02, struct.pack("<QQI", summary_start if summary else 0, 0, 0))
    out += mcap.MAGIC
    return bytes(out)


class McapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "a.mcap"

    def tearDown(self):
        self.temp.cleanup()

    def test_summary_lists_topics_counts_and_duration(self):
        self.path.write_bytes(
            build_mcap(
                [
                    ("/webcam/image/compressed", "sensor_msgs/msg/CompressedImage", 75),
                    ("/joint_states", "sensor_msgs/msg/JointState", 150),
                ]
            )
        )
        info = mcap.summarize(self.path)
        self.assertTrue(info["has_summary"])
        self.assertEqual(info["message_count"], 225)
        self.assertEqual(info["duration_s"], 2.5)
        self.assertEqual([t["topic"] for t in info["topics"]], ["/joint_states", "/webcam/image/compressed"])
        self.assertEqual(info["topics"][0]["messages"], 150)
        self.assertEqual(info["topics"][0]["type"], "sensor_msgs/msg/JointState")

    def test_missing_summary_is_reported_not_scanned(self):
        self.path.write_bytes(build_mcap([("/a", "x/msg/Y", 1)], summary=False))
        info = mcap.summarize(self.path)
        self.assertFalse(info["has_summary"])
        self.assertEqual(info["topics"], [])

    def test_unfinished_or_foreign_files_are_rejected(self):
        data = build_mcap([("/a", "x/msg/Y", 1)])
        for broken in (data[:-8], b"not an mcap file" * 10, data[:20]):
            self.path.write_bytes(broken)
            with self.assertRaises(mcap.McapError):
                mcap.summarize(self.path)


class LayoutTests(unittest.TestCase):
    def test_every_template_is_valid_and_normalised(self):
        for key, template in cell_layout.TEMPLATES.items():
            self.assertEqual(cell_layout.validate_layout(template["layout"]), template["layout"], key)

    def test_rejects_bad_input(self):
        base = copy.deepcopy(cell_layout.TEMPLATES["so101_tabletop"]["layout"])

        def broken(mutate):
            layout = copy.deepcopy(base)
            mutate(layout)
            with self.assertRaises(cell_layout.LayoutError):
                cell_layout.validate_layout(layout)

        broken(lambda x: x["modules"].append(dict(x["modules"][0])))  # duplicate id
        broken(lambda x: x["modules"][1].update(name=x["modules"][2]["name"].upper()))  # duplicate name
        broken(lambda x: x["modules"][1].update(type="drone"))
        broken(lambda x: x["modules"][1].update(x=float("nan")))
        broken(lambda x: x["modules"][1].update(x=True))
        broken(lambda x: x["modules"][1].update(bogus=1))
        broken(lambda x: x["modules"][1]["properties"].update(dof=0))
        broken(lambda x: x["modules"][1]["properties"].update(colour="x"))
        broken(lambda x: x["modules"][1]["topics"].append({"name": "/bad topic"}))
        broken(lambda x: x["modules"][1]["topics"].append({"name": "/ok", "type": "not a type"}))
        broken(lambda x: x["workspace"].update(width_m=0))
        broken(
            lambda x: x.update(
                modules=[dict(base["modules"][0], id=f"m{i}", name=f"n{i}") for i in range(65)]
            )
        )

    def test_modules_stack_on_each_other_without_loops(self):
        layout = copy.deepcopy(cell_layout.TEMPLATES["so101_tabletop"]["layout"])
        cube = next(m for m in layout["modules"] if m["id"] == "cube")
        self.assertEqual((cube["parent"], cube["z"]), ("table", 0.75))
        self.assertEqual(next(m for m in layout["modules"] if m["id"] == "table")["height"], 0.75)
        for parent in ("missing", "cube"):  # unknown parent, then a loop via the cube
            broken = copy.deepcopy(layout)
            next(m for m in broken["modules"] if m["id"] == "table")["parent"] = parent
            with self.assertRaises(cell_layout.LayoutError):
                cell_layout.validate_layout(broken)

    def test_legacy_fixture_height_property_is_migrated(self):
        layout = copy.deepcopy(cell_layout.TEMPLATES["empty"]["layout"])
        layout["modules"] = [
            {"id": "t", "type": "fixture", "name": "Old table", "properties": {"height_m": 0.9}}
        ]
        module = cell_layout.validate_layout(layout)["modules"][0]
        self.assertEqual(module["height"], 0.9)
        self.assertNotIn("height_m", module["properties"])

    def test_catalog_lists_policies_with_only_act_available(self):
        from mrp_app.catalog import describe

        policies = describe()["policies"]
        self.assertEqual([k for k, v in policies.items() if v["status"] == "available"], ["act"])
        self.assertEqual(policies["groot_n1"]["status"], "planned")

    def test_topic_names_get_a_leading_slash(self):
        layout = copy.deepcopy(cell_layout.TEMPLATES["empty"]["layout"])
        layout["modules"] = [{"id": "c", "type": "camera", "name": "Cam", "topics": [{"name": "cam/image"}]}]
        self.assertEqual(cell_layout.validate_layout(layout)["modules"][0]["topics"][0]["name"], "/cam/image")


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = Application(self.root, DemoRuntime())
        self.project = self.app.create_project({"name": "First"})

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def make_episode(self, ident=None, topics=None):
        ident = ident or str(uuid.uuid4())
        folder = self.root / "raw" / "episodes" / ident
        (folder / "validation").mkdir(parents=True)
        data = build_mcap(topics or [("/joint_states", "sensor_msgs/msg/JointState", 10)])
        (folder / "episode.mcap").write_bytes(data)
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        (folder / "manifest.json").write_text(json.dumps({"content_hash": digest, "started_ns": 5}))
        (folder / "status.json").write_text(json.dumps({"status": "accepted"}))
        return ident, folder

    def test_rename_validates_and_persists(self):
        renamed = self.app.rename_project(self.project["id"], {"name": "  Sorting bench  "})
        self.assertEqual(renamed["name"], "Sorting bench")
        for bad in ("", "   ", "x" * 81, 5, "a\nb"):
            with self.assertRaises(AppError):
                self.app.rename_project(self.project["id"], {"name": bad})
        with self.assertRaises(AppError) as ctx:
            self.app.rename_project(str(uuid.uuid4()), {"name": "x"})
        self.assertEqual(ctx.exception.status, 404)

    def test_delete_needs_confirmation_and_idle_project(self):
        with self.assertRaises(AppError):
            self.app.delete_project(self.project["id"], {})
        self.app.cell("up", self.project["id"])
        self.app.select_source({"source": "teleop"})
        self.app.start({"request_id": str(uuid.uuid4()), "project_id": self.project["id"]})
        with self.assertRaises(AppError) as ctx:
            self.app.delete_project(self.project["id"], {"confirm": True})
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(len(self.app.status()["projects"]), 1)

    def test_delete_removes_derived_rows_and_folders_but_keeps_recordings(self):
        other = self.app.create_project({"name": "Other"})
        pid = self.project["id"]
        export_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        (self.app.exports_dir / export_id / "dataset").mkdir(parents=True)
        (self.app.exports_dir / export_id / "dataset" / "f.bin").write_bytes(b"x" * 10)
        (self.app.runs_dir / run_id).mkdir()
        s = self.app.store
        s.execute(
            "INSERT INTO jobs (id,request_id,state,created,payload,project_id) VALUES (?,?,?,?,?,?)",
            (export_id, str(uuid.uuid4()), "complete", 1, "{}", pid),
        )
        s.execute(
            "INSERT INTO models (id,project_id,source,label,path,state,created) VALUES (?,?,?,?,?,?,?)",
            (
                run_id,
                pid,
                "local_training",
                "m",
                f"{run_id}/output/checkpoints/last/pretrained_model",
                "complete",
                1,
            ),
        )
        s.execute(
            "INSERT INTO uploads (id,request_id,state,created,payload) VALUES (?,?,?,?,?)",
            (str(uuid.uuid4()), str(uuid.uuid4()), "complete", 1, json.dumps({"export_id": export_id})),
        )
        ident, folder = self.make_episode()
        s.execute(
            "INSERT INTO sessions (id,request_id,project_id,mode,state,started,snapshot) VALUES (?,?,?,?,?,?,?)",
            (ident, str(uuid.uuid4()), pid, "ros", "accepted", 1, "{}"),
        )
        result = self.app.delete_project(pid, {"confirm": True})
        self.assertEqual(result["removed"]["jobs"], 1)
        self.assertEqual(result["removed"]["models"], 1)
        self.assertEqual(result["removed"]["sessions"], 1)
        self.assertTrue(result["recordings_kept"])
        self.assertFalse((self.app.exports_dir / export_id).exists())
        self.assertFalse((self.app.runs_dir / run_id).exists())
        self.assertEqual(s.rows("SELECT * FROM uploads"), [])
        self.assertTrue(folder.is_dir())
        self.assertEqual([p["id"] for p in self.app.status()["projects"]], [other["id"]])
        episode = self.app.episodes()["episodes"][0]
        self.assertIsNone(episode["project_id"])

    def test_layout_defaults_then_saves_and_snapshots_into_sessions(self):
        self.assertFalse(self.project["layout_saved"])  # create_project returns the same shape
        fresh = self.app.project(self.project["id"])
        self.assertFalse(fresh["layout_saved"])
        self.assertEqual(fresh["cell_layout"], cell_layout.default_layout("mock-so101"))
        layout = copy.deepcopy(cell_layout.TEMPLATES["dual_arm"]["layout"])
        saved = self.app.set_layout(self.project["id"], {"layout": layout})
        self.assertTrue(saved["layout_saved"])
        self.assertEqual(saved["cell_layout"], layout)
        with self.assertRaises(AppError):
            self.app.set_layout(self.project["id"], {"layout": {"modules": "no"}})
        self.app.cell("up", self.project["id"])
        self.app.select_source({"source": "teleop"})
        session = self.app.start({"request_id": str(uuid.uuid4()), "project_id": self.project["id"]})
        self.assertEqual(session["snapshot"]["cell_layout"], layout)

    def test_episode_library_detail_and_delete(self):
        ident, folder = self.make_episode(topics=[("/a", "x/msg/Y", 3), ("/b", "x/msg/Z", 4)])
        listing = self.app.episodes()["episodes"]
        self.assertEqual(listing[0]["id"], ident)
        self.assertGreater(listing[0]["size_bytes"], 0)
        detail = self.app.episode_detail(ident)
        self.assertEqual(detail["mcap"]["message_count"], 7)
        self.assertEqual(self.app.episode_mcap(ident), folder / "episode.mcap")
        with self.assertRaises(AppError):
            self.app.delete_episode(ident, {})
        self.assertTrue(folder.is_dir())
        result = self.app.delete_episode(ident, {"confirm": True})
        self.assertGreater(result["freed_bytes"], 0)
        self.assertFalse(folder.exists())
        with self.assertRaises(AppError) as ctx:
            self.app.episode_detail(ident)
        self.assertEqual(ctx.exception.status, 404)

    def test_broken_mcap_is_reported_per_episode(self):
        ident, folder = self.make_episode()
        (folder / "episode.mcap").write_bytes(b"garbage")
        detail = self.app.episode_detail(ident)
        self.assertIsNone(detail["mcap"])
        self.assertIn("MCAP", detail["mcap_error"])

    def test_delete_reports_volume_permission_error(self):
        ident, _ = self.make_episode()
        with patch.object(self.app.artifacts, "delete", side_effect=PermissionError("read only")):
            with self.assertRaisesRegex(AppError, "recording volume permissions"):
                self.app.delete_episode(ident, {"confirm": True})

    def test_episode_ids_cannot_escape_the_library(self):
        for bad in ("../x", "not-a-uuid", str(uuid.uuid4())):
            with self.assertRaises(AppError):
                self.app.delete_episode(bad, {"confirm": True})
            with self.assertRaises(AppError):
                self.app.episode_mcap(bad)


class WorkspaceApiTests(ApiTestCase):
    def test_rename_delete_layout_and_catalog_over_http(self):
        project = self.new_project("Bench")
        status, renamed = self.post(f"/api/v1/projects/{project['id']}/rename", {"name": "Bench 2"})
        self.assertEqual((status, renamed["name"]), (200, "Bench 2"))
        self.assertEqual(self.post(f"/api/v1/projects/{project['id']}/rename", {"name": ""})[0], 400)
        catalog = self.get("/api/v1/catalog")[1]
        self.assertIn("arm", catalog["layout"]["module_types"])
        layout = catalog["layout"]["templates"]["so101_tabletop"]["layout"]
        status, saved = self.post(f"/api/v1/projects/{project['id']}/layout", {"layout": layout})
        self.assertEqual((status, saved["layout_saved"]), (200, True))
        self.assertEqual(self.post(f"/api/v1/projects/{project['id']}/layout", {"layout": {}})[0], 400)
        self.assertEqual(self.post(f"/api/v1/projects/{project['id']}/delete", {})[0], 400)
        self.assertEqual(self.post(f"/api/v1/projects/{project['id']}/delete", {"confirm": True})[0], 200)
        self.assertEqual(self.get("/api/v1/status")[1]["projects"], [])

    def test_episode_routes_over_http(self):
        ident = str(uuid.uuid4())
        folder = self.app.artifacts.root / ident
        folder.mkdir(parents=True)
        data = build_mcap([("/a", "x/msg/Y", 2)])
        (folder / "r.mcap").write_bytes(data)
        listing = self.get("/api/v1/episodes")[1]["episodes"]
        self.assertEqual(listing[0]["id"], ident)
        status, body = self.call(f"/api/v1/episodes/{ident}/recording.mcap")
        self.assertEqual((status, body), (200, data))
        self.assertEqual(self.get(f"/api/v1/episodes/{ident}")[1]["mcap"]["topics"][0]["topic"], "/a")
        self.assertEqual(self.post(f"/api/v1/episodes/{ident}/delete", {})[0], 400)
        self.assertEqual(self.post(f"/api/v1/episodes/{ident}/delete", {"confirm": True})[0], 200)
        self.assertEqual(self.get(f"/api/v1/episodes/{ident}")[0], 404)


if __name__ == "__main__":
    unittest.main()
