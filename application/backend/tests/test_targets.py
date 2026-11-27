import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from mrp_app import hub
from mrp_app.runtime import DemoRuntime
from mrp_app.service import AppError, Application
from mrp_app.settings import Settings, check_target_url

GROOT = {"id": "gpu-box", "name": "GPU box", "runtime": "groot", "url": "tcp://gpu.example:5555"}


class TargetSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_url_scheme_follows_runtime(self):
        self.assertEqual(check_target_url("groot", "tcp://gpu.example:5555"), "tcp://gpu.example:5555")
        for runtime, url in (
            ("groot", "http://gpu.example:5555"),
            ("lerobot_async", "tcp://gpu.example:8080"),
            ("groot", "tcp://gpu.example"),
            ("groot", "tcp://user@gpu.example:5555"),
            ("groot", "tcp://gpu.example:5555/path"),
            ("nope", "tcp://gpu.example:5555"),
        ):
            with self.assertRaises(ValueError, msg=url):
                check_target_url(runtime, url)

    def test_own_token_is_encrypted_and_never_public(self):
        public = self.settings.update({"target_upsert": {**GROOT, "token_mode": "own", "token": "hf_secret"}})
        self.assertEqual(public["targets"][0]["token_set"], True)
        self.assertNotIn("hf_secret", json.dumps(public))
        self.assertNotIn("hf_secret", self.settings.path.read_text())
        self.assertEqual(self.settings.target_token("gpu-box"), "hf_secret")

    def test_saved_mode_uses_the_saved_token_and_none_uses_nothing(self):
        self.settings.update({"hf_token": "hf_saved", "target_upsert": {**GROOT, "token_mode": "saved"}})
        self.assertEqual(self.settings.target_token("gpu-box"), "hf_saved")
        self.settings.update({"target_upsert": {**GROOT, "token_mode": "none"}})
        self.assertIsNone(self.settings.target_token("gpu-box"))

    def test_own_mode_needs_a_token_and_edit_keeps_it(self):
        with self.assertRaises(ValueError):
            self.settings.update({"target_upsert": {**GROOT, "token_mode": "own"}})
        self.settings.update({"target_upsert": {**GROOT, "token_mode": "own", "token": "hf_a"}})
        self.settings.update({"target_upsert": {**GROOT, "name": "Renamed", "token_mode": "own"}})
        self.assertEqual(self.settings.target_token("gpu-box"), "hf_a")

    def test_delete(self):
        self.settings.update({"target_upsert": {**GROOT, "token_mode": "none"}})
        self.assertEqual(self.settings.update({"target_delete": "gpu-box"})["targets"], [])


class ServiceTargetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(Path(self.temp.name), DemoRuntime())
        self.project = self.app.create_project({"name": "p"})
        self.app.update_settings({"hf_token": "hf_saved"})
        self.app.update_settings({"target_upsert": {**GROOT, "token_mode": "saved"}})

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def test_catalog_blocks_local_groot_without_gpu(self):
        runtimes = self.app.catalog()["runtimes"]
        self.assertFalse(runtimes["groot"]["local_available"])
        self.assertTrue(runtimes["lerobot_act"]["local_available"])

    def test_model_upload_requires_confirmation_and_records_result_without_token(self):
        model_id = str(uuid.uuid4())
        self.app.agent_url = "http://agent:8090"
        self.app.store.execute(
            "INSERT INTO models (id,project_id,source,label,path,state,created,payload) VALUES (?,?,?,?,?,?,?,?)",
            (
                model_id,
                self.project["id"],
                "local_training",
                "test",
                model_id + "/output/checkpoints/last/pretrained_model",
                "complete",
                1,
                "{}",
            ),
        )
        body = {
            "request_id": str(uuid.uuid4()),
            "model_id": model_id,
            "repo_id": "me/test",
            "visibility": "public",
            "confirm_upload": True,
        }
        with self.assertRaisesRegex(AppError, "Public upload"):
            self.app.upload_model(body)
        body["confirm_public"] = True
        with mock.patch(
            "mrp_app.service.remote_json",
            side_effect=lambda url, path, payload, **kw: {
                "job_id": payload["job_id"],
                "state": "complete",
                "revision": "a" * 40,
            },
        ):
            upload = self.app.upload_model(body)
            self.app.jobs.wait(5)
        row = self.app.store.rows("SELECT * FROM uploads WHERE id=?", (upload["id"],))[0]
        self.assertEqual(row["state"], "complete")
        self.assertNotIn("hf_saved", json.dumps(row))
        self.assertEqual(self.app.upload_model(body)["id"], upload["id"])

    def test_local_groot_is_refused_without_gpu(self):
        with self.assertRaises(AppError) as caught:
            self.app._check_runtime_choice("groot", "local")
        self.assertEqual(caught.exception.status, 409)

    def test_target_must_exist_and_match_runtime(self):
        self.assertEqual(self.app._check_runtime_choice("groot", "gpu-box")["id"], "gpu-box")
        for runtime, target in (("groot", "missing"), ("lerobot_async", "gpu-box")):
            with self.assertRaises(AppError):
                self.app._check_runtime_choice(runtime, target)

    def test_launch_command_does_not_contain_the_token_by_default(self):
        out = self.app.launch_command(
            {"purpose": "serve", "runtime": "groot", "target": "gpu-box", "repo_id": "me/gr00t-so101"}
        )
        self.assertIn("-e HF_TOKEN ", out["command"])
        self.assertIn("--model-path me/gr00t-so101", out["command"])
        self.assertNotIn("hf_saved", out["command"])
        self.assertFalse(out["token_included"])

    def test_launch_command_token_needs_confirmation(self):
        body = {"purpose": "serve", "runtime": "groot", "target": "gpu-box", "include_token": True}
        with self.assertRaises(AppError):
            self.app.launch_command(body)
        out = self.app.launch_command({**body, "confirm_token": True, "repo_id": "me/m"})
        self.assertIn("HF_TOKEN=hf_saved", out["command"])

    def test_launch_command_accepts_a_docker_hub_image(self):
        body = {"purpose": "serve", "runtime": "groot", "image": "acme/model:v1"}
        self.assertIn(" acme/model:v1 ", self.app.launch_command(body)["command"])
        with self.assertRaises(AppError):
            self.app.launch_command({**body, "image": "acme/model;touch /tmp/x"})

    def test_hub_ref_is_recorded_without_download(self):
        row = self.app.register_hub_model(
            {
                "request_id": str(uuid.uuid4()),
                "project_id": self.project["id"],
                "repo_id": "me/gr00t-so101",
                "runtime": "groot",
            }
        )
        self.assertEqual((row["kind"], row["runtime"], row["path"]), ("hub", "groot", ""))
        self.assertEqual(self.app.status()["models"][0]["repo_id"], "me/gr00t-so101")

    def test_remote_and_foreign_runtime_deploy_is_not_silently_accepted(self):
        for extra in ({"runtime": "groot", "target": "gpu-box"}, {"runtime": "groot", "target": "local"}):
            with self.assertRaises(AppError):
                self.app.train({"request_id": str(uuid.uuid4()), "project_id": self.project["id"], **extra})

    def test_hub_listing_needs_a_token(self):
        self.app.update_settings({"clear_hf_token": True})
        with self.assertRaises(AppError):
            self.app.hub_repos("models")


class HubTests(unittest.TestCase):
    def test_classifies_and_sizes_models(self):
        listing = [
            {
                "id": "me/groot",
                "tags": ["gr00t"],
                "siblings": [{"rfilename": "model.safetensors", "size": 12 * 10**9}],
            },
            {"id": "me/act", "tags": ["lerobot"], "siblings": [{"rfilename": "config.json", "size": 10}]},
            {"id": "bad name", "tags": [], "siblings": []},
        ]
        with mock.patch.object(hub, "get_json", return_value=listing):
            rows = hub.list_repos("models", "t", preferred="me")
        self.assertEqual([r["repo_id"] for r in rows], ["me/groot", "me/act"])
        self.assertEqual((rows[0]["runtime"], rows[0]["size"]), ("groot", 12 * 10**9))
        with mock.patch.object(hub, "get_json", return_value=listing):
            only = hub.list_repos("models", "t", preferred="me", runtime="groot")
        self.assertEqual([r["repo_id"] for r in only], ["me/groot"])


if __name__ == "__main__":
    unittest.main()
