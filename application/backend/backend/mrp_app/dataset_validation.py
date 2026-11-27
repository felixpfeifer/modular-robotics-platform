"""Bounded structural checks for external LeRobot datasets; no files are extracted."""

import json
import stat
import zipfile
from pathlib import PurePosixPath
from urllib.request import Request, urlopen

from . import hub


def validate_files(names, info):
    if not isinstance(info, dict) or info.get("codebase_version") != "v3.0":
        raise ValueError("Only LeRobot Dataset v3.0 is supported.")
    if not any(name.startswith("meta/episodes/") and name.endswith(".parquet") for name in names):
        raise ValueError("Missing LeRobot episode metadata parquet files.")
    if not any(name.startswith("data/") and name.endswith(".parquet") for name in names):
        raise ValueError("Missing LeRobot data parquet files.")
    return {
        "valid": True,
        "scope": "Structural check only: metadata and file names were checked; frames and file contents were not validated.",
        "version": "v3.0",
        "episodes": info.get("total_episodes"),
        "frames": info.get("total_frames"),
    }


def validate_zip(path):
    try:
        with zipfile.ZipFile(path) as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if not members or len(members) > 100000:
                raise ValueError("ZIP must contain between 1 and 100000 files.")
            for entry in members:
                part = PurePosixPath(entry.filename)
                if (
                    part.is_absolute()
                    or ".." in part.parts
                    or "\\" in entry.filename
                    or stat.S_ISLNK(entry.external_attr >> 16)
                ):
                    raise ValueError("ZIP contains an unsafe path or symbolic link.")
            roots = [
                m.filename[: -len("meta/info.json")] for m in members if m.filename.endswith("meta/info.json")
            ]
            if len(roots) != 1:
                raise ValueError("ZIP must contain exactly one meta/info.json.")
            prefix = roots[0]
            info_file = archive.getinfo(prefix + "meta/info.json")
            if info_file.file_size > 1024 * 1024:
                raise ValueError("Dataset metadata is too large.")
            info = json.loads(archive.read(info_file))
            return validate_files(
                [m.filename[len(prefix) :] for m in members if m.filename.startswith(prefix)], info
            )
    except (zipfile.BadZipFile, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("ZIP or dataset metadata is unreadable.") from exc


def validate_hub(repo_id, token):
    if not isinstance(repo_id, str) or not hub.REPO.fullmatch(repo_id):
        raise ValueError("Repository must use namespace/dataset syntax.")
    meta = hub.get_json(f"/datasets/{repo_id}?blobs=true", token)
    names = [entry.get("rfilename", "") for entry in meta.get("siblings", [])]
    request = Request(
        f"https://huggingface.co/datasets/{repo_id}/raw/main/meta/info.json",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("Dataset metadata is too large.")
        info = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise ValueError("Could not read valid LeRobot metadata from this Hub dataset.") from exc
    return validate_files(names, info)
