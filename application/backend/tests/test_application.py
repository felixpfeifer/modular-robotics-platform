import concurrent.futures
import hashlib
import json
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mrp_app.artifacts import Artifacts
from mrp_app.runtime import DemoRuntime, RuntimeErrorDetail
from mrp_app.server import make_server
from mrp_app.service import AppError, Application


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = Application(self.root, DemoRuntime())
        self.project = self.app.create_project({"name": "Mock collection"})

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def prepare(self):
        self.app.cell("up", self.project["id"])
        self.app.select_source({"source": "teleop"})

    def start(self, request_id=None):
        return self.app.start(
            {"request_id": request_id or str(uuid.uuid4()), "project_id": self.project["id"]}
        )

    def test_cell_start_requires_an_existing_project(self):
        for project_id in (None, "", str(uuid.uuid4())):
            with self.subTest(project_id=project_id), self.assertRaises(AppError):
                self.app.cell("up", project_id)
            self.assertFalse(self.app.runtime.status()["cell_running"])
        self.app.cell("up", self.project["id"])
        self.assertTrue(self.app.runtime.status()["cell_running"])

    def test_recording_requires_readiness_and_explicit_source(self):
        with self.assertRaises(AppError):
            self.start()
        self.app.cell("up", self.project["id"])
        with self.assertRaises(AppError):
            self.start()
        self.app.select_source({"source": "teleop"})
        self.assertEqual(self.start()["state"], "recording")

    def test_demo_joint_telemetry_is_labeled_and_offline_until_cell_starts(self):
        status = self.app.runtime.status()
        self.assertTrue(status["robot_data_simulated"])
        self.assertEqual(status["robot_data"], {})
        self.app.cell("up", self.project["id"])
        data = self.app.runtime.status()["robot_data"]
        self.assertEqual(set(data), {"Leader", "Follower"})
        self.assertEqual(len(data["Follower"]["joint_names"]), 6)
        self.assertEqual(data["Follower"]["positions"], [0.0] * 6)
        self.assertEqual(data["Follower"]["velocities"], [0.0] * 6)

    def test_demo_joint_motion_follows_teleop_and_holds_when_released(self):
        with patch("mrp_app.runtime.time.monotonic", return_value=10) as clock:
            self.prepare()
            clock.return_value = 12
            moving = self.app.runtime.status()["robot_data"]
            self.assertEqual(moving["Action"]["source"], "demo_teleop")
            self.assertEqual(moving["Action"]["positions"], moving["Leader"]["positions"])
            self.assertNotEqual(moving["Follower"]["positions"], moving["Action"]["positions"])
            self.assertNotEqual(moving["Follower"]["velocities"], [0.0] * 6)
            self.app.select_source({"source": "none"})
            clock.return_value = 20
            held = self.app.runtime.status()["robot_data"]
            self.assertNotIn("Action", held)
            self.assertEqual(held["Follower"]["positions"], moving["Follower"]["positions"])
            self.assertEqual(held["Follower"]["velocities"], [0.0] * 6)
            self.app.cell("down")
            self.assertEqual(self.app.runtime.status()["robot_data"], {})

    def test_failed_start_is_terminal_and_can_be_retried(self):
        self.prepare()
        start = self.app.runtime.start

        def reject(*args):
            raise RuntimeErrorDetail("Recorder rejected the goal")

        self.app.runtime.start = reject
        with self.assertRaisesRegex(AppError, "Recorder rejected"):
            self.start()
        failed = self.app.status()["sessions"][0]
        self.assertEqual(failed["state"], "failed")
        self.assertIsNotNone(failed["ended"])
        self.app.runtime.start = start
        self.assertEqual(self.start()["state"], "recording")

    def test_readiness_failure_includes_failed_checks(self):
        self.app.runtime.status = lambda: {
            "ready": False,
            "active_source": "teleop",
            "active_episode_id": None,
            "checks": [{"name": "Action", "ready": False, "detail": "No fresh action"}],
        }
        with self.assertRaisesRegex(AppError, "Action: No fresh action"):
            self.start()

    def test_concurrent_duplicate_start_creates_one_session(self):
        self.prepare()
        ident = str(uuid.uuid4())
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: self.start(ident), range(4)))
        self.assertEqual(len({result["id"] for result in results}), 1)
        self.assertEqual(len(self.app.status()["sessions"]), 1)
        with self.assertRaises(AppError):
            self.start()

    def test_active_recording_prevents_cell_stop(self):
        self.prepare()
        self.start()
        with self.assertRaises(AppError):
            self.app.cell("down")

    def test_demo_outcome_never_creates_accepted_artifact(self):
        self.prepare()
        episode = self.start()
        self.app.mark(episode["id"], {"kind": "annotation", "annotation": "Operator note"})
        self.app.mark(episode["id"], {"kind": "success"})
        state = self.app.status()
        self.assertEqual(state["sessions"][0]["state"], "demo_complete")
        self.assertEqual(state["sessions"][0]["annotations"][0]["text"], "Operator note")
        self.assertEqual(self.app.artifacts.list()[0], [])
        with self.assertRaises(AppError):
            self.app.export(
                {
                    "request_id": str(uuid.uuid4()),
                    "project_id": self.project["id"],
                    "episode_ids": [episode["id"]],
                }
            )

    def test_export_passes_frame_stride_to_agent(self):
        self.app.runtime.mode = "ros"
        self.app.agent_url = "http://agent"
        body = {
            "request_id": str(uuid.uuid4()),
            "project_id": self.project["id"],
            "episode_ids": [str(uuid.uuid4())],
            "repo_id": "local/test",
            "downsample_hz_ratio": 2,
        }
        with (
            patch.object(self.app.artifacts, "selection", return_value={"episodes": []}),
            patch.object(self.app, "snapshot_for", return_value={}),
            patch(
                "mrp_app.service.remote_json",
                side_effect=lambda _url, _path, payload, **_: {
                    "state": "complete",
                    "job_id": payload["job_id"],
                },
            ) as remote,
        ):
            job = self.app.export(body)
            self.app.jobs.wait(5)
        remote.assert_called_once()
        self.assertEqual(remote.call_args.args[2]["downsample_hz_ratio"], 2)
        self.assertEqual(
            self.app.store.rows("SELECT state FROM jobs WHERE id=?", (job["id"],))[0]["state"], "complete"
        )
        for invalid in (0, 121, 1.5, True):
            with self.assertRaisesRegex(AppError, "downsample_hz_ratio"):
                self.app.export({**body, "request_id": str(uuid.uuid4()), "downsample_hz_ratio": invalid})

    def test_restart_preserves_project_and_interrupts_recording(self):
        self.prepare()
        episode = self.start()
        self.app.close()
        self.app = Application(self.root, DemoRuntime())
        status = self.app.status()
        self.assertEqual(status["projects"][0]["id"], self.project["id"])
        self.assertEqual(status["sessions"][0]["id"], episode["id"])
        self.assertEqual(status["sessions"][0]["state"], "interrupted")
        self.assertFalse(status["runtime"]["cell_running"])

    def test_cancel_releases_capture_and_rejects_late_marks(self):
        self.prepare()
        episode = self.start()
        self.app.mark(episode["id"], {"kind": "cancel"})
        with self.assertRaises(AppError):
            self.app.mark(episode["id"], {"kind": "success"})
        self.assertNotEqual(self.start()["id"], episode["id"])

    def test_export_report_reconciles_after_application_restart(self):
        ident, request_id = str(uuid.uuid4()), str(uuid.uuid4())
        payload = {"episode_ids": [], "repo_id": "local/test", "format": "LeRobot v3", "output": "test"}
        self.app.store.execute(
            "INSERT INTO jobs (id,request_id,state,created,payload,detail) VALUES (?,?,?,?,?,?)",
            (ident, request_id, "running", 1, json.dumps(payload), ""),
        )
        folder = self.app.exports_dir / ident
        folder.mkdir()
        (folder / "report.json").write_text(
            json.dumps({"job_id": ident, "state": "complete", "detail": "verified"})
        )
        self.app.close()
        self.app = Application(self.root, DemoRuntime())
        self.assertEqual(self.app.status()["jobs"][0]["state"], "complete")


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.artifacts = Artifacts(self.root)
        self.ident = str(uuid.uuid4())
        self.folder = self.root / "episodes" / self.ident
        (self.folder / "validation").mkdir(parents=True)
        # Unit fixture only; exporter/MCAP qualification is a separate integration check.
        content = b"unit-fixture-for-hash-gating"
        (self.folder / "data.mcap").write_bytes(content)
        self.digest = "sha256:" + hashlib.sha256(content).hexdigest()
        (self.folder / "manifest.json").write_text(json.dumps({"content_hash": self.digest, "started_ns": 1}))
        (self.folder / "status.json").write_text(json.dumps({"status": "accepted"}))
        self.report = self.folder / "validation/validation.json"
        self.report.write_text(json.dumps({"valid": True, "artifact_hash": self.digest}))

    def tearDown(self):
        self.temp.cleanup()

    def test_selection_requires_matching_validation_and_raw_hash(self):
        self.assertEqual(self.artifacts.selection([self.ident])["episodes"][0]["content_hash"], self.digest)
        (self.folder / "data.mcap").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.artifacts.selection([self.ident])

    def test_rejected_and_stale_evidence_never_selected(self):
        for report in (
            {"valid": False, "artifact_hash": self.digest},
            {"valid": True, "artifact_hash": "stale"},
        ):
            self.report.write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                self.artifacts.selection([self.ident])

    def test_path_traversal_and_symlink_rejected(self):
        with self.assertRaises(ValueError):
            self.artifacts.episode("../../outside")
        other = str(uuid.uuid4())
        (self.root / "episodes" / other).symlink_to(self.folder, target_is_directory=True)
        with self.assertRaises(FileNotFoundError):
            self.artifacts.episode(other)
        self.assertEqual(len(self.artifacts.list()[0]), 1)

    def test_corrupt_report_is_visible_without_hiding_other_episodes(self):
        self.report.write_text("broken")
        episodes, errors = self.artifacts.list()
        self.assertEqual(episodes, [])
        self.assertEqual(errors[0]["id"], self.ident)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(Path(self.temp.name), DemoRuntime())
        self.server = make_server(self.app, port=0, allowed_origins=("http://frontend.example",))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.app.close()
        self.temp.cleanup()

    def request(self, path, body=None, headers=None):
        request = Request(
            self.url + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers or {"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, response.headers, response.read()
        except HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def test_api_contract_is_served_without_frontend_assets(self):
        for path in ("/health", "/openapi.json", "/api/v1/webrtc/status"):
            status, headers, body = self.request(path)
            self.assertEqual(status, 200, path)
            self.assertGreater(len(body), 0)
            self.assertIn("nosniff", headers["X-Content-Type-Options"])
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)  # urllib follows the redirect to Swagger UI
        self.assertIn(b"swagger-ui", body)
        contract = json.loads(self.request("/openapi.json")[2])
        self.assertIn("/api/v1/models/import", contract["paths"])
        self.assertIn("project_id", contract["components"]["schemas"]["Export"]["required"])

    def test_invalid_json_shape_and_cross_origin_writes_rejected(self):
        self.assertEqual(self.request("/api/v1/projects", ["not an object"])[0], 400)
        self.assertEqual(
            self.request(
                "/api/v1/projects",
                {"name": "test"},
                {"Content-Type": "application/json", "Origin": "http://untrusted.example"},
            )[0],
            400,
        )
        self.assertEqual(
            self.request("/api/v1/projects", {"name": "test"}, {"Content-Type": "text/plain"})[0], 400
        )
        self.assertEqual(self.request("/health", headers={"Host": "untrusted.example"})[0], 403)

    def test_same_origin_browser_write_and_untrusted_origin(self):
        status, _, body = self.request(
            "/api/v1/projects",
            {"name": "Same origin"},
            {"Content-Type": "application/json", "Origin": self.url},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["name"], "Same origin")
        status, _, body = self.request(
            "/api/v1/projects",
            {"name": "Rejected"},
            {"Content-Type": "application/json", "Origin": "http://127.0.0.1:9999"},
        )
        self.assertEqual(status, 400)
        self.assertIn("Cross-origin", json.loads(body)["error"])

    def test_browser_cross_origin_preflight(self):
        def preflight(origin):
            request = Request(
                self.url + "/api/v1/projects",
                method="OPTIONS",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            try:
                with urlopen(request, timeout=5) as response:
                    return response.status, response.headers
            except HTTPError as exc:
                return exc.code, exc.headers

        status, headers = preflight("http://frontend.example")
        self.assertEqual(status, 204)
        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://frontend.example")
        self.assertIn("POST", headers["Access-Control-Allow-Methods"])
        self.assertEqual(preflight("http://untrusted.example")[0], 400)
        status, headers, _ = self.request(
            "/api/v1/projects",
            {"name": "Remote"},
            {"Origin": "http://frontend.example", "Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://frontend.example")

    def test_fastapi_contract_and_validation(self):
        from urllib.request import HTTPRedirectHandler, build_opener

        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        with self.assertRaises(HTTPError) as redirect:
            build_opener(NoRedirect).open(self.url + "/")
        self.assertEqual(redirect.exception.code, 302)
        self.assertEqual(redirect.exception.headers["Location"], "/docs")
        contract = json.loads(self.request("/openapi.json")[2])
        self.assertEqual(contract["paths"]["/api/v1/sessions"]["post"]["tags"], ["Recordings"])
        self.assertIn("request_id", contract["components"]["schemas"]["Session"]["required"])
        self.assertIn(
            "application/zip", contract["paths"]["/api/v1/models/import"]["post"]["requestBody"]["content"]
        )
        status, _, body = self.request("/api/v1/projects", {})
        self.assertEqual(status, 400)
        self.assertIn("name", json.loads(body)["error"])
        self.assertEqual(
            self.request("/api/v1/control", {"source": "policy", "confirm_policy": "true"})[0], 400
        )
        self.assertEqual(self.request("/api/v1/projects", {"name": "x" * 65536})[0], 400)
        self.assertEqual(self.request("/not-a-route")[0], 404)

    def test_complete_demo_workflow_over_http(self):
        _, _, data = self.request("/api/v1/projects", {"name": "Browser project"})
        project = json.loads(data)
        self.assertEqual(self.request("/api/v1/cell/up", {"project_id": project["id"]})[0], 200)
        self.assertEqual(self.request("/api/v1/control", {"source": "teleop"})[0], 200)
        request = {"project_id": project["id"], "request_id": str(uuid.uuid4())}
        status, _, data = self.request("/api/v1/sessions", request)
        self.assertEqual(status, 200)
        ident = json.loads(data)["id"]
        self.assertEqual(self.request(f"/api/v1/sessions/{ident}/mark", {"kind": "success"})[0], 200)
        self.assertEqual(
            self.request(
                "/api/v1/exports",
                {"request_id": str(uuid.uuid4()), "project_id": project["id"], "episode_ids": [ident]},
            )[0],
            409,
        )
        self.assertEqual(self.request("/api/v1/cell/down", {})[0], 200)


if __name__ == "__main__":
    unittest.main()


class ProjectWorkflowTests(unittest.TestCase):
    SIM = {
        "leader": "mock",
        "follower": "gazebo",
        "camera": "gazebo_scene",
        "task_id": "red_cube_to_rectangle",
    }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(Path(self.temp.name), DemoRuntime(), agent_url="http://agent.invalid")
        self.project = self.app.create_project({"name": "P"})

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def test_new_project_defaults_to_mock_cell_and_reports_stages(self):
        self.assertEqual(self.project["preset"], "mock-so101")
        flow = self.app.workflow(self.project["id"])
        self.assertEqual([s["id"] for s in flow["stages"]], ["setup", "record", "dataset", "train", "deploy"])
        self.assertEqual([s["state"] for s in flow["stages"]], ["done", "todo", "blocked", "blocked", "todo"])

    def test_cell_start_forwards_saved_custom_images(self):
        cell = {**self.project["cell_spec"], "images": {"leader": "acme/robot:v1"}}
        self.app.set_cell(self.project["id"], {"cell": cell})
        self.app.runtime.mode = "ros"
        with patch("mrp_app.service.remote_json", return_value={}) as remote:
            self.app.cell("up", self.project["id"])
        self.assertEqual(remote.call_args.args[2]["images"], cell["images"])

    def test_cell_can_be_reconfigured_but_only_to_supported_combinations(self):
        self.assertEqual(self.app.set_cell(self.project["id"], {"cell": self.SIM})["preset"], "sim-so101")
        with self.assertRaises(AppError) as error:
            self.app.set_cell(self.project["id"], {"cell": {**self.SIM, "camera": "synthetic"}})
        self.assertIn("Gazebo", str(error.exception))
        with self.assertRaises(AppError) as error:
            self.app.set_cell(self.project["id"], {"cell": {**self.SIM, "follower": "hardware"}})
        self.assertIn("Unknown follower", str(error.exception))
        with self.assertRaises(AppError):
            self.app.set_cell(self.project["id"], {"cell": {**self.SIM, "task_id": "pipeline_check"}})

    def test_real_hardware_cells_follow_the_staged_combinations(self):
        mock = {"leader": "mock", "follower": "mock", "camera": "synthetic", "task_id": "pipeline_check"}
        ports = {"leader": {"port": "/dev/ttyACM0"}, "follower": {"port": "/dev/ttyACM1"}}
        # Real leader + mock follower: no motors move.
        cell = {**mock, "leader": "real", "devices": {"leader": ports["leader"]}}
        self.assertEqual(self.app.set_cell(self.project["id"], {"cell": cell})["preset"], "hwleader-so101")
        # Real leader + real follower, USB camera.
        cell = {
            **mock,
            "leader": "real",
            "follower": "real",
            "camera": "opencv_usb",
            "task_id": "free_teleop",
            "devices": {**ports, "camera": {"device": "/dev/video2"}},
        }
        saved = self.app.set_cell(self.project["id"], {"cell": cell})
        self.assertEqual(saved["preset"], "real-so101")
        self.assertEqual(saved["cell_spec"]["devices"]["follower"]["port"], "/dev/ttyACM1")
        # A real follower must never be driven by a mock leader.
        with self.assertRaises(AppError) as error:
            self.app.set_cell(self.project["id"], {"cell": {**mock, "follower": "real"}})
        self.assertIn("real leader", str(error.exception))
        bad_devices = [
            {"leader": {"port": "/etc/passwd"}},
            {"leader": {"port": "/dev/ttyACM0"}, "follower": {"port": "/dev/ttyACM0"}},
            {"camera": {"device": "/dev/video2"}, "leader": {"port": "/dev/ttyACM0"}, "bogus": {}},
            {"leader": {"port": "/dev/ttyACM0", "calibration": "../x.yaml"}},
        ]
        for devices in bad_devices:
            with self.subTest(devices=devices), self.assertRaises(AppError):
                self.app.set_cell(self.project["id"], {"cell": {**cell, "devices": devices}})
        # Mock motion needs a mock leader.
        with self.assertRaises(AppError):
            self.app.set_cell(self.project["id"], {"cell": {**cell, "mock_motion": True}})
        ok = self.app.set_cell(self.project["id"], {"cell": {**mock, "mock_motion": True}})
        self.assertTrue(ok["cell_spec"]["mock_motion"])

    def test_marking_a_finalizing_episode_explains_why_instead_of_a_generic_error(self):
        ident = str(uuid.uuid4())
        self.app.store.execute(
            "INSERT INTO sessions (id,request_id,project_id,mode,state,started,snapshot) VALUES (?,?,?,?,?,?,?)",
            (ident, str(uuid.uuid4()), self.project["id"], "ros", "finalizing", time.time(), "{}"),
        )
        with self.assertRaises(AppError) as error:
            self.app.mark(ident, {"kind": "success"})
        self.assertEqual(error.exception.status, 409)
        self.assertIn("being saved and validated", str(error.exception))

    def test_runtime_bound_to_other_cell_refuses_to_record(self):
        sim = self.app.create_project({"name": "Sim", "cell": self.SIM})
        with self.assertRaises(AppError) as error:
            self.app.start({"request_id": str(uuid.uuid4()), "project_id": sim["id"]})
        self.assertEqual(error.exception.status, 409)
        self.assertIn("runtime is bound", str(error.exception))

    def test_training_requires_completed_export_of_the_same_project(self):
        body = {
            "request_id": str(uuid.uuid4()),
            "project_id": self.project["id"],
            "export_id": str(uuid.uuid4()),
        }
        with self.assertRaises(AppError):
            self.app.train(body)

    def test_training_validates_settings_and_model_path(self):
        export = str(uuid.uuid4())
        self.app.store.execute(
            "INSERT INTO jobs (id,request_id,state,created,payload,project_id) VALUES (?,?,?,?,?,?)",
            (export, str(uuid.uuid4()), "complete", 1, "{}", self.project["id"]),
        )
        base = {"project_id": self.project["id"], "export_id": export}
        for bad in (
            {"settings": {"steps": 0}},
            {"settings": {"batch_size": "8"}},
            {"base_model": "/etc/passwd"},
            {"base_model": "../x/output/checkpoints/last/pretrained_model"},
            {
                "settings": {"smoke": True},
                "base_model": f"{uuid.uuid4()}/output/checkpoints/last/pretrained_model",
            },
            {"label": "x" * 81},
        ):
            with self.assertRaises(AppError, msg=str(bad)):
                self.app.train({"request_id": str(uuid.uuid4()), **base, **bad})

    def test_training_runs_once_and_records_checkpoint(self):
        export = str(uuid.uuid4())
        self.app.store.execute(
            "INSERT INTO jobs (id,request_id,state,created,payload,project_id) VALUES (?,?,?,?,?,?)",
            (export, str(uuid.uuid4()), "complete", 1, "{}", self.project["id"]),
        )
        from unittest.mock import patch

        calls = []

        def fake(base, path, payload=None, timeout=10):
            if path == "/api/v1/hardware":
                return {"gpu": False, "name": "", "vram_gb": 0, "detail": ""}
            calls.append((path, payload))
            return {
                "run_id": payload["run_id"],
                "status": "complete",
                "checkpoint": f"/data/runs/{payload['run_id']}/output/checkpoints/last/pretrained_model",
            }

        with patch("mrp_app.service.remote_json", fake):
            request = str(uuid.uuid4())
            row = self.app.train(
                {
                    "request_id": request,
                    "project_id": self.project["id"],
                    "export_id": export,
                    "settings": {"steps": 5, "smoke": True},
                    "label": "first",
                }
            )
            self.app.jobs.wait(5)
            self.assertEqual(
                self.app.train(
                    {"request_id": request, "project_id": self.project["id"], "export_id": export}
                )["id"],
                row["id"],
            )
        done = self.app.store.rows("SELECT * FROM trainings")[0]
        self.assertEqual(
            (done["state"], done["checkpoint"]),
            ("complete", f"{row['id']}/output/checkpoints/last/pretrained_model"),
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["settings"]["steps"], 5)

    def test_cpu_training_without_gpu_needs_confirmation_and_cuda_needs_a_gpu(self):
        from unittest.mock import patch

        export = str(uuid.uuid4())
        self.app.store.execute(
            "INSERT INTO jobs (id,request_id,state,created,payload,project_id) VALUES (?,?,?,?,?,?)",
            (export, str(uuid.uuid4()), "complete", 1, "{}", self.project["id"]),
        )
        none = {"gpu": False, "name": "", "vram_gb": 0, "detail": "Docker cannot reach an NVIDIA GPU."}
        gpu = {"gpu": True, "name": "RTX", "vram_gb": 8, "detail": ""}
        sent = []

        def fake(base, path, payload=None, timeout=10):
            sent.append(payload["device"])
            return {"run_id": payload["run_id"], "status": "failed"}

        def start(device="auto", **extra):
            body = {
                "request_id": str(uuid.uuid4()),
                "project_id": self.project["id"],
                "export_id": export,
                "device": device,
                **extra,
            }
            row = self.app.train(body)
            self.app.jobs.wait(5)
            return row

        with patch("mrp_app.service.remote_json", fake):
            with patch.object(self.app, "hardware", return_value=none):
                with self.assertRaises(AppError) as error:
                    start("auto")
                self.assertEqual(error.exception.status, 409)
                self.assertIn("Docker cannot reach", str(error.exception))
                with self.assertRaises(AppError):
                    start("cpu")
                with self.assertRaises(AppError):
                    start("cuda", confirm_cpu=True)
                start("auto", confirm_cpu=True)
            with patch.object(self.app, "hardware", return_value=gpu):
                start("auto")
                start("cpu")  # An explicit CPU choice needs no confirmation when a GPU exists.
        self.assertEqual(sent, ["cpu", "cuda", "cpu"])

    def test_policy_source_needs_a_running_deployment_and_confirmation(self):
        self.app.cell("up", self.project["id"])
        with self.assertRaises(AppError):
            self.app.select_source({"source": "policy"})
        with self.assertRaises(AppError):
            self.app.select_source({"source": "policy", "confirm_policy": True})


class LegacyProjectTests(unittest.TestCase):
    def test_projects_created_before_cells_get_the_mock_cell(self):
        with tempfile.TemporaryDirectory() as root:
            app = Application(Path(root), DemoRuntime())
            app.store.execute(
                "INSERT INTO projects (id,name,created) VALUES (?,?,?)",
                ("a" * 8 + "-0000-0000-0000-" + "0" * 12, "Old", 1),
            )
            project = app.status()["projects"][0]
            self.assertEqual(
                (project["preset"], project["cell_spec"]["task_id"]), ("mock-so101", "pipeline_check")
            )
            self.assertEqual(app.workflow(project["id"])["stages"][0]["state"], "done")
            app.close()


class DeliveryAndModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = Application(self.root, DemoRuntime(), agent_url="http://agent.invalid")
        self.project = self.app.create_project({"name": "P"})
        self.server = make_server(self.app, port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.app.close()
        self.temp.cleanup()

    def checkpoint_zip(self, config=None):
        import io
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name in ("model.safetensors", "policy_preprocessor.json", "policy_postprocessor.json"):
                archive.writestr(name, "x")
            archive.writestr("config.json", json.dumps(config or {"type": "act"}))
        return buffer.getvalue()

    def post(self, path, data, content_type):
        request = Request(self.base + path, data=data, headers={"Content-Type": content_type})
        try:
            with urlopen(request) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_checkpoint_zip_import_creates_project_model_usable_as_base(self):
        status, model = self.post(
            f"/api/v1/models/import?project_id={self.project['id']}&label=gpu",
            self.checkpoint_zip(),
            "application/zip",
        )
        self.assertEqual((status, model["source"], model["state"]), (200, "checkpoint_import", "complete"))
        self.assertTrue((self.app.runs_dir / model["path"] / "model.safetensors").is_file())
        self.assertEqual(self.app.project_model(model["id"], self.project["id"])["path"], model["path"])
        other = self.app.create_project({"name": "Other"})
        with self.assertRaises(AppError):
            self.app.project_model(model["id"], other["id"])
        flow = self.app.workflow(self.project["id"])
        self.assertEqual(next(s for s in flow["stages"] if s["id"] == "train")["summary"], "1 model(s)")

    def test_bad_checkpoint_zip_is_rejected_without_leftovers(self):
        status, body = self.post(
            f"/api/v1/models/import?project_id={self.project['id']}",
            self.checkpoint_zip({"type": "diffusion"}),
            "application/zip",
        )
        self.assertEqual(status, 400)
        self.assertEqual(list(self.app.runs_dir.iterdir()), [])
        status, _ = self.post(
            f"/api/v1/models/import?project_id={self.project['id']}", b"not a zip", "application/zip"
        )
        self.assertEqual(status, 400)
        status, _ = self.post(
            f"/api/v1/models/import?project_id={self.project['id']}", b"{}", "application/json"
        )
        self.assertEqual(status, 400)

    def test_settings_token_is_write_only_and_private_on_disk(self):
        status, public = self.post(
            "/api/v1/settings",
            json.dumps({"hf_token": "hf_secret", "hf_namespace": "me"}).encode(),
            "application/json",
        )
        self.assertEqual((status, public), (200, {"hf_token_set": True, "hf_namespace": "me", "targets": []}))
        self.assertNotIn("hf_secret", json.dumps(self.app.status()))
        self.assertEqual((self.root / "settings.json").stat().st_mode & 0o777, 0o600)
        self.assertNotIn("hf_secret", (self.root / "settings.json").read_text())
        self.assertTrue((self.root / "settings.key").is_file())
        self.assertEqual(
            self.post("/api/v1/settings", json.dumps({"hf_token": "bad token"}).encode(), "application/json")[
                0
            ],
            400,
        )
        self.assertEqual(self.app.update_settings({"clear_hf_token": True})["hf_token_set"], False)

    def test_hub_import_uses_saved_token_only_when_asked_and_records_model(self):
        from unittest.mock import patch

        self.app.update_settings({"hf_token": "hf_secret"})
        seen = []

        def fake(base, path, payload=None, timeout=10):
            seen.append(payload)
            return {"run_id": payload["run_id"], "status": "complete"}

        with patch("mrp_app.service.remote_json", fake):
            request = str(uuid.uuid4())
            self.app.import_hub_model(
                {
                    "request_id": request,
                    "project_id": self.project["id"],
                    "repo_id": "me/act",
                    "use_saved_token": True,
                }
            )
            self.app.jobs.wait(5)
            self.app.import_hub_model(
                {"request_id": str(uuid.uuid4()), "project_id": self.project["id"], "repo_id": "me/act"}
            )
            self.app.jobs.wait(5)
        self.assertEqual([call["token"] for call in seen], ["hf_secret", None])
        self.assertEqual({m["state"] for m in self.app.status()["models"]}, {"complete"})
        self.assertNotIn("hf_secret", json.dumps(self.app.status()))
        with self.assertRaises(AppError):
            self.app.import_hub_model(
                {"request_id": str(uuid.uuid4()), "project_id": self.project["id"], "repo_id": "../x"}
            )

    def test_dataset_zip_download_and_notebook(self):
        export = str(uuid.uuid4())
        dataset = self.app.exports_dir / export / "dataset"
        (dataset / "meta").mkdir(parents=True)
        (dataset / "meta/info.json").write_text("{}")
        (dataset / "data.bin").write_bytes(b"abc")
        self.app.store.execute(
            "INSERT INTO jobs (id,request_id,state,created,payload,project_id) VALUES (?,?,?,?,?,?)",
            (export, str(uuid.uuid4()), "complete", 1, "{}", self.project["id"]),
        )
        import io
        import zipfile

        with urlopen(f"{self.base}/api/v1/exports/{export}/dataset.zip") as response:
            names = zipfile.ZipFile(io.BytesIO(response.read())).namelist()
        self.assertEqual(sorted(names), ["data.bin", "meta/info.json"])
        with self.assertRaises(HTTPError):
            urlopen(f"{self.base}/api/v1/exports/{uuid.uuid4()}/dataset.zip")
        with urlopen(
            f"{self.base}/api/v1/projects/{self.project['id']}/notebook.ipynb?source=hub&repo_id=me/ds&steps=50"
        ) as response:
            notebook = json.load(response)
        text = "".join("".join(c["source"]) for c in notebook["cells"])
        self.assertIn("lerobot==0.6.1", text)
        self.assertIn("STEPS, BATCH_SIZE, CHUNK_SIZE = 50, 8, 100", text)
        self.assertNotIn("hf_", text.replace("huggingface_hub", "").replace("HF_TOKEN", ""))
        with self.assertRaises(HTTPError):
            urlopen(f"{self.base}/api/v1/projects/{self.project['id']}/notebook.ipynb?source=hub&repo_id=bad")
