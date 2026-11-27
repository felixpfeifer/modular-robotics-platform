import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from mrp_app import dataset_validation


class DatasetValidationTests(unittest.TestCase):
    def test_zip_structural_check_and_invalid_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "dataset.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "dataset/meta/info.json", json.dumps({"codebase_version": "v3.0", "total_frames": 5})
                )
                archive.writestr("dataset/meta/episodes/chunk/file.parquet", b"placeholder")
                archive.writestr("dataset/data/chunk/file.parquet", b"placeholder")
            result = dataset_validation.validate_zip(path)
            self.assertTrue(result["valid"])
            self.assertIn("not validated", result["scope"])
            with zipfile.ZipFile(path, "a") as archive:
                archive.writestr("../unsafe", b"unsafe")
            with self.assertRaisesRegex(ValueError, "unsafe"):
                dataset_validation.validate_zip(path)

    def test_missing_files_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "episode metadata"):
            dataset_validation.validate_files([], {"codebase_version": "v3.0"})
        with self.assertRaisesRegex(ValueError, "v3.0"):
            dataset_validation.validate_files([], {"codebase_version": "v2.1"})

    def test_hub_metadata_requires_valid_repository(self):
        with patch.object(dataset_validation.hub, "get_json") as get:
            with self.assertRaises(ValueError):
                dataset_validation.validate_hub("../bad", "token")
            get.assert_not_called()
