"""HTTP contract tests: what the web interface relies on, plus error paths."""

import asyncio
import json
import tempfile
import threading
import time
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

import httpx
from mrp_app.runtime import DemoRuntime
from mrp_app.server import create_api, make_server
from mrp_app.service import Application
from websockets.exceptions import ConnectionClosedError, InvalidStatus
from websockets.sync.client import connect


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Application(Path(self.temp.name), DemoRuntime())
        self.addCleanup(self.app.close)
        self.api = create_api(self.app, allowed_origins=("http://frontend.example",))
        self.addCleanup(self.api.state.webrtc.close)
        self.url = "http://127.0.0.1"

    def request(self, method, path, **kwargs):
        async def exchange():
            transport = httpx.ASGITransport(app=self.api)
            async with httpx.AsyncClient(transport=transport, base_url=self.url) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(exchange())

    def call(self, path, body=None, raw=None, content_type="application/json"):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        headers = {"Content-Type": content_type} if data is not None else {}
        response = self.request("GET" if data is None else "POST", path, content=data, headers=headers)
        return response.status_code, response.content

    def post(self, path, body):
        status, data = self.call(path, body)
        return status, json.loads(data or b"{}")

    def get(self, path):
        status, data = self.call(path)
        return status, json.loads(data)

    def new_project(self, name="Test project"):
        status, project = self.post("/api/v1/projects", {"name": name})
        self.assertEqual(status, 200, project)
        return project

    def record(self, project):
        self.assertEqual(self.post("/api/v1/cell/up", {"project_id": project["id"]})[0], 200)
        self.assertEqual(self.post("/api/v1/control", {"source": "teleop"})[0], 200)
        status, session = self.post(
            "/api/v1/sessions", {"project_id": project["id"], "request_id": str(uuid.uuid4())}
        )
        self.assertEqual(status, 200, session)
        return session


class StatusContractTests(ApiTestCase):
    """The frontend's types.ts depends on these fields; a rename must fail CI."""

    def test_status_has_every_field_the_frontend_reads(self):
        status, body = self.get("/api/v1/status")
        self.assertEqual(status, 200)
        for key in ("mode", "runtime", "projects", "sessions", "settings", "export_enabled"):
            self.assertIn(key, body)
        self.assertIn(body["mode"], ("demo", "ros"))
        for key in ("cell_running", "active_source", "checks", "message"):
            self.assertIn(key, body["runtime"])
        for check in body["runtime"]["checks"]:
            self.assertTrue({"name", "ready", "detail"} <= set(check))
        self.assertEqual(set(body["settings"]), {"hf_token_set", "hf_namespace", "targets"})

    def test_demo_mode_never_offers_export(self):
        _, body = self.get("/api/v1/status")
        self.assertEqual(body["mode"], "demo")
        self.assertFalse(body["export_enabled"])

    def test_episodes_listing_is_a_dict_with_episodes(self):
        status, body = self.get("/api/v1/episodes")
        self.assertEqual(status, 200)
        self.assertEqual(body["episodes"], [])

    def test_health_and_unknown_routes(self):
        self.assertEqual(self.call("/health")[0], 200)
        self.assertEqual(self.call("/api/v1/does-not-exist")[0], 404)

    def test_new_project_appears_in_status_with_cell_fields(self):
        project = self.new_project("Pick and place")
        _, body = self.get("/api/v1/status")
        listed = {item["id"]: item for item in body["projects"]}
        self.assertEqual(listed[project["id"]]["name"], "Pick and place")
        self.assertIn("preset", listed[project["id"]])
        self.assertIn("task_id", listed[project["id"]]["cell_spec"])


class WebSocketContractTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        server = make_server(self.app, port=0)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)

        def stop():
            if thread.is_alive():
                server.shutdown()
                thread.join(timeout=5)

        self.addCleanup(stop)
        thread.start()
        self.url = f"http://127.0.0.1:{server.server_port}"

    def test_telemetry_socket_streams_cached_robot_data_and_checks_origin(self):
        self.app.runtime.cell("up")
        self.app.runtime.select_source("teleop")
        url = self.url.replace("http://", "ws://") + "/api/v1/telemetry"
        with connect(url, origin=self.url, open_timeout=5) as ws:
            first = json.loads(ws.recv(timeout=5))
            second = json.loads(ws.recv(timeout=5))
            self.assertTrue(first["robot_data_simulated"])
            self.assertIn("Follower", first["robot_data"])
            self.assertGreater(
                second["robot_data"]["Follower"]["stamp_ns"], first["robot_data"]["Follower"]["stamp_ns"]
            )
        with self.assertRaises(InvalidStatus):
            with connect(url, origin="http://evil.example", open_timeout=5):
                pass

    def test_camera_socket_sends_only_new_frames_and_reports_unavailable(self):
        image = b"jpeg-frame"
        self.app.runtime.preview = lambda: image
        url = self.url.replace("http://", "ws://") + "/api/v1/camera"
        with connect(url, origin=self.url, open_timeout=5) as ws:
            self.assertEqual(ws.recv(timeout=5), image)
            with self.assertRaises(TimeoutError):
                ws.recv(timeout=0.25)
            self.app.runtime.preview = lambda: None
            self.assertEqual(json.loads(ws.recv(timeout=5)), {"available": False})
            self.app.runtime.preview = lambda: b"next-frame"
            self.assertEqual(ws.recv(timeout=5), b"next-frame")

    def test_camera_socket_streams_fresh_frames_at_the_preview_rate(self):
        frames = (f"frame-{number}".encode() for number in range(11))
        self.app.runtime.preview = lambda: next(frames, None)
        url = self.url.replace("http://", "ws://") + "/api/v1/camera"
        with connect(url, origin=self.url, open_timeout=5) as ws:
            self.assertEqual(ws.recv(timeout=5), b"frame-0")
            started = time.monotonic()
            for number in range(1, 11):
                ws.send("ignored")
                remaining = max(0, started + 1.8 - time.monotonic())
                self.assertEqual(ws.recv(timeout=remaining), f"frame-{number}".encode())
            self.assertGreaterEqual(time.monotonic() - started, 0.9)

    def test_named_camera_socket_keeps_feeds_separate_and_releases_its_viewer(self):
        stopped = threading.Event()
        images = {None: b"primary-frame", "wrist": b"wrist-frame"}

        @contextmanager
        def watch_camera(name):
            try:
                yield name == "wrist"
            finally:
                if name == "wrist":
                    stopped.set()

        self.app.runtime.watch_camera = watch_camera
        self.app.runtime.preview = lambda name=None: images.get(name)
        url = self.url.replace("http://", "ws://") + "/api/v1/camera"
        with (
            connect(url, origin=self.url) as primary,
            connect(url + "?camera=wrist", origin=self.url) as wrist,
        ):
            self.assertEqual(primary.recv(timeout=5), b"primary-frame")
            self.assertEqual(wrist.recv(timeout=5), b"wrist-frame")
            self.assertEqual(self.call("/api/v1/preview.jpg?camera=wrist"), (200, b"wrist-frame"))
            images["wrist"] = None
            self.assertEqual(json.loads(wrist.recv(timeout=5)), {"available": False})
            images[None] = b"next-primary-frame"
            self.assertEqual(primary.recv(timeout=5), b"next-primary-frame")
        self.assertTrue(stopped.wait(2))
        with connect(url + "?camera=unknown", origin=self.url) as unknown:
            with self.assertRaises(ConnectionClosedError) as closed:
                unknown.recv(timeout=5)
            self.assertEqual(closed.exception.rcvd.code, 1008)


class ValidationTests(ApiTestCase):
    def test_chunked_json_body_enforces_the_limit_and_keeps_cors_headers(self):
        async def chunks(size):
            yield b"{}"
            yield b" " * (size - 2)

        headers = {"Content-Type": "application/json", "Origin": "http://frontend.example"}
        accepted = self.request("POST", "/api/v1/config/export", headers=headers, content=chunks(65536))
        self.assertEqual(accepted.status_code, 200)
        oversized = self.request("POST", "/api/v1/config/export", headers=headers, content=chunks(65537))
        self.assertEqual(oversized.status_code, 400)
        self.assertEqual(oversized.json(), {"error": "JSON body must contain 1–65536 bytes."})
        self.assertEqual(oversized.headers["Access-Control-Allow-Origin"], "http://frontend.example")
        self.assertEqual(oversized.headers["Cache-Control"], "no-store")

    def test_archive_length_and_content_type_errors_preserve_the_contract(self):
        original_files = set(self.app.data_dir.iterdir())
        for path, media in (
            ("/api/v1/datasets/validate-zip", "application/zip"),
            ("/api/v1/models/import?project_id=test", "application/zip"),
            ("/api/v1/config/validate", "application/gzip"),
            ("/api/v1/config/import", "application/gzip"),
        ):
            for length, error in (
                ("2", "Upload ended early."),
                ("1", "Upload exceeded its declared length."),
                ("invalid", "Invalid Content-Length."),
            ):
                with self.subTest(path=path, length=length):
                    response = self.request(
                        "POST",
                        path,
                        headers={"Content-Type": media, "Content-Length": length},
                        content=b"x" if length != "1" else b"xx",
                    )
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.json(), {"error": error})
            response = self.request("POST", path, content=b"x", headers={"Content-Type": "text/plain"})
            self.assertEqual(response.json(), {"error": f"Content-Type must be {media}."})
        self.assertEqual(set(self.app.data_dir.iterdir()), original_files)

    def test_recording_and_job_openapi_responses_are_typed(self):
        status, schema = self.get("/openapi.json")
        self.assertEqual(status, 200)
        for path, model in (
            ("/api/v1/sessions", "SessionResult"),
            ("/api/v1/sessions/{episode_id}/mark", "MarkResult"),
            ("/api/v1/exports", "JobResult"),
            ("/api/v1/trainings", "TrainingResult"),
            ("/api/v1/uploads", "UploadResult"),
            ("/api/v1/models/hub", "ImportedModelResult"),
        ):
            responses = schema["paths"][path]["post"]["responses"]
            self.assertIn("400", responses)
            self.assertNotIn("422", responses)
            self.assertEqual(
                responses["200"]["content"]["application/json"]["schema"]["$ref"],
                f"#/components/schemas/{model}",
            )

    def test_project_cell_accepts_component_lists_and_persists_them(self):
        project = self.new_project()
        cell = {
            "arms": [
                {"id": "leader", "role": "leader", "backend": "mock"},
                {"id": "follower", "role": "follower", "backend": "mock", "leader": "leader"},
            ],
            "cameras": [{"id": "top", "source": "synthetic"}],
            "task_id": "pipeline_check",
        }
        status, saved = self.post(f"/api/v1/projects/{project['id']}/cell", {"cell": cell})
        self.assertEqual(status, 200, saved)
        _, state = self.get("/api/v1/status")
        restored = next(p for p in state["projects"] if p["id"] == project["id"])["cell_spec"]
        self.assertEqual(restored["cameras"][0]["id"], "top")
        self.assertEqual([arm["id"] for arm in restored["arms"]], ["leader", "follower"])

    def test_project_cell_round_trips_custom_images(self):
        project = self.new_project()
        cell = {**project["cell_spec"], "images": {"camera": "acme/camera:v1"}}
        status, saved = self.post(f"/api/v1/projects/{project['id']}/cell", {"cell": cell})
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["cell_spec"]["images"], cell["images"])
        cell["images"]["camera"] = "invalid;command"
        self.assertEqual(self.post(f"/api/v1/projects/{project['id']}/cell", {"cell": cell})[0], 400)

    def test_project_name_rules(self):
        self.assertEqual(self.post("/api/v1/projects", {"name": ""})[0], 400)
        self.assertEqual(self.post("/api/v1/projects", {"name": "x" * 81})[0], 400)
        self.assertEqual(self.post("/api/v1/projects", {})[0], 400)
        self.assertEqual(self.post("/api/v1/projects", {"name": 123})[0], 400)

    def test_body_must_be_json_and_bounded(self):
        self.assertEqual(self.call("/api/v1/projects", raw=b"{not json")[0], 400)
        self.assertEqual(self.call("/api/v1/projects", raw=b"")[0], 400)
        big = json.dumps({"name": "x" * 70000}).encode()
        self.assertEqual(self.call("/api/v1/projects", raw=big)[0], 400)
        self.assertEqual(
            self.call("/api/v1/projects", raw=b'{"name":"a"}', content_type="text/plain")[0], 400
        )

    def test_error_responses_carry_an_error_message_for_the_ui(self):
        # api.ts shows response.data.error to the user; it must always be present.
        status, body = self.post("/api/v1/projects", {"name": ""})
        self.assertEqual(status, 400)
        self.assertTrue(body.get("error"), body)
        status, body = self.post("/api/v1/control", {"source": "teleop"})
        self.assertGreaterEqual(status, 400)
        self.assertTrue(body.get("error"), body)

    def test_control_source_is_restricted(self):
        project = self.new_project()
        self.post("/api/v1/cell/up", {"project_id": project["id"]})
        self.assertEqual(self.post("/api/v1/control", {"source": "autopilot"})[0], 400)

    def test_policy_control_requires_explicit_confirmation(self):
        project = self.new_project()
        self.post("/api/v1/cell/up", {"project_id": project["id"]})
        status, _ = self.post("/api/v1/control", {"source": "policy"})
        self.assertGreaterEqual(status, 400)

    def test_mark_kind_is_restricted(self):
        project = self.new_project()
        session = self.record(project)
        path = f"/api/v1/sessions/{session['id']}/mark"
        self.assertEqual(self.post(path, {"kind": "explode"})[0], 400)
        self.assertEqual(self.post(path, {"kind": "annotation", "annotation": "x" * 257})[0], 400)

    def test_session_ids_must_be_uuids(self):
        self.assertGreaterEqual(
            self.post("/api/v1/sessions", {"project_id": "x", "request_id": "nope"})[0], 400
        )


class WorkflowTests(ApiTestCase):
    def test_cell_start_requires_an_existing_project(self):
        for body, expected in (
            ({}, 400),
            ({"project_id": ""}, 400),
            ({"project_id": str(uuid.uuid4())}, 404),
        ):
            status, result = self.post("/api/v1/cell/up", body)
            self.assertEqual(status, expected)
            self.assertTrue(result.get("error"))
            self.assertFalse(self.app.runtime.status()["cell_running"])

    def test_cannot_record_before_cell_and_teleop_are_ready(self):
        project = self.new_project()
        status, body = self.post(
            "/api/v1/sessions", {"project_id": project["id"], "request_id": str(uuid.uuid4())}
        )
        self.assertGreaterEqual(status, 400)
        self.assertTrue(body.get("error"))

    def test_cannot_select_teleop_while_cell_is_stopped(self):
        status, body = self.post("/api/v1/control", {"source": "teleop"})
        self.assertGreaterEqual(status, 400)
        self.assertTrue(body.get("error"))

    def test_unknown_project_is_rejected(self):
        project = self.new_project()
        self.post("/api/v1/cell/up", {"project_id": project["id"]})
        self.post("/api/v1/control", {"source": "teleop"})
        status, _ = self.post(
            "/api/v1/sessions", {"project_id": str(uuid.uuid4()), "request_id": str(uuid.uuid4())}
        )
        self.assertGreaterEqual(status, 400)

    def test_status_follows_the_record_button_lifecycle(self):
        project = self.new_project()
        _, idle = self.get("/api/v1/status")
        self.assertFalse(idle["runtime"]["cell_running"])
        session = self.record(project)
        _, live = self.get("/api/v1/status")
        self.assertTrue(live["runtime"]["cell_running"])
        self.assertEqual(live["runtime"]["active_source"], "teleop")
        self.assertEqual(live["runtime"]["active_episode_id"], session["id"])
        self.assertEqual(self.post(f"/api/v1/sessions/{session['id']}/mark", {"kind": "success"})[0], 200)
        _, done = self.get("/api/v1/status")
        self.assertFalse(done["runtime"].get("active_episode_id"))
        mine = [item for item in done["sessions"] if item["project_id"] == project["id"]]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["id"], session["id"])

    def test_retrying_with_the_same_request_id_returns_one_session(self):
        project = self.new_project()
        self.post("/api/v1/cell/up", {"project_id": project["id"]})
        self.post("/api/v1/control", {"source": "teleop"})
        body = {"project_id": project["id"], "request_id": str(uuid.uuid4())}
        first = self.post("/api/v1/sessions", body)
        second = self.post("/api/v1/sessions", body)
        self.assertEqual(first[0], 200)
        self.assertEqual(first[1]["id"], second[1]["id"])
        _, status = self.get("/api/v1/status")
        self.assertEqual(len(status["sessions"]), 1)

    def test_second_recording_is_refused_while_one_is_active(self):
        project = self.new_project()
        self.record(project)
        status, _ = self.post(
            "/api/v1/sessions", {"project_id": project["id"], "request_id": str(uuid.uuid4())}
        )
        self.assertGreaterEqual(status, 400)

    def test_cell_cannot_stop_during_recording_and_recovers_after(self):
        project = self.new_project()
        session = self.record(project)
        self.assertGreaterEqual(self.post("/api/v1/cell/down", {})[0], 400)
        self.post(f"/api/v1/sessions/{session['id']}/mark", {"kind": "cancel"})
        self.assertEqual(self.post("/api/v1/cell/down", {})[0], 200)
        _, status = self.get("/api/v1/status")
        self.assertFalse(status["runtime"]["cell_running"])

    def test_marking_unknown_or_finished_session_fails(self):
        project = self.new_project()
        session = self.record(project)
        path = f"/api/v1/sessions/{session['id']}/mark"
        self.assertEqual(self.post(path, {"kind": "failure"})[0], 200)
        self.assertGreaterEqual(self.post(path, {"kind": "success"})[0], 400)
        self.assertGreaterEqual(
            self.post(f"/api/v1/sessions/{uuid.uuid4()}/mark", {"kind": "success"})[0], 400
        )

    def test_demo_recordings_are_never_listed_as_accepted(self):
        project = self.new_project()
        session = self.record(project)
        self.post(f"/api/v1/sessions/{session['id']}/mark", {"kind": "success"})
        _, body = self.get("/api/v1/episodes")
        self.assertEqual([e for e in body["episodes"] if e.get("status") == "accepted"], [])

    def test_preview_is_not_available_in_demo_mode(self):
        project = self.new_project()
        self.post("/api/v1/cell/up", {"project_id": project["id"]})
        status, _ = self.call("/api/v1/preview.jpg")
        self.assertIn(status, (404, 503))


class SettingsTests(ApiTestCase):
    def test_token_is_write_only_through_the_api(self):
        secret = "hf_super_secret_value"
        self.assertEqual(self.post("/api/v1/settings", {"hf_token": secret, "hf_namespace": "acme"})[0], 200)
        status, data = self.call("/api/v1/settings")
        self.assertEqual(status, 200)
        self.assertNotIn(secret.encode(), data)
        self.assertEqual(json.loads(data), {"hf_token_set": True, "hf_namespace": "acme", "targets": []})
        _, status_body = self.call("/api/v1/status")
        self.assertNotIn(secret.encode(), status_body)

    def test_blank_token_keeps_saved_one_and_clear_removes_it(self):
        self.post("/api/v1/settings", {"hf_token": "hf_abc", "hf_namespace": "acme"})
        # The Settings page sends hf_token: undefined (omitted) when the field is blank.
        self.post("/api/v1/settings", {"hf_namespace": "other"})
        _, body = self.get("/api/v1/settings")
        self.assertEqual(body, {"hf_token_set": True, "hf_namespace": "other", "targets": []})
        self.assertEqual(self.post("/api/v1/settings", {"clear_hf_token": True})[0], 200)
        _, body = self.get("/api/v1/settings")
        self.assertFalse(body["hf_token_set"])
        self.assertEqual(body["hf_namespace"], "other")


if __name__ == "__main__":
    unittest.main()
