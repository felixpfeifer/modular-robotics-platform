import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from mrp_app.errors import AgentRejected, AppError
from mrp_app.runtime import DemoRuntime
from mrp_app.service import Application


class WorkflowRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.app = Application(Path(self.directory), DemoRuntime(), agent_url="http://agent")
        self.addCleanup(self.app.close)
        self.project_id = self.app.create_project({"name": "Test project"})["id"]

    def recording_request(self):
        self.app.cell("up", self.project_id)
        self.app.select_source({"source": "teleop"})
        return {"request_id": str(uuid.uuid4()), "project_id": self.project_id}

    def test_late_result_resolves_timed_out_start_once(self):
        body = self.recording_request()
        captured = {}

        def start(ident, snapshot, finished):
            captured.update(ident=ident, finished=finished)
            raise TimeoutError("Recorder did not respond.")

        with patch.object(self.app.runtime, "start", side_effect=start) as runtime:
            with self.assertRaises(AppError):
                self.app.start(body)
            self.assertEqual(self.app.start(body)["state"], "interrupted")
            runtime.assert_called_once()

        other = self.app.start({**body, "request_id": str(uuid.uuid4())})
        captured["finished"](captured["ident"], "recorded", "Saved")
        captured["finished"](captured["ident"], "rejected", "Duplicate callback")
        result = self.app.start(body)
        self.assertEqual(
            (result["id"], result["state"], result["detail"]), (captured["ident"], "recorded", "Saved")
        )
        self.assertEqual(self.app.start({**body, "request_id": other["request_id"]})["state"], "recording")

    def test_start_timeout_does_not_replace_a_result_that_arrived_first(self):
        body = self.recording_request()

        def start(ident, snapshot, finished):
            finished(ident, "recorded", "Saved")
            raise TimeoutError("Recorder request timed out.")

        with patch.object(self.app.runtime, "start", side_effect=start), self.assertRaises(AppError):
            self.app.start(body)
        self.assertEqual(self.app.start(body)["state"], "recorded")

    def test_uncertain_export_can_reconcile_but_never_restarts(self):
        self.app.runtime.mode = "ros"
        body = {
            "request_id": str(uuid.uuid4()),
            "project_id": self.project_id,
            "episode_ids": [str(uuid.uuid4())],
        }
        with (
            patch.object(self.app, "snapshot_for", return_value={}),
            patch.object(self.app.artifacts, "selection", return_value={}),
            patch("mrp_app.service.remote_json", return_value=[]) as remote,
            self.assertLogs("mrp_app.jobs", "WARNING"),
        ):
            job = self.app.export(body)
            self.app.jobs.wait(5)
            self.assertEqual(self.app.export(body)["state"], "interrupted")
            remote.assert_called_once()

        report = self.app.exports_dir / job["id"] / "report.json"
        for invalid in ([], {"job_id": str(uuid.uuid4()), "state": "complete"}):
            report.write_text(json.dumps(invalid))
            self.assertEqual(self.app.status()["jobs"][0]["state"], "interrupted")
        report.write_text(json.dumps({"job_id": job["id"], "state": "complete", "detail": "External text"}))
        self.assertEqual(self.app.status()["jobs"][0]["state"], "complete")
        self.assertNotIn("External text", self.app.status()["jobs"][0]["detail"])

    def training_request(self):
        export_id = str(uuid.uuid4())
        self.app.store.execute(
            "INSERT INTO jobs (id,request_id,state,created,payload,project_id) VALUES (?,?,?,?,?,?)",
            (export_id, str(uuid.uuid4()), "complete", 1, "{}", self.project_id),
        )
        return {
            "request_id": str(uuid.uuid4()),
            "project_id": self.project_id,
            "export_id": export_id,
            "settings": {"smoke": True},
        }

    @staticmethod
    def checkpoint_report(payload):
        ident = payload["run_id"]
        return {
            "run_id": ident,
            "status": "complete",
            "checkpoint": f"{ident}/output/checkpoints/last/pretrained_model",
        }

    def test_training_completion_rolls_back_if_the_model_insert_fails(self):
        body = self.training_request()
        self.app.store.execute(
            "CREATE TRIGGER reject_model BEFORE INSERT ON models "
            "BEGIN SELECT RAISE(ABORT,'test insert failed'); END;"
        )
        with (
            patch.object(self.app, "hardware", return_value={"gpu": False}),
            patch(
                "mrp_app.service.remote_json",
                side_effect=lambda _url, _path, payload, **_: self.checkpoint_report(payload),
            ),
            self.assertLogs("mrp_app.jobs", "ERROR") as logs,
        ):
            self.app.train(body)
            self.app.jobs.wait(5)
        training = self.app.store.rows("SELECT * FROM trainings")[0]
        self.assertEqual((training["state"], training["checkpoint"]), ("failed", None))
        self.assertEqual(self.app.store.rows("SELECT * FROM models"), [])
        self.assertNotIn("test insert failed", "\n".join(logs.output))

    def test_abort_acknowledgement_cannot_overwrite_completed_training(self):
        body = self.training_request()
        started, finish = threading.Event(), threading.Event()
        self.addCleanup(finish.set)

        def remote(_agent, path, payload, **_):
            if path == "/api/v1/trainings":
                started.set()
                if not finish.wait(5):
                    raise TimeoutError("Training test did not release its worker.")
                return self.checkpoint_report(payload)
            self.assertEqual(path, "/api/v1/trainings/abort")
            finish.set()
            self.app.jobs.wait(5)
            return {"run_id": payload["run_id"], "state": "aborting"}

        with (
            patch.object(self.app, "hardware", return_value={"gpu": False}),
            patch("mrp_app.service.remote_json", remote),
        ):
            job = self.app.train(body)
            self.assertTrue(started.wait(5))
            self.assertEqual(self.app.abort_training(job["id"])["state"], "aborting")
        training = self.app.store.rows("SELECT * FROM trainings")[0]
        self.assertEqual(training["state"], "complete")
        self.assertIn("checkpoint was written", training["detail"])
        self.assertEqual(self.app.store.rows("SELECT id FROM models"), [{"id": job["id"]}])

    def test_only_a_confirmed_abort_becomes_aborted(self):
        body = self.training_request()

        def remote(_url, _path, payload, **_):
            raise AgentRejected("Raw remote error", aborted_run=payload["run_id"])

        with (
            patch.object(self.app, "hardware", return_value={"gpu": False}),
            patch("mrp_app.service.remote_json", side_effect=remote),
        ):
            self.app.train(body)
            self.app.jobs.wait(5)
        training = self.app.store.rows("SELECT * FROM trainings")[0]
        self.assertEqual(training["state"], "aborted")
        self.assertNotIn("Raw remote error", training["detail"])
