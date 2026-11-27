import json
import tempfile
import unittest
import uuid
from pathlib import Path

import yaml

from training_lerobot import hub_import

ROOT = Path(__file__).resolve().parents[1]


def fake_fetch(files):
    def fetch(args, destination, token):
        base = destination / args.subfolder if args.subfolder else destination
        base.mkdir(parents=True)
        for name in files:
            (base / name).write_text(
                json.dumps({"type": "act"}) if name == "config.json" else ""
            )
        return destination

    return fetch


class HubImportTests(unittest.TestCase):
    def args(self, root, *extra):
        return hub_import.parse_args(
            [
                "--repo-id",
                "me/act",
                "--runs-dir",
                root,
                "--run-id",
                str(uuid.uuid4()),
                *extra,
            ]
        )

    def test_imports_complete_checkpoint_into_run_layout(self):
        files = [
            "config.json",
            "model.safetensors",
            "policy_preprocessor.json",
            "policy_postprocessor.json",
        ]
        with tempfile.TemporaryDirectory() as root:
            args = self.args(root, "--subfolder", "checkpoints/last")
            self.assertEqual(hub_import.run(args, fake_fetch(files)), 0)
            run_dir = Path(root) / args.run_id
            self.assertTrue(
                (
                    run_dir
                    / "output/checkpoints/last/pretrained_model/model.safetensors"
                ).is_file()
            )
            meta = json.loads((run_dir / "job.json").read_text())
            self.assertEqual((meta["status"], meta["policy"]), ("complete", "act"))
            self.assertFalse((run_dir / ".download").exists())

    def test_incomplete_checkpoint_fails(self):
        with tempfile.TemporaryDirectory() as root:
            args = self.args(root)
            self.assertEqual(hub_import.run(args, fake_fetch(["config.json"])), 1)
            self.assertEqual(
                json.loads((Path(root) / args.run_id / "job.json").read_text())[
                    "status"
                ],
                "failed",
            )

    def test_rejects_unsafe_arguments(self):
        with tempfile.TemporaryDirectory() as root:
            for extra in (
                ["--subfolder", "../x"],
                ["--revision", "../x"],
                ["--subfolder", "/abs"],
            ):
                with self.assertRaises(SystemExit):
                    self.args(root, *extra)


class ComposeTests(unittest.TestCase):
    def load(self, name):
        return yaml.safe_load((ROOT / name).read_text())

    def test_training_services_match_agent_plan_checks(self):
        services = self.load("training.compose.yaml")["services"]
        self.assertEqual(set(services), {"train", "hub_import"})
        self.assertEqual(services["train"]["network_mode"], "none")
        for service in services.values():
            self.assertFalse(service.get("devices") or service.get("privileged"))
            source_mounts = [v for v in service["volumes"] if v.startswith(("/", "."))]
            self.assertEqual(
                set(source_mounts),
                {
                    "./ai_lerobot:/app/ai_lerobot:ro",
                    "./training_lerobot:/app/training_lerobot:ro",
                    "./policy_lerobot:/app/policy_lerobot:ro",
                },
            )

    def test_gpu_overlay_only_reserves_a_gpu_for_the_trainer(self):
        services = self.load("training.gpu.compose.yaml")["services"]
        self.assertEqual(set(services), {"train"})
        devices = services["train"]["deploy"]["resources"]["reservations"]["devices"]
        self.assertEqual(devices[0]["driver"], "nvidia")
        self.assertNotIn(
            "deploy", self.load("training.compose.yaml")["services"]["train"]
        )

    def test_policy_services_match_agent_plan_checks(self):
        services = self.load("policy.compose.yaml")["services"]
        self.assertEqual(set(services), {"act_server", "policy_source"})
        self.assertTrue(
            all(v.endswith(":ro") for v in services["act_server"]["volumes"])
        )
        self.assertEqual(
            services["policy_source"]["volumes"],
            [
                "../control_arbiter/control_arbiter:"
                "/ws/install/control_arbiter/lib/python3.12/site-packages/control_arbiter:ro"
            ],
        )
        self.assertNotIn("ports", services["act_server"])


if __name__ == "__main__":
    unittest.main()
