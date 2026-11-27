"""Model artifacts: safe checkpoint import and the canonical on-disk layout.

Every model lives in the training-runs volume as
``<run-uuid>/output/checkpoints/last/pretrained_model`` regardless of whether it
was trained locally, trained elsewhere (notebook / GPU server) or fetched from the Hub.
"""

import json
import shutil
import stat
import time
import uuid
import zipfile
from pathlib import PurePosixPath

REQUIRED = ("config.json", "model.safetensors", "policy_preprocessor.json", "policy_postprocessor.json")
MAX_FILES = 500
MAX_BYTES = 8 * 1024**3


class ModelImportError(ValueError):
    pass


def canonical_model_path(run_id):
    return f"{run_id}/output/checkpoints/last/pretrained_model"


def import_checkpoint_zip(archive, runs_dir, label=""):
    """Validate a zip of a pretrained_model folder and install it as a new run. Returns (run_id, path)."""
    try:
        zf = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ModelImportError("The file is not a valid zip archive.") from exc
    with zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        if not members or len(members) > MAX_FILES:
            raise ModelImportError(f"Archive must contain 1–{MAX_FILES} files.")
        if sum(m.file_size for m in members) > MAX_BYTES:
            raise ModelImportError("Archive is larger than 8 GiB when extracted.")
        for member in members:
            path = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            if path.is_absolute() or ".." in path.parts or "\\" in member.filename:
                raise ModelImportError("Archive contains an unsafe path.")
            if mode and stat.S_ISLNK(mode):
                raise ModelImportError("Archive contains a symbolic link.")
        # The checkpoint folder is wherever config.json sits (root, or inside a wrapper folder).
        roots = {
            str(PurePosixPath(m.filename).parent)
            for m in members
            if PurePosixPath(m.filename).name == "config.json"
        }
        roots = {r for r in roots if len(PurePosixPath(r).parts) <= 4}
        if len(roots) != 1:
            raise ModelImportError(
                "Archive must contain exactly one pretrained_model folder with config.json."
            )
        base = roots.pop()
        prefix = "" if base == "." else base + "/"
        present = {
            m.filename[len(prefix) :]: m
            for m in members
            if m.filename.startswith(prefix) and "/" not in m.filename[len(prefix) :]
        }
        missing = [name for name in REQUIRED if name not in present]
        if missing:
            raise ModelImportError(f"Checkpoint is missing {', '.join(missing)}.")
        try:
            config = json.loads(zf.read(present["config.json"]).decode())
        except (ValueError, UnicodeDecodeError) as exc:
            raise ModelImportError("config.json is not valid JSON.") from exc
        if config.get("type") != "act":
            raise ModelImportError("Only ACT policies are supported for now.")
        run_id = str(uuid.uuid4())
        run_dir = runs_dir / run_id
        target = run_dir / "output/checkpoints/last/pretrained_model"
        target.mkdir(parents=True)
        try:
            for name, member in present.items():
                with zf.open(member) as source, (target / name).open("wb") as out:
                    shutil.copyfileobj(source, out)
            (run_dir / "job.json").write_text(
                json.dumps(
                    {
                        "schema_version": "mrp-training-job/v1",
                        "run_id": run_id,
                        "status": "complete",
                        "source": "checkpoint_import",
                        "label": label,
                        "finished_unix": time.time(),
                        "checkpoint": str(target),
                    },
                    indent=2,
                )
                + "\n"
            )
        except Exception:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise
    return run_id, canonical_model_path(run_id)
