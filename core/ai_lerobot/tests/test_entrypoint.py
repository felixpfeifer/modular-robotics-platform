import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_lerobot.__main__ import main, upload


class EntrypointTests(unittest.TestCase):
    def test_upload_uses_private_model_repo_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as root:
            checkpoint = Path(root)
            (checkpoint / "config.json").write_text(json.dumps({"type": "act"}))
            for filename in (
                "model.safetensors",
                "policy_preprocessor.json",
                "policy_postprocessor.json",
            ):
                (checkpoint / filename).touch()
            with (
                patch("ai_lerobot.__main__.os.environ", {}),
                patch(
                    "sys.modules",
                    {"huggingface_hub": types.SimpleNamespace(HfApi=MagicMock())},
                ) as modules,
            ):
                api = modules["huggingface_hub"].HfApi.return_value
                upload(checkpoint, "me/model", "secret")
                api.create_repo.assert_called_once_with(
                    repo_id="me/model", repo_type="model", private=True, exist_ok=True
                )
                api.upload_folder.assert_called_once_with(
                    repo_id="me/model", repo_type="model", folder_path=root
                )

    def test_no_token_rejects_upload_before_training(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("ai_lerobot.__main__.job.run") as run,
        ):
            with self.assertRaises(SystemExit):
                main(
                    [
                        "train",
                        "--hub-repo",
                        "me/model",
                        "--dataset",
                        "/data",
                        "--repo-id",
                        "local/task",
                        "--runs-dir",
                        "/output",
                    ]
                )
            run.assert_not_called()

    def test_training_saves_then_uploads_only_on_success(self):
        args = [
            "train",
            "--hub-repo",
            "me/model",
            "--dataset",
            "/data",
            "--repo-id",
            "local/task",
            "--runs-dir",
            "/output",
        ]
        with (
            patch.dict(os.environ, {"HF_TOKEN": "example"}),
            patch("ai_lerobot.__main__.job.run", return_value=0),
            patch("ai_lerobot.__main__.upload") as upload,
        ):
            self.assertEqual(main(args), 0)
            self.assertEqual(upload.call_args.args[1:], ("me/model", "example", True))
        with (
            patch.dict(os.environ, {"HF_TOKEN": "example"}),
            patch("ai_lerobot.__main__.job.run", return_value=1),
            patch("ai_lerobot.__main__.upload") as upload,
        ):
            self.assertEqual(main(args), 1)
            upload.assert_not_called()

    def test_upload_failure_does_not_delete_checkpoint_or_print_token(self):
        with tempfile.TemporaryDirectory() as root:
            checkpoint = Path(root)
            (checkpoint / "config.json").write_text(json.dumps({"type": "act"}))
            for filename in (
                "model.safetensors",
                "policy_preprocessor.json",
                "policy_postprocessor.json",
            ):
                (checkpoint / filename).touch()
            with (
                patch.dict(os.environ, {"HF_TOKEN": "secret"}),
                patch("ai_lerobot.__main__.upload", side_effect=RuntimeError("secret")),
                patch("sys.stderr") as stderr,
            ):
                self.assertEqual(
                    main(["upload", "--checkpoint", root, "--hub-repo", "me/model"]), 1
                )
                self.assertTrue((checkpoint / "model.safetensors").exists())
                self.assertNotIn("secret", str(stderr.write.call_args_list))


if __name__ == "__main__":
    unittest.main()
