"""Build and validate the Compose plan for a selected cell."""

import json
import subprocess
from _thread import RLock
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import devices as hw
from mrp_app import cameras as camera_models
from mrp_app import components
from mrp_app.catalog import PRESETS, CellSpecError, validate_settings, validate_spec
from mrp_app.deployment import ALLOWED_BACKENDS, check_plan

Document = dict[str, Any]
Devices = dict[str, Document]


class Preset(Protocol):
    files: list[Path]
    project: str
    lock: RLock

    def run(
        self, action: str, doc: Document | None = None, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]: ...


OVERLAY_FILES = {  # base service -> overlay that gives it its real device
    "leader": "real_leader.compose.yaml",
    "follower": "real_follower.compose.yaml",
    "camera": "usb_camera.compose.yaml",
    "camera2": "usb_side_camera.compose.yaml",
}

# Building blocks of the generated overlay for extra arms and cameras. They mirror the base
# services in mock-cell/compose.yaml; relative paths resolve against that file's folder.
ARM_IMAGE, RECORDER_IMAGE, USB_CAMERA_IMAGE = "mrp-robot-so101", "mrp-episode-recorder", "mrp-camera-opencv"
ROS_ENV = {
    "RMW": "zenoh",
    "ROS_DOMAIN_ID": "${MOCK_ROS_DOMAIN_ID:-42}",
    "ZENOH_CONFIG_OVERRIDE": 'mode="client";connect/endpoints=["tcp/zenoh_router:${MOCK_ZENOH_PORT:-17447}"];'
    "scouting/multicast/enabled=false",
}
CELL_SERVICE = {
    "restart": "no",  # an arm must never power back on by itself
    "networks": ["mock_cell"],
    "depends_on": {"zenoh_router": {"condition": "service_started"}},
}
ARM_SOURCES = (
    "../../../../driver/robot_so101/src:/app/src:ro",
    "../../../../driver/robot_so101/docker:/app/docker:ro",
)
RECORDER_CONFIG = "../../../../core/recorder/config:/workspace/core/recorder/config:ro"
BRIDGE_COMMAND = ["ros2", "run", "episode_recorder", "joint_intent_bridge.py", "--ros-args", "-p"]
# SDK cameras (RealSense, IDS uEye) reach their camera over libusb: the USB bus, not one node.
USB_BUS = "/dev/bus/usb"
USB_CGROUP_RULE = "c 189:* rmw"  # USB device character nodes only
MOTION_ENTRYPOINT = [
    "/bin/bash", "-c", "source /opt/platform/install/setup.bash && cd /opt/mock && exec python3 mock_motion.py",
]  # fmt: skip


def robot_profiles(root: Path | None) -> dict[str, Document]:
    """Robot profiles shipped by the drivers (driver/*/profile.json), by id. The renderer validates them."""
    profiles: dict[str, Document] = {}
    if root is None:
        return profiles
    for path in sorted(Path(root).glob("driver/*/profile.json")):
        try:
            profile = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(profile, dict) and isinstance(profile.get("id"), str):
            profiles.setdefault(profile["id"], profile)
    return profiles


def cell_of(ident: str, body: Document) -> tuple[Document, Document]:
    """Validate the request as a cell of this preset: (settings, topology of every arm and camera)."""
    backends = ALLOWED_BACKENDS[ident]
    preset: Document = PRESETS[ident]
    spec = {"task_id": body.get("task_id") or preset["tasks"][0]}
    if "arms" not in body:
        spec.update(leader=backends["leader"], follower=backends["follower"])
    if "cameras" not in body:
        spec["camera"] = body.get("camera", "gazebo_scene" if preset["simulation"] else "synthetic")
    for key in ("devices", "settings", "images", "mock_motion", "arms", "cameras"):
        if key in body:
            spec[key] = body[key]
    try:
        clean, matched = validate_spec(spec)
        settings = validate_settings(clean.get("settings"))
    except CellSpecError as exc:
        raise ValueError(str(exc)) from exc
    if matched != ident:
        raise ValueError(f"These components make a '{matched}' cell, not a '{ident}' cell.")
    return settings, components.topology(components.expand(clean, settings))


def camera_of(cell: Document, ident: str) -> Document:
    return next(camera for camera in cell["cameras"] if camera["id"] == ident)


def camera_settings(camera: Document) -> dict[str, int | float]:
    return {key: camera[key] for key in ("width", "height", "fps")}


def variant(
    base: Preset,
    resolved: Devices | None,
    overlay: Path | None,
    overlay_dir: Path | None,
    factory: Callable[[list[Path], str], Preset],
) -> Preset:
    """The preset's Compose files plus the overlays for the selected devices and extra components."""
    services = {item["service"] for item in (resolved or {}).values() if item["kind"] != "sdk_camera"}
    overlays = [OVERLAY_FILES[service] for service in OVERLAY_FILES if service in services]
    files = list(base.files)
    if overlays:
        if overlay_dir is None:
            raise ValueError("The agent has no workspace root for device overlays.")
        files.extend(overlay_dir / name for name in overlays)
    if overlay is not None:
        files.append(overlay)
    if files == list(base.files):
        return base
    result = factory(files, base.project)
    result.lock = base.lock  # one operation at a time per Compose project
    return result


def device_env(
    resolved: Devices | None, cell: Document, settings: Document, mock_motion: bool
) -> dict[str, str]:
    """Compose variables for this start. Nothing here is edited by hand: it all comes from the UI."""
    env: dict[str, str] = {}
    for item in (resolved or {}).values():
        if item["service"] in ("leader", "follower"):
            env[f"{item['service'].upper()}_PORT"] = item["path"]
            env[f"{item['service'].upper()}_CALIBRATION"] = item["calibration"]
    for camera in cell["cameras"]:
        prefix = camera["env_prefix"]
        if prefix is None:
            continue
        for key, value in camera_settings(camera).items():
            env[f"{prefix}_{key.upper()}"] = str(value)
        env[f"{prefix}_TOPIC"] = camera["topic"]
        if resolved and camera["id"] in resolved and resolved[camera["id"]]["kind"] == "camera":
            env[f"{prefix}_DEVICE"] = resolved[camera["id"]]["path"]
    profiles = []
    if mock_motion:
        profiles.append("motion")
        motion = settings["mock_motion"]
        env.update(
            MOCK_MOTION_SEED=str(int(motion["seed"])),
            MOCK_MOTION_SPEED=repr(float(motion["speed"])),  # "1.0", never "1": ROS types it from the text
            MOCK_MOTION_MODE=motion["mode"],
        )
    if len(cell["cameras"]) > 1:
        profiles.append("side")
    if profiles:
        env["COMPOSE_PROFILES"] = ",".join(profiles)
    return env


def extra_services(
    cell: Document, resolved: Devices | None, images: dict[str, str], settings: Document, mock_motion: bool
) -> Document | None:
    """Compose overlay for a cell with more arms or cameras than the base file has, or None."""
    sdk_cameras = [
        c for c in cell["cameras"] if c["source"] != "opencv_usb" and camera_models.is_real(c["source"])
    ]
    if not cell["multi_arm"] and len(cell["cameras"]) <= 2 and not sdk_cameras:
        return None
    resolved = resolved or {}
    services: dict[str, Document] = {}
    volumes: dict[str, Document] = {}
    if cell["multi_arm"]:
        followers = [a for a in cell["arms"] if a["role"] == "follower"]
        for arm in cell["arms"]:
            namespace = {"NAMESPACE": arm["namespace"]}
            if arm["service"] in ("leader", "follower"):
                services[arm["service"]] = {"environment": namespace}
            else:
                service: Document = {
                    **CELL_SERVICE, "image": images.get(arm["role"]) or ARM_IMAGE, "command": ["arm"],
                    "environment": {**ROS_ENV, "ROLE": arm["role"], **namespace, "BACKEND": arm["backend"]},
                    "volumes": list(ARM_SOURCES),
                }  # fmt: skip
                if arm["backend"] == "real":
                    path = resolved[arm["id"]]["path"]
                    service["environment"].update(
                        USB_PORT=path,
                        CALIBRATION_FILE=f"/calibration/{resolved[arm['id']]['calibration']}",
                    )
                    service["devices"] = [f"{path}:{path}"]
                    service["volumes"].append("calibration:/calibration:ro")
                    volumes["calibration"] = {"name": hw.CALIBRATION_VOLUME}
                services[arm["service"]] = service
        for arm in followers:
            command = [
                *BRIDGE_COMMAND,
                f"robot_config:=/workspace/config/mock-so101/robots/{arm['id']}.yaml",
            ]
            if arm["bridge"] == "bridge":
                services["bridge"] = {"command": command}
            else:
                services[arm["bridge"]] = {
                    **CELL_SERVICE, "image": RECORDER_IMAGE, "command": command, "environment": dict(ROS_ENV),
                    "volumes": [RECORDER_CONFIG, "cell_workspace:/workspace/config/mock-so101:ro"],
                }  # fmt: skip
        services["arm_adapter"] = {
            **CELL_SERVICE, "image": RECORDER_IMAGE,
            "entrypoint": ["/bin/bash", "-c", "source /opt/platform/install/setup.bash && cd /opt/mock && "
                           "exec python3 arm_adapter.py /workspace/config/mock-so101/arms.json"],
            "environment": {**ROS_ENV, "RMW_IMPLEMENTATION": "rmw_zenoh_cpp"},
            "volumes": ["./arm_adapter.py:/opt/mock/arm_adapter.py:ro", "./arm_merge.py:/opt/mock/arm_merge.py:ro",
                        "cell_workspace:/workspace/config/mock-so101:ro"],
            "healthcheck": {"disable": True},
        }  # fmt: skip
        if mock_motion:
            for index, leader in enumerate(a for a in cell["arms"] if a["role"] == "leader"):
                follower = next(f for f in followers if f["leader"] == leader["id"])
                motion = {
                    "MOCK_MOTION_STATE_TOPIC": follower["joint_states_topic"],
                    "MOCK_MOTION_COMMAND_TOPIC": f"/{leader['namespace']}/forward_position_controller/commands",
                    "MOCK_MOTION_NODE": f"mock_motion_{leader['id']}",
                }
                if index == 0:
                    services["leader_motion"] = {"environment": motion}
                else:
                    seed = int(settings["mock_motion"]["seed"]) + index
                    services[f"leader_motion_{leader['id']}"] = {
                        **CELL_SERVICE, "image": ARM_IMAGE, "profiles": ["motion"],
                        "entrypoint": MOTION_ENTRYPOINT,
                        "environment": {**ROS_ENV, "RMW_IMPLEMENTATION": "rmw_zenoh_cpp", **motion,
                                        "MOCK_MOTION_SEED": str(seed),
                                        "MOCK_MOTION_SPEED": repr(float(settings["mock_motion"]["speed"])),
                                        "MOCK_MOTION_MODE": settings["mock_motion"]["mode"]},
                        "volumes": ["./mock_motion.py:/opt/mock/mock_motion.py:ro",
                                    "./motion_planner.py:/opt/mock/motion_planner.py:ro"],
                    }  # fmt: skip
    for camera in cell["cameras"][:2]:
        if camera in sdk_cameras:
            # Replaces the base file's mock camera service: same name, the model's driver instead.
            services[camera["service"]] = {**sdk_camera_service(camera), "entrypoint": None}
    for camera in cell["cameras"][2:]:
        environment = {**ROS_ENV, "RMW_IMPLEMENTATION": "rmw_zenoh_cpp"}
        if camera in sdk_cameras:
            services[camera["service"]] = {
                **CELL_SERVICE, **sdk_camera_service(camera),
                "environment": {**environment, **sdk_camera_service(camera)["environment"]},
            }  # fmt: skip
        elif camera["source"] == "opencv_usb":
            path = resolved[camera["id"]]["path"]
            services[camera["service"]] = {
                **CELL_SERVICE, "image": images.get("camera") or USB_CAMERA_IMAGE, "environment": environment,
                "devices": [f"{path}:{path}"],
                "command": ["--ros-args", "-r", f"__node:=camera_{camera['id']}", "-p", f"video_device:={path}",
                            "-p", f"image_width:={camera['width']}", "-p", f"image_height:={camera['height']}",
                            "-p", f"fps:={camera['fps']}", "-r", f"image/compressed:={camera['topic']}"],
            }  # fmt: skip
        else:
            services[camera["service"]] = {
                **CELL_SERVICE, "image": images.get("camera") or RECORDER_IMAGE,
                "entrypoint": ["/bin/bash", "-c",
                               "source /opt/platform/install/setup.bash && exec python3 /opt/mock/mock_camera.py"],
                "environment": {**environment, "CAMERA_TOPIC": camera["topic"], "CAMERA_NODE": f"mock_{camera['id']}",
                                "CAMERA_LABEL": camera.get("name") or camera["id"],
                                **{f"CAMERA_{k.upper()}": str(v) for k, v in camera_settings(camera).items()}},
                "volumes": ["./mock_camera.py:/opt/mock/mock_camera.py:ro"],
                "healthcheck": {"disable": True},
            }  # fmt: skip
    document = {"services": services}
    if volumes:
        document["volumes"] = volumes
    return document


def sdk_ros_args(camera: Document, topic: str) -> list[str]:
    """The driver's ROS arguments: the cell's size, rate and serial number, publishing on ``topic``."""
    model = camera_models.models()[camera["source"]]
    fps = float(camera["fps"]) if model["fps_type"] == "float" else int(camera["fps"])
    command = ["--ros-args", "-r", f"__node:=camera_{camera['id']}",
               "-p", f"image_width:={camera['width']}", "-p", f"image_height:={camera['height']}",
               "-p", f"fps:={fps}", "-r", f"image/compressed:={topic}"]  # fmt: skip
    serial = (camera.get("device") or {}).get("serial")
    if serial:
        # Quoted, so ROS keeps an all-digit serial number a string.
        command += ["-p", f"serial_number:='{serial}'"]
    address = (camera.get("device") or {}).get("address")
    if address:  # network cameras (custom drivers): validated by cameras.check_device
        command += ["-p", f"address:='{address}'"]
    return command


def sdk_camera_service(camera: Document) -> Document:
    """Driver service of an SDK camera: the catalogue's image, USB bus access, no privileges.

    A network camera (custom driver) gets no host device at all, only the cell network.
    """
    model = camera_models.models()[camera["source"]]
    service: Document = {
        "image": model["image"],
        "command": sdk_ros_args(camera, camera["topic"]),
        "environment": {"RMW_IMPLEMENTATION": "rmw_zenoh_cpp"},
    }
    if model["access"] == "usb_bus":
        service["volumes"] = [f"{USB_BUS}:{USB_BUS}"]
        service["device_cgroup_rules"] = [USB_CGROUP_RULE]
    if camera["source"] == "ids_ueye":
        service["cap_add"] = ["NET_ADMIN", "SYS_NICE"]
    return service


def write_overlay(base: Preset, document: Document | None, state_dir: Path) -> Path | None:
    """Persist the generated overlay next to the agent's state; Compose reads it from here."""
    if document is None:
        return None
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / f"{base.project}.cell.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n")
    temporary.replace(path)
    return path


def profile_for(ident: str, root: Path | None) -> Document:
    wanted = PRESETS[ident].get("robot")
    profile = robot_profiles(root).get(wanted) if isinstance(wanted, str) else None
    if profile is None:
        raise ValueError(f"No robot profile '{wanted}' was found (driver/*/profile.json).")
    return profile


def render_params(ident: str, task: str, settings: Document, cell: Document, root: Path | None) -> Document:
    followers = [a for a in cell["arms"] if a["role"] == "follower"]
    recording = settings["recording"]
    params: Document = {
        "robot": "real" if any(a["backend"] == "real" for a in followers) else "sim",
        "robot_profile": profile_for(ident, root),
        "mock_handover": all(a["backend"] == "mock" for a in followers) and any(
            a["role"] == "leader" and a["backend"] == "real" for a in cell["arms"]
        ),
        "teleop": {**settings["teleop"], "joint_mapping": {} if cell["multi_arm"] else followers[0]["joint_mapping"]},
        "task_id": task,
        "instruction": recording["instruction"],
        "recording": {
            "minimum_duration_seconds": recording["minimum_duration_seconds"],
            "preflight_min_free_gib": recording["preflight_min_free_gib"],
            "maximum_camera_gap_ms": recording["maximum_camera_gap_ms"],
        },
        "cameras": [{"name": c["id"], "topic": c["topic"], **camera_settings(c)} for c in cell["cameras"]],
    }  # fmt: skip
    if cell["multi_arm"]:
        params["arms"] = [
            {"id": a["id"], "role": a["role"], "robot": "real" if a["backend"] == "real" else "sim",
             **({"leader": a["leader"], "joint_mapping": a["joint_mapping"]} if a["role"] == "follower" else {})}
            for a in cell["arms"]
        ]  # fmt: skip
    return params


def plan(
    ident: str,
    preset: Preset,
    env: dict[str, str] | None = None,
    allowed: dict[str, str] | None = None,
    extra: Document | None = None,
) -> Document:
    result = preset.run("plan", env=env)
    if result.returncode:
        raise ValueError(result.stderr[-2000:] or "Cannot resolve Compose plan.")
    return check_plan(json.loads(result.stdout), ident, allowed, extra)


def running(preset: Preset) -> bool:
    result = preset.run("status")
    return result.returncode == 0 and "running" in result.stdout
