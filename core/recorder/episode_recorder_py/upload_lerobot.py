"""Explicitly upload a locally verified LeRobot Dataset v3 to the Hub."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path


@dataclass(frozen=True)
class UploadResult:
    repo_id: str
    commit_revision: str
    visibility: str
    frames: int
    episodes: int


def validate_dataset(dataset_dir: Path, repo_id: str = "local/validation") -> dict:
    """Open and read every frame of a LeRobot v3 dataset before any Hub request."""
    root = dataset_dir.expanduser()
    if root.is_symlink():
        raise ValueError("dataset path must not be a symlink")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("dataset path must be a directory")
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError(
            "dataset contains symlinks; refusing to upload paths outside the dataset"
        )

    info_path = root / "meta" / "info.json"
    if not info_path.is_file():
        raise ValueError(
            "missing meta/info.json; this is not a complete LeRobot dataset"
        )
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("meta/info.json is unreadable or invalid JSON") from exc
    if info.get("codebase_version") != "v3.0":
        raise ValueError("only LeRobot Dataset v3.0 is supported")
    if not (root / "meta" / "episodes").is_dir():
        raise ValueError("missing meta/episodes; dataset is incomplete")
    if not (root / "data").is_dir() or not any((root / "data").rglob("*.parquet")):
        raise ValueError("missing LeRobot parquet data files")
    if not any(path.is_file() for path in root.rglob("*")):
        raise ValueError("dataset is empty")

    try:
        installed_lerobot_version = version("lerobot")
    except Exception:
        raise ValueError(
            "local dataset verification requires lerobot==0.6.1 to be installed"
        ) from None
    if installed_lerobot_version != "0.6.1":
        raise ValueError("local dataset verification requires pinned lerobot==0.6.1")
    try:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset

        dataset = LeRobotDataset(repo_id=repo_id, root=root)
        frame_count = len(dataset)
        if frame_count <= 0:
            raise ValueError("LeRobot dataset contains no readable frames")
        for frame_index in range(frame_count):
            dataset[frame_index]
        episode_count = int(dataset.num_episodes)
    except Exception as exc:
        if (
            isinstance(exc, ValueError)
            and str(exc) == "LeRobot dataset contains no readable frames"
        ):
            raise
        raise ValueError(
            "LeRobot v3 local reopen or full frame iteration failed"
        ) from None
    finally:
        close = getattr(locals().get("dataset"), "finalize", None)
        if callable(close):
            close()

    if episode_count <= 0:
        raise ValueError("LeRobot dataset contains no episodes")
    return {"info": info, "frames": frame_count, "episodes": episode_count}


def upload_dataset(
    dataset_dir: Path,
    repo_id: str,
    *,
    visibility: str = "private",
    confirm_upload: bool = False,
    confirm_public: bool = False,
) -> UploadResult:
    """Upload after validation and explicit confirmation; credentials stay out of argv."""
    if not confirm_upload:
        raise ValueError("upload requires --confirm-upload")
    if visibility not in {"private", "public"}:
        raise ValueError("visibility must be private or public")
    if visibility == "public" and not confirm_public:
        raise ValueError("public upload also requires --confirm-public")
    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repo_id
    ):
        raise ValueError("repo id must have the form namespace/name")

    root = dataset_dir.expanduser()
    if root.is_symlink():
        raise ValueError("dataset path must not be a symlink")
    root = root.resolve(strict=True)
    verification = validate_dataset(root, repo_id=repo_id)
    # huggingface_hub resolves HF_TOKEN or the `hf auth login` credential store.
    # The token is never accepted as a command-line argument or printed.
    from huggingface_hub import HfApi

    api = HfApi(token=os.environ.get("HF_TOKEN") or None)
    try:
        repo = api.repo_info(repo_id=repo_id, repo_type="dataset")
    except Exception as exc:
        # A missing repo is normal. Distinguish it from auth/network errors without
        # printing exception text, which could include request details.
        if (
            getattr(exc, "response", None) is None
            or getattr(exc.response, "status_code", None) != 404
        ):
            raise RuntimeError(
                "could not inspect the Hub repository; check network and HF login"
            ) from None
        repo = None
    if repo is None:
        try:
            api.create_repo(
                repo_id=repo_id, repo_type="dataset", private=(visibility == "private")
            )
        except Exception:
            raise RuntimeError(
                "could not create the Hub repository; check permissions and visibility"
            ) from None
    elif bool(getattr(repo, "private", False)) != (visibility == "private"):
        raise ValueError(
            "existing repository visibility differs from requested visibility"
        )

    try:
        commit = api.upload_folder(
            folder_path=str(root),
            repo_id=repo_id,
            repo_type="dataset",
            commit_message="Upload verified LeRobot Dataset v3",
        )
    except Exception:
        raise RuntimeError(
            "Hub upload failed; check permissions, network, and repository quota"
        ) from None
    commit_revision = getattr(commit, "oid", None)
    if not commit_revision:
        raise RuntimeError("Hub reported success without a commit revision")
    return UploadResult(
        repo_id=repo_id,
        commit_revision=str(commit_revision),
        visibility=visibility,
        frames=verification["frames"],
        episodes=verification["episodes"],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", required=True, type=Path)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument(
        "--visibility", choices=("private", "public"), default="private"
    )
    parser.add_argument(
        "--confirm-upload",
        action="store_true",
        help="required acknowledgement that data will be sent to the Hub",
    )
    parser.add_argument(
        "--confirm-public",
        action="store_true",
        help="additional acknowledgement for a public repository",
    )
    args = parser.parse_args(argv)
    try:
        result = upload_dataset(
            args.dataset_dir,
            args.repo_id,
            visibility=args.visibility,
            confirm_upload=args.confirm_upload,
            confirm_public=args.confirm_public,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"upload refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
