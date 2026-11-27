"""Shareable configuration bundles: calibration, robot profiles, components and cell configs.

A bundle is a ``.tar.gz`` with a manifest that lists every file with its SHA-256 digest::

    manifest.json              schema, creation time, per-file digests, counts
    calibration/<name>.yaml    arm calibration files (the format the driver reads)
    robots/<id>.json           robot profiles (``robot-profile/v1``), for compatibility checks
    components.json            the catalog presets the cells use (``mrp-components/v1``)
    projects/<n>.json          one cell configuration per project (spec and layout)

Bundles contain no credentials, recordings, datasets or models. A bundle is untrusted input:
``read_bundle`` bounds its size, accepts only plain files with allow-listed names, checks the
digests and then validates every document with the same validators the API uses. Nothing is
written by this module; ``service.Application`` applies a bundle that passed all checks.
"""

import hashlib
import io
import json
import os
import re
import tarfile
import time

from . import layout as cell_layout
from .calibration import CALIBRATION_NAME, validate_calibration
from .catalog import PRESETS, CellSpecError, validate_spec

SCHEMA = "mrp-config-bundle/v1"
COMPONENTS_SCHEMA = "mrp-components/v1"
PROJECT_SCHEMA = "mrp-cell-config/v1"
ROBOT_SCHEMA = "robot-profile/v1"

MAX_COMPRESSED = 8 * 1024 * 1024
MAX_UNPACKED = 16 * 1024 * 1024
MAX_FILE = 1024 * 1024
MAX_MEMBERS = 400
ROBOT_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
PROJECT_FILE = re.compile(r"projects/[0-9]{1,3}\.json")
CALIBRATION_FILE = re.compile(r"calibration/(" + CALIBRATION_NAME.pattern + r")")
ROBOT_FILE = re.compile(r"robots/(" + ROBOT_ID.pattern + r")\.json")
FIXED_FILES = {"manifest.json", "components.json"}
BACKUP_NAME = re.compile(r"mrp-config-[0-9]{8}-[0-9]{6}(-[0-9]{1,3})?\.tar\.gz")


class BundleError(ValueError):
    """The bundle is not a valid MRP configuration bundle. The message says why."""


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _json(data):
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()


def components_snapshot(presets=None):
    """The catalog facts a receiver needs to judge whether a cell can run on its installation."""
    presets = PRESETS if presets is None else presets
    keys = ("label", "robot", "tasks", "hardware", "family", "simulation")
    return {
        "schema_version": COMPONENTS_SCHEMA,
        "presets": {ident: {k: preset[k] for k in keys} for ident, preset in sorted(presets.items())},
    }


def build_bundle(calibrations, projects, robots, app_version, now=None):
    """Return the bundle bytes. ``projects`` are rows of the projects table with parsed JSON."""
    files = {}
    for name, text in sorted(calibrations.items()):
        files[f"calibration/{name}"] = validate_calibration(text).encode()
    for ident, profile in sorted(robots.items()):
        if ROBOT_ID.fullmatch(ident) and isinstance(profile, dict):
            files[f"robots/{ident}.json"] = _json(profile)
    files["components.json"] = _json(components_snapshot())
    for index, project in enumerate(projects, 1):
        files[f"projects/{index}.json"] = _json(
            {
                "schema_version": PROJECT_SCHEMA,
                "name": project["name"],
                "preset": project["preset"],
                "cell": project["cell_spec"],
                "layout": project.get("cell_layout") or None,
            }
        )
    created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now or time.time()))
    manifest = {
        "schema_version": SCHEMA,
        "created": created,
        "app_version": app_version,
        "files": {name: {"sha256": _digest(data), "bytes": len(data)} for name, data in files.items()},
        "counts": {
            "calibrations": sum(1 for n in files if n.startswith("calibration/")),
            "robots": sum(1 for n in files if n.startswith("robots/")),
            "projects": sum(1 for n in files if n.startswith("projects/")),
        },
    }
    files["manifest.json"] = _json(manifest)
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        for name, data in [("manifest.json", files.pop("manifest.json")), *files.items()]:
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), int(now or time.time()), 0o644
            archive.addfile(info, io.BytesIO(data))
    return out.getvalue()


def _allowed(name):
    return name in FIXED_FILES or any(
        pattern.fullmatch(name) for pattern in (PROJECT_FILE, CALIBRATION_FILE, ROBOT_FILE)
    )


def _unpack(path):
    """Return {name: bytes} after bounding size and member types. Never extracts to disk."""
    if os.path.getsize(path) > MAX_COMPRESSED:
        raise BundleError(f"Bundle is larger than {MAX_COMPRESSED // 1024 // 1024} MB.")
    files, total = {}, 0
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            for member in archive:
                if len(files) >= MAX_MEMBERS:
                    raise BundleError("Bundle has too many files.")
                if not member.isreg():
                    raise BundleError(
                        f"Bundle contains something that is not a plain file: {member.name[:60]!r}."
                    )
                if not _allowed(member.name):
                    raise BundleError(f"Bundle contains an unexpected file: {member.name[:60]!r}.")
                if member.name in files:
                    raise BundleError(f"Bundle lists {member.name} twice.")
                if member.size > MAX_FILE:
                    raise BundleError(f"{member.name} is too large.")
                total += member.size
                if total > MAX_UNPACKED:
                    raise BundleError("Bundle is too large when unpacked.")
                handle = archive.extractfile(member)
                files[member.name] = handle.read(MAX_FILE + 1) if handle else b""
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise BundleError("This is not a readable .tar.gz bundle.") from exc
    return files


def _load(files, name):
    try:
        value = json.loads(files[name].decode())
    except (KeyError, ValueError, UnicodeError) as exc:
        raise BundleError(f"{name} is missing or is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise BundleError(f"{name} must be a JSON object.")
    return value


def _check_manifest(files):
    manifest = _load(files, "manifest.json")
    if manifest.get("schema_version") != SCHEMA:
        raise BundleError(f"Unsupported bundle version; expected {SCHEMA}.")
    listed = manifest.get("files")
    if not isinstance(listed, dict):
        raise BundleError("manifest.json has no file list.")
    payload = set(files) - {"manifest.json"}
    if set(listed) != payload:
        extra, missing = sorted(payload - set(listed)), sorted(set(listed) - payload)
        raise BundleError(
            "The bundle does not match its manifest"
            + (f"; not listed: {', '.join(extra[:3])}" if extra else "")
            + (f"; missing: {', '.join(missing[:3])}" if missing else "")
            + "."
        )
    for name in sorted(payload):
        entry = listed[name]
        if not isinstance(entry, dict) or entry.get("sha256") != _digest(files[name]):
            raise BundleError(f"{name} was changed after the bundle was created (checksum mismatch).")
    return manifest


def _check_robot(ident, profile, local):
    problems, notes = [], []
    if profile.get("schema_version") != ROBOT_SCHEMA:
        problems.append(f"robots/{ident}.json: unsupported schema; expected {ROBOT_SCHEMA}.")
    if profile.get("id") != ident:
        problems.append(f"robots/{ident}.json: id does not match the file name.")
    joints = profile.get("joint_names")
    if not (isinstance(joints, list) and joints and all(isinstance(j, str) and j for j in joints)):
        problems.append(f"robots/{ident}.json: joint_names must be a list of names.")
    if not isinstance(profile.get("topics"), dict):
        problems.append(f"robots/{ident}.json: topics must be an object.")
    status = "unknown"
    if not problems:
        mine = local.get(ident)
        if mine is None:
            notes.append(f"Robot '{ident}' is not installed here: its driver must be added before real use.")
        elif mine.get("joint_names") != joints:
            status = "differs"
            notes.append(f"Robot '{ident}' has different joints here than in the bundle.")
        else:
            status = "known"
    return {"id": ident, "label": str(profile.get("label", ident))[:60], "status": status}, problems, notes


def read_bundle(path, local_calibrations, local_robots, existing_names=()):
    """Validate a bundle file and describe what importing it would do.

    Returns ``{"errors": [...], "warnings": [...], "items": {...}, "payload": {...}}``. The payload
    (normalised documents) is only present when there are no errors. Raises BundleError for a file
    that cannot be treated as a bundle at all.
    """
    files = _unpack(path)
    manifest = _check_manifest(files)
    errors, warnings = [], []
    items = {"calibrations": [], "robots": [], "projects": []}
    payload = {"calibrations": {}, "projects": []}

    for name in sorted(files):
        match = CALIBRATION_FILE.fullmatch(name)
        if not match:
            continue
        try:
            text = validate_calibration(files[name].decode())
        except (ValueError, UnicodeError) as exc:
            errors.append(f"{name}: {exc}")
            continue
        mine = local_calibrations.get(match[1])
        status = "new" if mine is None else "identical" if mine == text else "conflict"
        items["calibrations"].append({"name": match[1], "status": status})
        payload["calibrations"][match[1]] = text

    bundled_robots = {}
    for name in sorted(files):
        match = ROBOT_FILE.fullmatch(name)
        if not match:
            continue
        try:
            profile = _load(files, name)
        except BundleError as exc:
            errors.append(str(exc))
            continue
        item, problems, notes = _check_robot(match[1], profile, local_robots)
        errors += problems
        warnings += notes
        bundled_robots[match[1]] = profile
        items["robots"].append(item)

    components = _load(files, "components.json")
    if components.get("schema_version") != COMPONENTS_SCHEMA or not isinstance(
        components.get("presets"), dict
    ):
        errors.append(f"components.json: unsupported; expected {COMPONENTS_SCHEMA} with a presets object.")
        components = {"presets": {}}

    taken = {n.lower() for n in existing_names}
    calibration_known = set(local_calibrations) | set(payload["calibrations"])
    for name in sorted(files, key=lambda n: (len(n), n)):
        if not PROJECT_FILE.fullmatch(name):
            continue
        try:
            doc = _load(files, name)
            if doc.get("schema_version") != PROJECT_SCHEMA or set(doc) - {
                "schema_version", "name", "preset", "cell", "layout",
            }:  # fmt: skip
                raise BundleError(f"{name}: unsupported cell configuration.")
            title = doc.get("name")
            if (
                not isinstance(title, str)
                or not 1 <= len(title.strip()) <= 80
                or any(ord(c) < 32 for c in title)
            ):
                raise BundleError(f"{name}: project name must be 1–80 printable characters.")
            try:
                spec, preset = validate_spec(doc.get("cell"))
            except CellSpecError as exc:
                raise BundleError(f"{name}: {exc}") from exc
            if doc.get("preset") != preset:
                raise BundleError(
                    f"{name}: preset {doc.get('preset')!r} does not match its components ({preset})."
                )
            theirs = components["presets"].get(preset, {})
            if theirs and theirs.get("robot") != PRESETS[preset]["robot"]:
                warnings.append(f"'{title}': the bundle was made for robot '{theirs.get('robot')}'.")
            layout = None
            if doc.get("layout") is not None:
                try:
                    layout = cell_layout.validate_layout(doc["layout"])
                except cell_layout.LayoutError as exc:
                    raise BundleError(f"{name}: {exc}") from exc
            for role, entry in (spec.get("devices") or {}).items():
                wanted = entry.get("calibration")
                if wanted and wanted not in calibration_known:
                    warnings.append(
                        f"'{title}' ({role}) needs calibration {wanted}, which is not available here."
                    )
            if spec.get("devices"):
                warnings.append(
                    f"'{title}' names USB ports: scan the devices again in Cell setup before starting it."
                )
        except BundleError as exc:
            errors.append(str(exc))
            continue
        renamed = f"{title.strip()} (imported)" if title.strip().lower() in taken else title.strip()
        taken.add(renamed.lower())
        items["projects"].append({"name": renamed, "original_name": title.strip(), "preset": preset})
        payload["projects"].append(
            {"name": renamed, "cell_spec": spec, "preset": preset, "cell_layout": layout}
        )

    summary = {
        "created": manifest.get("created", ""),
        "app_version": str(manifest.get("app_version", ""))[:20],
    }
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": sorted(set(warnings)),
        "items": items,
        "bundle": summary,
        "payload": None if errors else payload,
    }
