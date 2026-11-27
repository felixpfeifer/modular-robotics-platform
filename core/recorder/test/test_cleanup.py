import json
import sys
import uuid
from pathlib import Path

from episode_recorder_py.cleanup import main


def _episode(root: Path, status: str, validated_at: float = 0.0) -> Path:
    episode_id = str(uuid.uuid4())
    episode = root / "episodes" / episode_id
    (episode / "bag").mkdir(parents=True)
    (episode / "bag/episode.mcap").write_bytes(b"fixture")
    (episode / "manifest.json").write_text(
        json.dumps({"episode_id": episode_id, "finalized_ns": 1}), encoding="utf-8"
    )
    (episode / "status.json").write_text(
        json.dumps({"status": status, "validated_at_unix": validated_at}),
        encoding="utf-8",
    )
    return episode


def test_cleanup_is_dry_run_and_deletes_only_finalized_expired_rejections(
    tmp_path, monkeypatch
):
    rejected = _episode(tmp_path, "rejected")
    accepted = _episode(tmp_path, "accepted")
    malformed = tmp_path / "episodes/ep_7"
    malformed.mkdir(parents=True)

    monkeypatch.setattr(sys, "argv", ["cleanup", "--dataset-dir", str(tmp_path)])
    assert main() == 0
    assert rejected.exists() and accepted.exists() and malformed.exists()

    monkeypatch.setattr(
        sys, "argv", ["cleanup", "--dataset-dir", str(tmp_path), "--delete"]
    )
    assert main() == 0
    assert not rejected.exists()
    assert accepted.exists() and malformed.exists()
