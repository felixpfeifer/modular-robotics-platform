import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from training_lerobot import job
from policy_lerobot.contract import safe_action, JOINTS


class ModelTests(unittest.TestCase):
    def options(self, policy, *extra):
        return job.parse_args(
            [
                "--policy",
                policy,
                "--dataset",
                "/data",
                "--repo-id",
                "local/task",
                "--runs-dir",
                "/runs",
                *extra,
            ]
        )

    def test_models_get_correct_training_arguments(self):
        act = job.command(self.options("act"), "/data", "/out")
        self.assertIn("--policy.type=act", act)
        for name in ("smolvla", "groot"):
            options = self.options(name, "--base-model", "/model")
            cmd = job.command(options, "/data", "/out")
            self.assertIn("--policy.path=/model", cmd)
            self.assertFalse(
                any(
                    "pretrained_backbone_weights" in x or "chunk_size" in x for x in cmd
                )
            )
        options = self.options("groot", "--base-model", "/model")
        options.groot_foundation = True
        cmd = job.command(options, "/data", "/out")
        self.assertIn("--policy.base_model_path=/model", cmd)
        self.assertIn("--policy.embodiment_tag=new_embodiment", cmd)

    def test_checkpoint_type_checked(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path / "config.json").write_text(json.dumps({"type": "smolvla"}))
            for f in (
                "model.safetensors",
                "policy_preprocessor.json",
                "policy_postprocessor.json",
            ):
                (path / f).touch()
            job.inspect_base_model(path, "smolvla")
            with self.assertRaises(ValueError):
                job.inspect_base_model(path, "groot")

    def test_action_bounds_and_delta(self):
        state = [0.0] * len(JOINTS)
        self.assertEqual(safe_action(state, state, 0.15), state)
        with self.assertRaises(ValueError):
            safe_action([0.2] + state[1:], state, 0.15)
        with self.assertRaises(ValueError):
            safe_action(state[:-1] + [-0.01], state, 0.15)


class ServerModelSelectionTests(unittest.TestCase):
    def test_server_loads_the_selected_lerobot_policy(self):
        import sys
        import types
        from unittest.mock import MagicMock, patch
        from policy_lerobot.server import LeRobotPolicy

        with tempfile.TemporaryDirectory() as root:
            checkpoint = Path(root)
            for filename in (
                "model.safetensors",
                "policy_preprocessor.json",
                "policy_postprocessor.json",
            ):
                (checkpoint / filename).touch()
            model = MagicMock()
            model.to.return_value.eval.return_value = model
            model.config.input_features = {
                "observation.state": types.SimpleNamespace(shape=(6,)),
                "observation.images.top": types.SimpleNamespace(shape=(3, 480, 640)),
            }
            model.config.output_features = {"action": types.SimpleNamespace(shape=(6,))}
            policy_class = MagicMock()
            policy_class.from_pretrained.return_value = model
            factory = MagicMock(return_value=policy_class)
            modules = {
                "torch": types.SimpleNamespace(device=lambda x: x),
                "lerobot": types.ModuleType("lerobot"),
                "lerobot.policies": types.SimpleNamespace(
                    make_pre_post_processors=MagicMock(return_value=(None, None))
                ),
                "lerobot.policies.factory": types.SimpleNamespace(
                    get_policy_class=factory
                ),
            }
            with patch.dict(sys.modules, modules):
                for name in ("act", "smolvla", "groot"):
                    (checkpoint / "config.json").write_text(json.dumps({"type": name}))
                    adapter = LeRobotPolicy(
                        checkpoint, "cpu", name, "pick up the object"
                    )
                    factory.assert_called_with(name)
                    self.assertEqual(adapter.policy, name)
                    policy_class.from_pretrained.assert_called_with(str(checkpoint))
