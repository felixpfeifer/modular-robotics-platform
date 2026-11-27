"""Camera models: which real camera driver a cell camera uses, and what it needs.

A cell camera picks two things, like an arm:

* the **model** (set on the camera module of the workspace layout): which kind of device it is,
  e.g. a plain USB webcam, an Intel RealSense or an IDS uEye camera, plus an optional variant;
* the **backend** (``cameras[].source`` in the cell spec): ``synthetic`` (mock) or, for a real
  camera, the model's driver id. ``gazebo_scene`` is the simulated tabletop camera.

Each model names its driver image, the device fields an entry may carry and how the deployment
agent reaches the hardware:

* ``video_node`` - one V4L2 node (``/dev/video*``), resolved by the agent and passed through alone;
* ``usb_bus`` - the vendor SDK talks to the camera over libusb. The USB device number can change
  while the driver runs (the IDS daemon uploads the firmware and the camera re-enumerates), so the
  service gets the host's USB bus (``/dev/bus/usb`` + the USB character-device rule), never
  ``privileged`` and never all of ``/dev``. See ``mrp_app.deployment.check_plan``;
* ``network`` - an IP camera the driver reaches over the cell network. No host device at all.

The models come from three places, merged by :func:`models` (built-in ids always win):

* **built-in** - :data:`BUILTIN` below, the first-party drivers;
* **discovered** - local Docker images labelled ``io.mrp.driver.kind=camera`` whose
  ``io.mrp.driver.manifest`` label describes the model (the deployment agent scans for them);
* **custom** - models a user added in the UI, stored by the application in a JSON file.

Discovered and custom models pass :func:`parse_manifest`: they may only use ``usb_bus`` or
``network`` access, never extra capabilities, and never the image of a built-in model.
"""

import json
import re
import threading

AVAILABLE, PLANNED = "available", "planned"
DEFAULT_MODEL = "opencv_usb"
MOCK_SOURCES = ("synthetic", "gazebo_scene")
SERIAL = re.compile(r"[A-Za-z0-9_-]{1,32}")
ADDRESS = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.:-]{0,252})")
# Docker Hub style references (optionally docker.io/, namespace, tag, digest). Also used by the catalog.
IMAGE_REFERENCE = re.compile(
    r"(?:docker\.io/)?(?:[a-z0-9]+(?:[-_][a-z0-9]+)*/)?"
    r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?"
    r"(?:@sha256:[a-f0-9]{64})?"
)
# Labels a camera driver image carries so the agent finds it (see the README, "Camera drivers").
LABEL_KIND, LABEL_MANIFEST, KIND_CAMERA = "io.mrp.driver.kind", "io.mrp.driver.manifest", "camera"
MODEL_ID = re.compile(r"[a-z][a-z0-9_]{1,31}")
VARIANT_ID = re.compile(r"[a-z0-9][a-z0-9_]{0,23}")
ARGUMENT = re.compile(r"[A-Za-z0-9_./:=@+-]{1,120}")
USB_VENDOR = re.compile(r"[0-9a-f]{4}")
USB_PRODUCT = re.compile(r"[a-z0-9]{0,40}")
EXTRA_ACCESS = ("usb_bus", "network")
MANIFEST_KEYS = {"id", "label", "access", "variants", "fps_type", "probe_command", "usb", "note"}
MAX_EXTRA_MODELS = 32

BUILTIN = {
    "opencv_usb": {
        "label": "USB webcam (UVC / OpenCV)",
        "status": AVAILABLE,
        "driver": "camera_opencv",
        "image": "mrp-camera-opencv",
        "access": "video_node",
        "connections": ["usb"],
        "variants": {},
        "fields": {"device": "/dev/video* (pick from the scan)"},
        "fps_type": "int",
    },
    "realsense": {
        "label": "Intel RealSense",
        "status": AVAILABLE,
        "driver": "camera_realsense",
        "image": "mrp-camera-realsense",
        "access": "usb_bus",
        "connections": ["usb"],
        "variants": {
            "d405": "D405",
            "d415": "D415",
            "d435": "D435",
            "d435i": "D435i",
            "d455": "D455",
        },
        "fields": {"serial": "camera serial number (empty = the first RealSense found)"},
        "fps_type": "int",
        # How the connection test starts the driver inside its image (followed by --ros-args ...).
        "probe_command": ["ros2", "run", "camera_realsense", "camera_node"],
        "note": "Color only for recording; depth is not recorded yet. Needs a USB 3 port.",
    },
    "ids_ueye": {
        "label": "IDS uEye (UI cameras)",
        "status": AVAILABLE,
        "driver": "camera_ids",
        "image": "mrp-camera-ids",
        "access": "usb_bus",
        "connections": ["usb", "gige"],
        "connections_available": ["usb"],
        "variants": {},
        "fields": {
            "serial": "camera serial number (empty = the first free uEye camera)",
            "connection": "usb or gige",
        },
        "fps_type": "float",
        "probe_command": ["/usr/local/bin/camera-ids-entrypoint.sh"],  # starts the uEye daemon first
        "note": "Build mrp-camera-ids locally with the IDS Software Suite (driver/camera_ids). "
        "GigE cameras need host networking, which cell services do not have yet: use USB.",
    },
}


class CameraModelError(ValueError):
    pass


# Discovered and custom models, replaced as a whole by set_extra() (one dict swap, no partial state).
_extra = {}
_extra_lock = threading.Lock()


def models():
    """Every camera model: the built-in ones first, then the custom and discovered ones."""
    return {**BUILTIN, **_extra}


def set_extra(extra):
    """Replace the custom and discovered models (already parsed by :func:`parse_manifest`)."""
    global _extra
    with _extra_lock:
        _extra = {k: v for k, v in (extra or {}).items() if k not in BUILTIN}


def _text(value, name, limit, required=True):
    if value is None and not required:
        return ""
    if not isinstance(value, str) or not value.strip() or len(value) > limit or not value.isprintable():
        raise CameraModelError(f"{name} must be 1-{limit} printable characters.")
    return value.strip()


def parse_manifest(raw, image, origin):
    """A discovered or custom camera model, validated. ``image`` is the driver image reference.

    Raises CameraModelError with a message for the user when anything is off.
    """
    if not isinstance(raw, dict):
        raise CameraModelError("The camera manifest must be a JSON object.")
    unknown = set(raw) - MANIFEST_KEYS
    if unknown:
        raise CameraModelError(f"Unknown manifest keys: {', '.join(sorted(unknown))}.")
    ident = raw.get("id")
    if not isinstance(ident, str) or not MODEL_ID.fullmatch(ident):
        raise CameraModelError("id must be 2-32 lowercase letters, digits or '_', starting with a letter.")
    if ident in BUILTIN or ident in MOCK_SOURCES or ident == "other":
        raise CameraModelError(f"id '{ident}' is reserved by a built-in camera.")
    if not isinstance(image, str) or len(image) > 255 or not IMAGE_REFERENCE.fullmatch(image):
        raise CameraModelError("image must be a Docker image name, optionally with a tag or digest.")
    builtin_images = {image_name(m["image"]).rsplit("/", 1)[-1] for m in BUILTIN.values()}
    if image.startswith("localhost/") or image_name(image).rsplit("/", 1)[-1] in builtin_images:
        raise CameraModelError(f"{image} is the image of a built-in camera; use that camera instead.")
    access = raw.get("access", "usb_bus")
    if access not in EXTRA_ACCESS:
        raise CameraModelError(f"access must be one of {', '.join(EXTRA_ACCESS)}.")
    fps_type = raw.get("fps_type", "int")
    if fps_type not in ("int", "float"):
        raise CameraModelError("fps_type must be int or float.")
    command = raw.get("probe_command")
    if (
        not isinstance(command, list)
        or not 1 <= len(command) <= 12
        or not all(isinstance(a, str) and ARGUMENT.fullmatch(a) for a in command)
    ):
        raise CameraModelError(
            "probe_command must list 1-12 arguments that start the driver node, "
            'e.g. ["ros2", "run", "camera_acme", "camera_node"].'
        )
    variants = raw.get("variants") or {}
    if (
        not isinstance(variants, dict)
        or len(variants) > 20
        or not all(isinstance(k, str) and VARIANT_ID.fullmatch(k) for k in variants)
    ):
        raise CameraModelError("variants must map up to 20 short lowercase ids to labels.")
    variants = {k: _text(v, f"variant '{k}'", 40) for k, v in variants.items()}
    model = {
        "label": _text(raw.get("label"), "label", 60),
        "status": AVAILABLE,
        "driver": ident,
        "image": image,
        "access": access,
        "connections": ["usb"] if access == "usb_bus" else ["network"],
        "variants": variants,
        "fields": {"serial": "camera serial number (empty = the first camera found)"}
        if access == "usb_bus"
        else {"address": "camera IP address or host name"},
        "fps_type": fps_type,
        "probe_command": list(command),
        "origin": origin,
    }
    usb = raw.get("usb")
    if usb is not None:
        if access != "usb_bus" or not isinstance(usb, dict) or set(usb) - {"vendor_id", "product"}:
            raise CameraModelError(
                'usb is only for usb_bus cameras: {"vendor_id": "1409", "product": "..."}.'
            )
        vendor, product = str(usb.get("vendor_id", "")).lower(), str(usb.get("product", "")).lower()
        if not USB_VENDOR.fullmatch(vendor) or not USB_PRODUCT.fullmatch(product):
            raise CameraModelError(
                "usb.vendor_id must be 4 hex digits; usb.product lowercase letters/digits."
            )
        model["usb"] = {"vendor_id": vendor, "product": product}
    if raw.get("note"):
        model["note"] = _text(raw["note"], "note", 280)
    return ident, model


def image_name(image):
    """``mrp-camera-ids`` for ``docker.io/mrp-camera-ids:latest``: the repository without tag/digest."""
    name = image.split("@", 1)[0]
    if name.startswith("docker.io/"):
        name = name[len("docker.io/") :]
    last = name.rsplit("/", 1)[-1]
    if ":" in last:
        name = name[: len(name) - len(last)] + last.split(":", 1)[0]
    return name


def parse_labels(labels, image):
    """The model a labelled driver image describes, or None when it is not a camera driver."""
    if not isinstance(labels, dict) or labels.get(LABEL_KIND) != KIND_CAMERA:
        return None
    try:
        raw = json.loads(labels.get(LABEL_MANIFEST) or "")
    except ValueError:
        raise CameraModelError(f"{image}: the {LABEL_MANIFEST} label is not valid JSON.") from None
    return parse_manifest(raw, image, "discovered")


def load_custom(path):
    """The custom models stored at ``path`` (missing file = none). Returns (models, problems)."""
    result, problems = {}, []
    try:
        stored = json.loads(path.read_text())
    except FileNotFoundError:
        return result, problems
    except (OSError, ValueError) as error:
        return result, [f"Custom cameras could not be read: {error}"]
    for entry in (stored.get("models") if isinstance(stored, dict) else None) or []:
        try:
            manifest = {k: v for k, v in entry.items() if k != "image"}
            ident, model = parse_manifest(manifest, entry.get("image"), "custom")
            result[ident] = model
        except (CameraModelError, AttributeError) as error:
            problems.append(
                f"Custom camera {entry.get('id', '?') if isinstance(entry, dict) else '?'}: {error}"
            )
    return result, problems


def to_manifest(ident, model):
    """The stored form of a custom model (what parse_manifest reads back)."""
    entry = {"id": ident, "image": model["image"], "label": model["label"], "access": model["access"],
             "fps_type": model["fps_type"], "probe_command": model["probe_command"]}  # fmt: skip
    for key in ("variants", "usb", "note"):
        if model.get(key):
            entry[key] = model[key]
    return entry


def merge(custom, discovered):
    """Custom models win over discovered ones with the same id; built-in ids are dropped from both."""
    extra = {k: v for k, v in discovered.items() if k not in BUILTIN}
    extra.update({k: v for k, v in custom.items() if k not in BUILTIN})
    return dict(list(extra.items())[:MAX_EXTRA_MODELS])


def is_real(source):
    return source in models()


def check_camera(model, variant=None):
    """The model exists and is available, and the variant (if any) belongs to it."""
    camera = models().get(model) if isinstance(model, str) else None
    if camera is None:
        raise CameraModelError(f"unknown camera model {model!r}.")
    if camera["status"] != AVAILABLE:
        raise CameraModelError(f"{camera['label']} is planned and cannot be selected yet.")
    if variant not in (None, "") and variant not in camera["variants"]:
        choices = ", ".join(camera["variants"]) or "none"
        raise CameraModelError(f"{camera['label']} has no variant {variant!r} (variants: {choices}).")
    return camera


def check_device(model, device):
    """Shape of a real camera's ``device`` entry for ``model``. Returns the cleaned entry."""
    camera = check_camera(model)
    if not isinstance(device, dict):
        raise CameraModelError("device must be an object.")
    allowed = {"serial"} | ({"device", "card"} if camera["access"] == "video_node" else set())
    if camera["access"] == "network":
        allowed = {"address"}
    if len(camera["connections"]) > 1:
        allowed.add("connection")
    if set(device) - allowed:
        raise CameraModelError(f"a {camera['label']} device may only contain: {', '.join(sorted(allowed))}.")
    clean = dict(device)
    if camera["access"] == "usb_bus" and clean.get("serial") not in (None, ""):
        if not isinstance(clean["serial"], str) or not SERIAL.fullmatch(clean["serial"]):
            raise CameraModelError("serial must be 1-32 letters, digits, '_' or '-'.")
    if camera["access"] == "network":
        address = clean.get("address")
        if not isinstance(address, str) or not ADDRESS.fullmatch(address):
            raise CameraModelError("address must be the camera's IP address or host name.")
    if "connection" in clean:
        if clean["connection"] not in camera["connections"]:
            raise CameraModelError(f"connection must be one of {', '.join(camera['connections'])}.")
        if clean["connection"] not in camera.get("connections_available", camera["connections"]):
            raise CameraModelError(f"{clean['connection']} connections are not supported in cells yet.")
    return clean


def describe(installed=None, problems=()):
    """The catalogue the UI shows. ``installed`` maps an image to whether it is on the host."""
    installed = installed or {}
    listed = {}
    for ident, model in models().items():
        entry = {**model, "origin": model.get("origin", "builtin")}
        if model["image"] in installed:
            entry["installed"] = installed[model["image"]]
        listed[ident] = entry
    return {"default": DEFAULT_MODEL, "mock_sources": list(MOCK_SOURCES), "models": listed,
            "problems": list(problems)}  # fmt: skip
