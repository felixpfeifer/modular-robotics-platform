"""Read recorder reports and freeze selections without changing raw artifacts."""

import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path

from . import mcap


def canonical_uuid(value):
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def read_json(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path.name}.")
    return value


class Artifacts:
    def __init__(self, dataset_dir):
        self.root = Path(dataset_dir).resolve() / "episodes"

    def episode(self, ident):
        if not canonical_uuid(ident):
            raise ValueError("Episode ID must be a canonical UUID.")
        path = self.root / ident
        if path.is_symlink() or path.resolve().parent != self.root or not path.is_dir():
            raise FileNotFoundError("Episode artifact not found.")
        result = {"id": ident, "status": "recorded", "manifest": {}, "validation": None}
        for filename, key in (
            ("manifest.json", "manifest"),
            ("status.json", "status_document"),
            ("validation/validation.json", "validation"),
        ):
            candidate = path / filename
            if candidate.resolve().is_relative_to(path.resolve()) and candidate.is_file():
                result[key] = read_json(candidate)
        result["status"] = result.get("status_document", {}).get("status", "recorded")
        return result

    def folder(self, ident):
        """Validated episode directory (canonical UUID, real directory, directly under the root)."""
        if not canonical_uuid(ident):
            raise ValueError("Episode ID must be a canonical UUID.")
        path = self.root / ident
        if path.is_symlink() or path.resolve().parent != self.root or not path.is_dir():
            raise FileNotFoundError("Episode artifact not found.")
        return path

    def mcap_files(self, ident):
        path = self.folder(ident)
        return sorted(
            f
            for f in path.rglob("*.mcap")
            if not f.is_symlink() and f.resolve().is_relative_to(path.resolve())
        )

    def disk_usage(self, ident):
        path = self.folder(ident)
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())

    def inspect(self, ident):
        """Episode plus what the MCAP itself says: topics, message counts, duration, size on disk."""
        result = self.episode(ident)
        files = self.mcap_files(ident)
        result["size_bytes"] = self.disk_usage(ident)
        result["mcap"] = None
        result["mcap_error"] = None
        if len(files) == 1:
            try:
                result["mcap"] = {"file": files[0].name, **mcap.summarize(files[0])}
            except (mcap.McapError, OSError) as exc:
                result["mcap_error"] = str(exc)
        elif files:
            result["mcap_error"] = f"Expected one MCAP file, found {len(files)}."
        else:
            result["mcap_error"] = "No MCAP file in this episode folder."
        return result

    def delete(self, ident):
        """Remove an episode folder. Callers decide whether that is allowed."""
        path = self.folder(ident)
        freed = self.disk_usage(ident)
        shutil.rmtree(path)
        return freed

    def list(self):
        episodes, errors = [], []
        if not self.root.is_dir():
            return episodes, errors
        for path in self.root.iterdir():
            if not canonical_uuid(path.name) or path.is_symlink() or not path.is_dir():
                continue
            try:
                episodes.append(self.episode(path.name))
            except (OSError, ValueError) as exc:
                errors.append({"id": path.name, "error": str(exc)})
        episodes.sort(key=lambda item: item["manifest"].get("started_ns", 0), reverse=True)
        return episodes, errors

    def selection(self, ids):
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("Select one or more unique accepted episodes.")
        selected = []
        for ident in ids:
            episode = self.episode(ident)
            manifest, validation = episode["manifest"], episode["validation"] or {}
            digest = manifest.get("content_hash", "")
            if episode["status"] != "accepted" or not validation.get("valid"):
                raise ValueError(f"Episode {ident} has not passed validation.")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise ValueError(f"Episode {ident} has no valid MCAP digest.")
            if validation.get("artifact_hash") != digest:
                raise ValueError(f"Episode {ident} has stale validation evidence.")
            path = self.root / ident
            files = list(path.rglob("*.mcap"))
            if len(files) != 1 or files[0].is_symlink() or not files[0].resolve().is_relative_to(path):
                raise ValueError(f"Episode {ident} must contain exactly one local MCAP file.")
            sha = hashlib.sha256()
            with files[0].open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    sha.update(chunk)
            if "sha256:" + sha.hexdigest() != digest:
                raise ValueError(f"Episode {ident} MCAP changed after validation.")
            selected.append(
                {"episode_id": ident, "content_hash": digest, "started_ns": manifest["started_ns"]}
            )
        selected.sort(key=lambda item: (item["started_ns"], item["episode_id"]))
        return {"schema_version": "accepted-episodes/v1", "episodes": selected}
