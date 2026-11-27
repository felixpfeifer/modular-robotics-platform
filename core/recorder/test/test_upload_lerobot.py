from __future__ import annotations

import json
import sys
import types

import pytest

from episode_recorder_py.upload_lerobot import upload_dataset, validate_dataset


def _dataset(root):
    (root / "meta" / "episodes").mkdir(parents=True)
    (root / "meta" / "info.json").write_text(
        json.dumps({"codebase_version": "v3.0"}), encoding="utf-8"
    )
    (root / "data" / "chunk-000").mkdir(parents=True)
    (root / "data" / "chunk-000" / "file-000.parquet").write_bytes(b"parquet")
    return root


def test_accepts_v3_layout_and_reopens_with_pinned_reader(tmp_path, monkeypatch):
    _install_fake_lerobot(monkeypatch)
    result = validate_dataset(_dataset(tmp_path))
    assert result["info"]["codebase_version"] == "v3.0"
    assert result["frames"] == 2
    assert result["episodes"] == 1


@pytest.mark.parametrize(
    ("path", "message"),
    [("info", "v3.0"), ("episodes", "v3.0"), ("parquet", "v3.0"), ("info", "v2.1")],
)
def test_rejects_incomplete_or_non_v3_layout(tmp_path, path, message):
    _dataset(tmp_path)
    if path == "info" and message == "v3.0":
        (tmp_path / "meta" / "info.json").unlink()
    elif path == "episodes":
        (tmp_path / "meta" / "episodes").rmdir()
    elif path == "parquet":
        (tmp_path / "data" / "chunk-000" / "file-000.parquet").unlink()
    else:
        (tmp_path / "meta" / "info.json").write_text('{"codebase_version":"v2.1"}')
    with pytest.raises(ValueError):
        validate_dataset(tmp_path)


def test_requires_explicit_confirmation_before_hub_import_or_network(tmp_path):
    with pytest.raises(ValueError, match="--confirm-upload"):
        upload_dataset(tmp_path, "user/dataset")


def test_private_upload_creates_private_repo_and_uploads_folder(
    tmp_path, monkeypatch, capsys
):
    _dataset(tmp_path)
    _install_fake_lerobot(monkeypatch)
    calls = []

    class FakeApi:
        def __init__(self, token=None):
            assert token is None

        def repo_info(self, **kwargs):
            calls.append(("repo_info", kwargs))
            error = RuntimeError("not found")
            error.response = types.SimpleNamespace(status_code=404)
            raise error

        def create_repo(self, **kwargs):
            calls.append(("create_repo", kwargs))

        def upload_folder(self, **kwargs):
            calls.append(("upload_folder", kwargs))
            return types.SimpleNamespace(oid="abc123commit")

    fake = types.ModuleType("huggingface_hub")
    fake.HfApi = FakeApi
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
    result = upload_dataset(tmp_path, "user/dataset", confirm_upload=True)
    assert calls[1][1]["private"] is True
    assert calls[2][1]["repo_type"] == "dataset"
    assert result.commit_revision == "abc123commit"
    assert result.frames == 2
    assert result.episodes == 1
    assert capsys.readouterr().out == ""


def test_public_requires_second_confirmation(tmp_path):
    _dataset(tmp_path)
    with pytest.raises(ValueError, match="--confirm-public"):
        upload_dataset(
            tmp_path, "user/dataset", visibility="public", confirm_upload=True
        )


def test_existing_visibility_must_match(tmp_path, monkeypatch):
    _dataset(tmp_path)
    _install_fake_lerobot(monkeypatch)

    class FakeApi:
        def __init__(self, **kwargs):
            pass

        def repo_info(self, **kwargs):
            return types.SimpleNamespace(private=False)

    fake = types.ModuleType("huggingface_hub")
    fake.HfApi = FakeApi
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
    with pytest.raises(ValueError, match="visibility differs"):
        upload_dataset(tmp_path, "user/dataset", confirm_upload=True)


def test_frame_iteration_failure_blocks_hub_access(tmp_path, monkeypatch):
    _dataset(tmp_path)

    class BrokenDataset:
        num_episodes = 1

        def __init__(self, **kwargs):
            pass

        def __len__(self):
            return 2

        def __getitem__(self, index):
            raise OSError("unreadable frame")

    _install_fake_lerobot(monkeypatch, BrokenDataset)
    with pytest.raises(ValueError, match="full frame iteration failed"):
        upload_dataset(tmp_path, "user/dataset", confirm_upload=True)


def _install_fake_lerobot(monkeypatch, dataset_class=None):
    monkeypatch.setattr("episode_recorder_py.upload_lerobot.version", lambda _: "0.6.1")

    class FakeDataset:
        num_episodes = 1

        def __init__(self, **kwargs):
            assert "root" in kwargs

        def __len__(self):
            return 2

        def __getitem__(self, index):
            return {"index": index}

    module = types.ModuleType("lerobot.datasets.lerobot_dataset")
    module.LeRobotDataset = dataset_class or FakeDataset
    for name in ("lerobot", "lerobot.datasets"):
        package = types.ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    monkeypatch.setitem(sys.modules, "lerobot.datasets.lerobot_dataset", module)
