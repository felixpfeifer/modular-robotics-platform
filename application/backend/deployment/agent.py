"""Local mock-cell deployment API. This is the only application service with Docker access."""

import argparse
import json
import os
import re
import subprocess
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import cell_plan
import device_checks
import devices as hw
from cell_config.compose_preset import ComposePreset as _ComposePreset
from mrp_app import cameras as camera_models
from mrp_app import components
from mrp_app.artifacts import canonical_uuid, read_json
from mrp_app.catalog import PRESETS
from mrp_app.deployment import (
    PRESET_SERVICES,
    check_policy_plan,
    check_training_plan,
)
from mrp_app.http import LocalHandler

TEST_VALIDITY_SECONDS = 600
CELL_KEYS = {
    "preset",
    "task_id",
    "devices",
    "camera",
    "mock_motion",
    "settings",
    "images",
    "operator_confirmed",
    "arms",
    "cameras",
}
SERVICE_FOR_ROLE = {"leader": "leader", "follower": "follower", "camera": "camera", "side_camera": "camera2"}
IMAGE_ENV = {
    "leader": "MRP_LEADER_IMAGE",
    "follower": "MRP_FOLLOWER_IMAGE",
    "camera": "MRP_CAMERA_IMAGE",
    "side_camera": "MRP_CAMERA2_IMAGE",
}


class ComposePreset(_ComposePreset):
    """Cell starts and stops also remove services a previous, larger cell added (no orphan arms)."""

    def run(self, action, doc=None, env=None):
        if action not in ("up", "down"):
            return super().run(action, doc, env)
        arguments = (
            ["up", "-d", "--no-build", "--pull", os.environ.get("MRP_IMAGE_PULL_POLICY", "never")]
            if action == "up"
            else ["down"]
        )
        with self.lock:
            return subprocess.run(
                self.command(*arguments, "--remove-orphans"),
                capture_output=True,
                text=True,
                timeout=3600 if action == "up" else 120,
                check=False,
                env=None if env is None else {**os.environ, **env},
            )


WORKSPACE_FILES = {  # (preset, task) -> workspace config inside the converter/recorder containers
    ("mock-so101", "pipeline_check"): "/workspace/config/mock-so101/workspace.yaml",
    # The mock-family presets read the configuration generated from the project settings.
    ("hwleader-so101", "pipeline_check"): "/workspace/config/mock-so101/workspace.yaml",
    ("real-so101", "free_teleop"): "/workspace/config/mock-so101/workspace.yaml",
    ("sim-so101", "red_cube_to_rectangle"): "/workspace/config/sim-so101/workspace.yaml",
    ("sim-so101", "scene_motion_check"): "/workspace/config/sim-so101/workspace_motion_check.yaml",
}
SIM_WORKSPACE_ENV = {
    "red_cube_to_rectangle": "workspace.yaml",
    "scene_motion_check": "workspace_motion_check.yaml",
}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
CHECKPOINT = re.compile(r"(" + UUID.pattern + r")/output/checkpoints/(last|[0-9]{1,10})/pretrained_model")
CHECKPOINT_FILES = (
    "config.json",
    "model.safetensors",
    "policy_preprocessor.json",
    "policy_postprocessor.json",
)


def load_checkpoint(runs_dir, model):
    """Return the checkpoint's config after verifying it is a complete ACT model inside the runs volume."""
    match = CHECKPOINT.fullmatch(model) if isinstance(model, str) else None
    if not match:
        raise ValueError("Invalid model path.")
    runs_dir = Path(runs_dir).resolve()
    folder = runs_dir / model
    if any(
        part.is_symlink() for part in [runs_dir / match[1], folder]
    ) or not folder.resolve().is_relative_to(runs_dir):
        raise ValueError("Model path must be a real folder inside the training runs volume.")
    missing = [name for name in CHECKPOINT_FILES if not (folder / name).is_file()]
    if missing:
        raise ValueError(f"Model is incomplete: missing {', '.join(missing)}.")
    config = json.loads((folder / "config.json").read_text())
    if config.get("type") != "act":
        raise ValueError("Only ACT policies are supported.")
    return config


STEP = re.compile(r"\bstep:(\d+(?:\.\d+)?)([KMBT]?)\b")
SCALE = {"": 1, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}
# lerobot draws a tqdm bar redrawn with carriage returns: `Training:  10%|█ | 100/1000 [02:56<24:36, 1.64s/step]`
BAR = re.compile(
    r"Training:\s*\d+%\|[^|]*\|\s*(\d+)/(\d+) \[([0-9:]+)<([0-9:?]+), *([0-9.]+)(s/step|step/s|s/it|it/s)[^\]]*\]"
)


def clock_seconds(text):
    if "?" in text:
        return None
    seconds = 0
    for part in text.split(":"):
        seconds = seconds * 60 + int(part)
    return seconds


def training_progress(run_dir):
    """Summarise a local run from job.json and the tail of train.log (tqdm bar plus lerobot's `step:… loss:…` lines)."""
    run_dir = Path(run_dir)
    job = read_json(run_dir / "job.json")
    steps = int((job.get("configuration") or {}).get("steps") or 0)
    started = job.get("started_unix")
    progress = {
        "run_id": run_dir.name,
        "status": job.get("status", "unknown"),
        "steps": steps,
        "step": 0,
        "percent": 0.0,
        "loss": None,
        "seconds_per_step": None,
        "eta_seconds": None,
        "elapsed_seconds": round(time.time() - started, 1) if started else None,
        "step_is_approximate": False,
        "log_tail": [],
    }
    try:
        with (run_dir / "train.log").open("rb") as log:
            log.seek(0, 2)
            log.seek(max(0, log.tell() - 65536))
            text = log.read().decode("utf-8", "replace")
    except OSError:
        return progress
    bars = list(BAR.finditer(text))
    plain = [line.strip() for line in BAR.sub("", text).replace("\r", "\n").splitlines()]
    plain = [line for line in plain if line and not line.startswith("Training:")]
    progress["log_tail"] = [line[-300:] for line in plain[-7:]] + ([bars[-1][0][-300:]] if bars else [])
    step = 0
    approximate = False
    if bars:
        last = bars[-1]
        step, steps = int(last[1]), int(last[2]) or steps
        rate = float(last[5])
        per_step = rate if last[6] in ("s/step", "s/it") else (1 / rate if rate else None)
        eta = clock_seconds(last[4])
        progress.update(steps=steps, seconds_per_step=per_step, eta_seconds=eta)
    losses = []
    for line in plain:
        found = STEP.search(line)
        if not found:
            continue
        match = re.search(r"\bloss:(-?[0-9.]+(?:e-?\d+)?)", line)
        if match:
            losses.append(float(match[1]))
        if not bars:  # Without the bar, fall back to the (rounded for large values) step in the log line.
            step = int(float(found[1]) * SCALE[found[2]])
            approximate = bool(found[2])
    if losses:
        progress["loss"] = losses[-1]
    progress.update(step=step, step_is_approximate=approximate)
    if steps:
        progress["percent"] = round(min(100.0, 100.0 * step / steps), 1)
    if progress["status"] != "running":
        progress["eta_seconds"] = 0 if progress["status"] == "complete" else None
    if progress["status"] == "complete":
        progress.update(step=steps, percent=100.0)
    return progress


def detect_gpu():
    """Whether the training image can use an NVIDIA GPU: the check that matters is PyTorch's own, run in that image."""
    image = os.environ.get("MRP_AI_LEROBOT_IMAGE", "mrp-ai-lerobot:dev")
    none = {"gpu": False, "name": "", "vram_gb": 0}
    probe = (
        "import torch; assert torch.cuda.is_available(), 'torch.cuda.is_available() is False'; "
        "p = torch.cuda.get_device_properties(0); print(p.name + ',' + str(p.total_memory))"
    )
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--gpus",
                "all",
                "--pull",
                "never",
                "--network",
                "none",
                "--entrypoint",
                "python3",
                image,
                "-c",
                probe,
            ],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {**none, "detail": f"GPU check failed: {type(exc).__name__}."}
    error = result.stderr.lower()
    if result.returncode:
        if "no such image" in error or "unable to find image" in error or "pull access denied" in error:
            detail = f"The training image {image} is not built yet (run ./start.sh)."
        elif "could not select device driver" in error or "nvidia" in error and "runtime" in error:
            detail = "Docker cannot reach an NVIDIA GPU. Install the NVIDIA driver and container toolkit."
        elif "cuda" in error:
            detail = "PyTorch in the training image cannot use the GPU (driver too old for CUDA 12.8?)."
        else:
            detail = "No usable NVIDIA GPU was found."
        return {**none, "detail": detail}
    name, _, memory = (
        result.stdout.strip().splitlines()[-1].partition(",") if result.stdout.strip() else ("", "", "")
    )
    try:
        return {"gpu": True, "name": name.strip(), "vram_gb": round(int(memory) / 1024**3, 1), "detail": ""}
    except ValueError:
        return {**none, "detail": "GPU check returned unexpected output."}


def make_server(
    presets,
    exports_dir,
    host="127.0.0.1",
    port=8090,
    training=None,
    policy=None,
    runs_dir="/data/runs",
    training_gpu=None,
    gpu_check=None,
    workspace_root=None,
    sys_root="/sys",
    runner=subprocess.run,
    state_dir=None,
    camera_models_file=None,
):
    """`presets` maps preset id -> ComposePreset. A bare ComposePreset means the original mock-only agent.

    ``camera_models_file`` is the application's custom camera store (read-only here); the agent
    merges it with the camera driver images it finds on the host.
    """
    if not isinstance(presets, dict):
        presets = {"mock-so101": presets}
    exports_dir = Path(exports_dir).resolve()
    exports_dir.mkdir(parents=True, exist_ok=True)

    gpu_check = gpu_check or detect_gpu
    gpu_cache = []  # [(monotonic time, report)]

    def gpu_report():
        if not gpu_cache or time.monotonic() - gpu_cache[0][0] > 60:
            gpu_cache[:] = [(time.monotonic(), gpu_check())]
        return gpu_cache[0][1]

    training_state_lock = threading.Lock()
    active_trainings = set()
    aborted = set()
    tests = {}  # fingerprint -> (monotonic time of the last passing connection test)
    root = Path(workspace_root) if workspace_root else None
    overlay_dir = root / "application/backend/deployment" if root else None
    state_dir = Path(state_dir or os.environ.get("MRP_AGENT_STATE_DIR", "/tmp/mrp-agent"))
    models_file = camera_models_file or os.environ.get("MRP_CAMERA_MODELS_FILE")
    models_file = Path(models_file) if models_file else None
    camera_cache = []  # [(monotonic time, catalogue)]
    camera_lock = threading.Lock()

    def camera_catalog(force=False):
        """Built-in, custom and discovered camera models, with whether each driver image is here.

        Also makes them the models the cell validation below accepts. Cached for 15 seconds.
        """
        with camera_lock:
            if force or not camera_cache or time.monotonic() - camera_cache[0][0] > 15:
                try:
                    discovered, problems = hw.discover_camera_images(runner)
                except (OSError, subprocess.TimeoutExpired) as error:
                    discovered, problems = {}, [f"Camera driver images could not be listed: {error}"]
                custom, more = camera_models.load_custom(models_file) if models_file else ({}, [])
                camera_models.set_extra(camera_models.merge(custom, discovered))
                installed = {}
                for model in camera_models.models().values():
                    try:
                        installed[model["image"]] = hw.image_present(model["image"], runner)
                    except (OSError, subprocess.TimeoutExpired):
                        installed[model["image"]] = False
                report = camera_models.describe(installed, problems + more)
                report["custom_store"] = models_file is not None
                camera_cache[:] = [(time.monotonic(), report)]
            return camera_cache[0][1]

    def choose(body):
        ident = body.pop("preset", "mock-so101") if isinstance(body, dict) else "mock-so101"
        if ident not in presets:
            raise ValueError("Unknown deployment preset.")
        return ident, presets[ident]

    def finish(handler, state_ok, report, error=None):
        handler.reply(
            200 if state_ok else 502,
            report if state_ok else {**report, "error": error or report.get("detail", "")},
        )

    class Handler(LocalHandler):
        def do_GET(self):
            if not self.valid_host():
                return self.reply(403, {"error": "Host is not allowed."})
            try:
                query = urlsplit(self.path)
                path, params = query.path, parse_qs(query.query)
                if path == "/api/v1/hardware":
                    return self.reply(200, gpu_report())
                match = re.fullmatch(r"/api/v1/trainings/(" + UUID.pattern + r")/progress", path)
                if match:
                    run_dir = Path(runs_dir) / match[1]
                    if run_dir.is_symlink() or not run_dir.is_dir():
                        return self.reply(404, {"error": "Training run not found."})
                    return self.reply(200, training_progress(run_dir))
                if path == "/api/v1/robots":
                    return self.reply(200, cell_plan.robot_profiles(root))
                if path == "/api/v1/cameras":
                    return self.reply(200, camera_catalog(force=params.get("refresh") == ["1"]))
                if path == "/api/v1/network":
                    return self.reply(
                        200,
                        {
                            "ros_domain_id": os.environ.get("MOCK_ROS_DOMAIN_ID", "42"),
                            "zenoh_port": os.environ.get("MOCK_ZENOH_PORT", "17447"),
                            "zenoh_bind": os.environ.get("MOCK_ZENOH_BIND") or "127.0.0.1",
                        },
                    )
                if path == "/api/v1/calibrations":
                    return self.reply(200, hw.read_calibrations(runner))
                if path == "/api/v1/devices/scan":
                    return self.reply(
                        200, {**hw.scan(sys_root), "calibrations": hw.list_calibrations(runner)}
                    )
                ident, preset = choose({"preset": params.get("preset", ["mock-so101"])[0]})
                if path == "/health":
                    return self.reply(200, {"status": "ok", "presets": sorted(presets)})
                if path == "/api/v1/deployment/plan":
                    return self.reply(200, cell_plan.plan(ident, preset))
                if path == "/api/v1/deployment/status":
                    result = preset.run("status")
                    return self.reply(
                        200 if result.returncode == 0 else 502,
                        {"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode},
                    )
                self.reply(404, {"error": "Not found."})
            except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
                self.reply(502, {"error": str(exc)})

        def do_POST(self):
            try:
                body = self.body()
                if self.path == "/api/v1/uploads":
                    return self.upload(body)
                if self.path == "/api/v1/model-uploads":
                    return self.upload_model(body)
                if self.path in ("/api/v1/deployment/up", "/api/v1/deployment/down"):
                    return self.cell(body, self.path.rsplit("/", 1)[1])
                if self.path.startswith("/api/v1/devices/"):
                    return self.device_operation(body, self.path.rsplit("/", 1)[1])
                if self.path == "/api/v1/exports":
                    return self.export(body)
                if self.path == "/api/v1/trainings":
                    return self.train(body)
                if self.path == "/api/v1/trainings/abort":
                    return self.abort_training(body)
                if self.path == "/api/v1/models/hub":
                    return self.hub_model(body)
                if self.path in ("/api/v1/policy/up", "/api/v1/policy/down"):
                    return self.policy_operation(body, self.path.rsplit("/", 1)[1])
                if self.path == "/api/v1/cameras/pull":
                    return self.pull_camera(body)
                self.reply(404, {"error": "Not found."})
            except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
                self.reply(400, {"error": str(exc)})

        def pull_camera(self, body):
            """Pull the driver image of a camera model in the catalogue; never an arbitrary image."""
            if set(body) - {"model"}:
                raise ValueError("Give the camera model id only.")
            model = camera_catalog(force=True)["models"].get(body.get("model"))
            if model is None or model["origin"] == "builtin":
                raise ValueError("Only custom and discovered camera images are pulled here.")
            result = hw.pull_image(model["image"], runner)
            return self.reply(200 if result["ok"] else 502, {**result, "catalog": camera_catalog(force=True)})

        def device_operation(self, body, name):
            """Read-only device checks. Every path is re-resolved against a fresh scan first."""
            if root is None:
                raise ValueError("The agent has no workspace root, so device tools are unavailable.")
            driver = root / "driver"
            if name == "probe":
                role = body.get("role")
                if role not in hw.ROLES:
                    raise ValueError("role must be leader or follower.")
                port = hw.resolve({"port": body.get("port"), "serial": body.get("serial")}, role, sys_root)
                return self.reply(200, {"port": port, **hw.probe_arm(port, driver, "scan", run=runner)})
            if name == "identify":
                ports = [hw.resolve({"port": p}, "leader", sys_root) for p in body.get("ports", [])]
                seconds = min(max(float(body.get("seconds", 5)), 2.0), 15.0)
                return self.reply(200, hw.identify_leader(ports, driver, seconds, runner))
            if name == "snapshot":
                device = hw.resolve(
                    {"device": body.get("device"), "serial": body.get("serial")}, "camera", sys_root
                )
                report = hw.probe_camera(
                    device, driver, body.get("width", 640), body.get("height", 480), 15, 1.5, True, run=runner
                )
                report["jpeg_base64"] = hw.snapshot_b64(report)
                return self.reply(200, {"device": device, **report})
            if name == "calibrate":
                role = body.get("role")
                if role not in hw.ROLES or body.get("step") not in ("zero", "range", "save"):
                    raise ValueError("Give role (leader|follower) and step (zero|range|save).")
                target = body.get("name") or f"{role}.yaml"  # one file per arm in multi-arm cells
                if not isinstance(target, str) or not components.CALIBRATION_FILE.fullmatch(target):
                    raise ValueError("name must be a plain .yaml file name.")
                port = hw.resolve({"port": body.get("port"), "serial": body.get("serial")}, role, sys_root)
                seconds = min(max(float(body.get("seconds", 10)), 1.0), 60.0)
                extra = [
                    "--role",
                    role,
                    "--dir",
                    "/calibration",
                    "--step",
                    body["step"],
                    "--seconds",
                    str(seconds),
                ]
                if target != f"{role}.yaml":
                    extra += ["--name", target]
                report = hw.probe_arm(
                    port, driver, "calibrate", extra,
                    mount_calibration=True, timeout=int(seconds) + 40, run=runner,
                )  # fmt: skip
                return self.reply(200 if report.get("ok", True) else 409, report)
            if name == "test":
                ident, _ = choose(dict(body))
                camera_catalog()
                _, cell = cell_plan.cell_of(ident, body)
                resolved = device_checks.selection(cell, sys_root)
                if not resolved:
                    return self.reply(200, {"passed": True, "checks": [], "fingerprint": ""})
                report = device_checks.connection_test(
                    ident, resolved, cell, root, overlay_dir, sys_root, runner
                )
                if report["passed"]:
                    tests[report["fingerprint"]] = time.monotonic()
                return self.reply(200, report)
            if name == "import-calibration":
                stored = hw.import_calibration(body.get("name"), body.get("content"), runner)
                return self.reply(200, {"name": stored})
            self.reply(404, {"error": "Not found."})

        def cell(self, body, action):
            if set(body) - CELL_KEYS:
                raise ValueError(
                    "Deployment operations accept a preset, task, devices, cameras, arms and flags only."
                )
            task = body.get("task_id")
            ident, base = choose(dict(body))
            if task is not None and task not in PRESETS[ident]["tasks"]:
                raise ValueError("Task is not available for this preset.")
            camera_catalog()
            settings, cell = cell_plan.cell_of(ident, body)
            mock_motion = body.get("mock_motion", False)
            real_arms = [arm for arm in cell["arms"] if arm["backend"] == "real"]
            resolved, env, allowed, preset, extra = None, {}, {}, base, None
            if action == "up":
                images = body.get("images") or {}
                resolved = device_checks.selection(cell, sys_root)
                document = cell_plan.extra_services(cell, resolved, images, settings, mock_motion)
                preset = cell_plan.variant(
                    base,
                    resolved,
                    cell_plan.write_overlay(base, document, state_dir),
                    overlay_dir,
                    ComposePreset,
                )
                allowed = {item["service"]: item["path"] for item in (resolved or {}).values()}
                extra = {
                    "services": set((document or {}).get("services", {})) - PRESET_SERVICES[ident],
                    "arms": {arm["service"]: (arm["role"], arm["backend"]) for arm in cell["arms"]},
                    # The only services that may reach the USB bus, each with its driver image.
                    "usb_bus": {
                        c["service"]: camera_models.models()[c["source"]]["image"]
                        for c in cell["cameras"]
                        if camera_models.is_real(c["source"])
                        and camera_models.models()[c["source"]]["access"] == "usb_bus"
                    },
                }
                env = cell_plan.device_env(resolved, cell, settings, mock_motion)
                env.update({IMAGE_ENV[role]: image for role, image in images.items()})
                files = None
                if real_arms:
                    if body.get("operator_confirmed") is not True:
                        raise ValueError("Starting real hardware needs the operator's confirmation.")
                    passed = tests.get(device_checks.fingerprint(ident, resolved, cell))
                    if passed is None or time.monotonic() - passed > TEST_VALIDITY_SECONDS:
                        raise ValueError(
                            "Run the connection test for these exact devices and settings first "
                            "(it expires after 10 minutes)."
                        )
                    names = hw.list_calibrations(runner)
                    files = [resolved[arm["id"]]["calibration"] for arm in real_arms]
                    if any(name not in names for name in files):
                        raise ValueError(
                            "A calibration file is missing: run the calibration wizard or import a file."
                        )
                if ident != "sim-so101":
                    # Recorder, bridge, exporter and the application read this generated configuration.
                    params = cell_plan.render_params(
                        ident, task or PRESETS[ident]["tasks"][0], settings, cell, root
                    )
                    real_follower = any(a["role"] == "follower" for a in real_arms)
                    hw.render_cell_config(root, params, files if real_follower else None, runner)
                else:
                    env["SIM_TASK_WORKSPACE"] = SIM_WORKSPACE_ENV.get(task, "workspace.yaml")
                for other_id, other in presets.items():
                    if other.project != base.project and cell_plan.running(other):
                        raise ValueError(f"Stop the '{other_id}' cell before starting '{ident}'.")
            rendered = cell_plan.plan(ident, preset, env or None, allowed, extra)
            if action == "up":
                for role, image in images.items():
                    if rendered["services"][SERVICE_FOR_ROLE[role]].get("image") != image:
                        raise ValueError(f"Custom image for {role} was not applied to the deployment plan.")
                for image in sorted(set(images.values())):
                    pulled = runner(
                        ["docker", "pull", image], capture_output=True, text=True, timeout=600, check=False
                    )
                    if pulled.returncode:
                        raise ValueError(f"Could not pull image {image}: {pulled.stderr[-1000:]}")
                if (
                    real_arms
                    and time.monotonic() - tests[device_checks.fingerprint(ident, resolved, cell)]
                    > TEST_VALIDITY_SECONDS
                ):
                    raise ValueError(
                        "The connection test expired while pulling images. Run it again before starting."
                    )
            result = preset.run(action, env=env or None)
            self.reply(
                200 if result.returncode == 0 else 502,
                {
                    "stdout": result.stdout[-4000:],
                    "error": result.stderr[-4000:],
                    "exit_code": result.returncode,
                },
            )

        def export(self, body):
            if set(body) - {"job_id", "repo_id", "preset", "task_id", "downsample_hz_ratio"} or {
                "job_id",
                "repo_id",
            } - set(body):
                raise ValueError("Invalid export request fields.")
            ratio = body.pop("downsample_hz_ratio", 1)
            if type(ratio) is not int or not 1 <= ratio <= 120:
                raise ValueError("downsample_hz_ratio must be an integer between 1 and 120.")
            task = body.pop("task_id", None)
            ident, preset = choose(body)
            task = task or PRESETS[ident]["tasks"][0]
            workspace = WORKSPACE_FILES.get((ident, task))
            if workspace is None:
                raise ValueError("No workspace configuration for this preset and task.")
            job, repo_id = body["job_id"], body["repo_id"]
            if (
                not canonical_uuid(job)
                or not isinstance(repo_id, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", repo_id)
            ):
                raise ValueError("Invalid export identifiers.")
            folder = exports_dir / job
            if (
                folder.is_symlink()
                or not folder.resolve().is_relative_to(exports_dir)
                or not (folder / "accepted.json").is_file()
            ):
                raise ValueError("Export selection is missing.")
            if (folder / "report.json").exists():
                report = read_json(folder / "report.json")
                return self.reply(200 if report["state"] == "complete" else 409, report)
            cell_plan.plan(ident, preset)
            # Shared with cell up/down: keep one operation active per preset.
            with preset.lock:
                if (folder / "dataset").exists():
                    raise ValueError("Export destination exists. Inspect it and create a new export job.")
                command = preset.command(
                    "run",
                    "--rm",
                    "--no-deps",
                    "-T",
                    "convert",
                    "--workspace-config",
                    workspace,
                    "--accepted-manifest",
                    f"/data/exports/{job}/accepted.json",
                    "--output-dir",
                    f"/data/exports/{job}/dataset",
                    "--repo-id",
                    repo_id,
                    "--downsample-hz-ratio",
                    str(ratio),
                )
                state, detail = "failed", ""
                with (folder / "converter.log").open("w") as log:
                    try:
                        result = subprocess.run(
                            command, stdout=log, stderr=subprocess.STDOUT, timeout=3500, check=False
                        )
                        state = "complete" if result.returncode == 0 else "failed"
                        detail = f"Converter exit code {result.returncode}; see converter.log."
                    except subprocess.TimeoutExpired:
                        state, detail = "interrupted", "Converter timed out. Inspect the export output."
                    except OSError as exc:
                        detail = str(exc)
                report = {"job_id": job, "state": state, "detail": detail, "format": "LeRobot v3"}
                temporary = folder / "report.json.tmp"
                temporary.write_text(json.dumps(report, indent=2) + "\n")
                temporary.replace(folder / "report.json")
                finish(self, state == "complete", report, detail)

        def train(self, body):
            if training is None:
                raise ValueError("Training is not configured on this agent.")
            if set(body) != {"export_id", "settings", "base_model", "label", "run_id", "device"}:
                raise ValueError("Invalid training request.")
            export_id, run_id, settings = body["export_id"], body["run_id"], body["settings"]
            if (
                not canonical_uuid(export_id)
                or not canonical_uuid(run_id)
                or body["device"] not in ("cpu", "cuda")
            ):
                raise ValueError("Invalid training identifiers or device.")
            trainer = training
            if body["device"] == "cuda":
                if training_gpu is None or not gpu_report()["gpu"]:
                    raise ValueError(
                        "No usable NVIDIA GPU is available; train on the CPU or fix the GPU setup."
                    )
                trainer = training_gpu
            if not isinstance(settings, dict) or set(settings) != {
                "steps",
                "batch_size",
                "chunk_size",
                "smoke",
            }:
                raise ValueError("Invalid training settings.")
            for key, high in (("steps", 200000), ("batch_size", 256), ("chunk_size", 200)):
                if type(settings[key]) is not int or not 1 <= settings[key] <= high:
                    raise ValueError(f"Invalid {key}.")
            label = body["label"]
            if not isinstance(label, str) or len(label) > 80 or any(ord(c) < 32 for c in label):
                raise ValueError("Invalid label.")
            dataset = exports_dir / export_id / "dataset"
            report = exports_dir / export_id / "report.json"
            if (
                dataset.is_symlink()
                or not (dataset / "meta/info.json").is_file()
                or read_json(report).get("state") != "complete"
            ):
                raise ValueError("Completed dataset export not found.")
            # `compose run` replaces the service's own `command: ["train"]`, so name the subcommand.
            arguments = [
                "train",
                "--dataset",
                f"/data/exports/{export_id}/dataset",
                "--repo-id",
                "local/mrp-task",
                "--runs-dir",
                "/data/runs",
                "--run-id",
                run_id,
                "--steps",
                str(settings["steps"]),
                "--batch-size",
                str(settings["batch_size"]),
                "--chunk-size",
                str(settings["chunk_size"]),
                "--device",
                body["device"],
                "--label",
                label,
            ]
            if settings["smoke"]:
                arguments.append("--smoke")
            if body["base_model"]:
                load_checkpoint(runs_dir, body["base_model"])
                arguments += ["--base-model", f"/data/runs/{body['base_model']}"]
            result = trainer.run("plan")
            if result.returncode:
                raise ValueError("Cannot resolve the training plan.")
            check_training_plan(json.loads(result.stdout), root)
            proc, execution_error = None, None
            with trainer.lock:
                with training_state_lock:
                    active_trainings.add(run_id)
                try:
                    proc = subprocess.run(
                        trainer.command(
                            "run", "--rm", "-T", "--name", f"mrp-train-{run_id}", "train", *arguments
                        ),
                        capture_output=True,
                        text=True,
                        timeout=86000,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    execution_error = exc
                finally:
                    with training_state_lock:
                        active_trainings.discard(run_id)
                        cancelled = run_id in aborted
                        aborted.discard(run_id)
            last = None
            if proc is not None:
                try:
                    output = json.loads(proc.stdout.strip().splitlines()[-1])
                    if isinstance(output, dict):
                        last = output
                except (IndexError, ValueError):
                    pass
                if (
                    proc.returncode == 0
                    and last
                    and last.get("status") == "complete"
                    and last.get("run_id") == run_id
                ):
                    return self.reply(200, last)
            if cancelled:
                try:
                    meta = read_json(Path(runs_dir) / run_id / "job.json")
                    if meta.get("status") == "running":
                        (Path(runs_dir) / run_id / "job.json").write_text(
                            json.dumps({**meta, "status": "aborted", "finished_unix": time.time()}, indent=2)
                            + "\n"
                        )
                except (OSError, ValueError):
                    pass  # The runs volume may be read-only here; the application records the abort.
                return self.reply(
                    409, {"run_id": run_id, "status": "aborted", "error": "Training was aborted."}
                )
            if execution_error is not None:
                return self.reply(
                    502,
                    {"status": "interrupted", "error": "Training outcome is unknown. Check the run folder."},
                )
            self.reply(
                502,
                {**(last or {}), "error": "Training failed; read train.log in the run folder."},
            )

        def abort_training(self, body):
            if training is None:
                raise ValueError("Training is not configured on this agent.")
            run_id = body.get("run_id")
            if set(body) != {"run_id"} or not canonical_uuid(run_id):
                raise ValueError("Provide the run_id of the training to abort.")
            with training_state_lock:
                if run_id in active_trainings and run_id not in aborted:
                    result = subprocess.run(
                        ["docker", "stop", "--time", "5", f"mrp-train-{run_id}"],
                        capture_output=True,
                        text=True,
                        timeout=60,
                        check=False,
                    )
                    if result.returncode == 0:
                        aborted.add(run_id)
                accepted = run_id in aborted
            if accepted:
                return self.reply(200, {"run_id": run_id, "state": "aborting"})
            self.reply(409, {"error": "No running training container found for this run."})

        def hub_model(self, body):
            if training is None:
                raise ValueError("Training is not configured on this agent.")
            required = {"run_id", "repo_id", "revision", "subfolder", "label", "token"}
            if set(body) != required:
                raise ValueError("Invalid model import request.")
            if (
                not canonical_uuid(body["run_id"])
                or not isinstance(body["repo_id"], str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", body["repo_id"])
            ):
                raise ValueError("Invalid model identifiers.")
            token = body["token"]
            if token is not None and (
                not isinstance(token, str)
                or not 1 <= len(token) <= 4096
                or any(c in token for c in "\r\n\x00 ")
            ):
                raise ValueError("Invalid token.")
            arguments = [
                "--repo-id",
                body["repo_id"],
                "--runs-dir",
                "/data/runs",
                "--run-id",
                body["run_id"],
                "--subfolder",
                body["subfolder"] or "",
                "--label",
                body["label"] or "",
            ]
            if body["revision"]:
                arguments += ["--revision", body["revision"]]
            planned = training.run("plan")
            if planned.returncode:
                raise ValueError("Cannot resolve the training plan.")
            check_training_plan(json.loads(planned.stdout), root)
            command = training.command(
                "--profile",
                "import",
                "run",
                "--rm",
                "-T",
                *(["-e", "HF_TOKEN"] if token else []),
                "hub_import",
                *arguments,
            )
            env = {**os.environ, **({"HF_TOKEN": token} if token else {})}
            with training.lock:
                try:
                    proc = subprocess.run(
                        command, env=env, capture_output=True, text=True, timeout=3500, check=False
                    )
                except subprocess.TimeoutExpired:
                    return self.reply(
                        502,
                        {"status": "interrupted", "error": "Model import timed out. Check the run folder."},
                    )
                except OSError:
                    return self.reply(502, {"error": "Model import could not start."})
                finally:
                    env.pop("HF_TOKEN", None)
                    token = None
            try:
                result = json.loads(proc.stdout.strip().splitlines()[-1])
            except (IndexError, ValueError):
                result = {}
            if proc.returncode:
                return self.reply(
                    502,
                    {
                        "error": "Model import failed. Check the repository, revision, subfolder, "
                        "token permissions, and that it is a complete ACT checkpoint."
                    },
                )
            if (
                not isinstance(result, dict)
                or result.get("status") != "complete"
                or result.get("run_id") != body["run_id"]
            ):
                return self.reply(
                    502, {"status": "interrupted", "error": "Model import result could not be verified."}
                )
            self.reply(200, result)

        def policy_operation(self, body, action):
            if policy is None:
                raise ValueError("Policy deployment is not configured on this agent.")
            if action == "down":
                if body:
                    raise ValueError("Stopping a policy accepts no arguments.")
                result = policy.run_profile("down")
                return self.reply(
                    200 if result.returncode == 0 else 502,
                    {"exit_code": result.returncode, "error": result.stderr[-2000:]},
                )
            if set(body) != {"preset", "model"}:
                raise ValueError("Starting a policy needs a preset and a model path.")
            ident, cell = choose(dict(body))
            config = load_checkpoint(runs_dir, body["model"])
            feature = PRESETS[ident]["image_feature"]
            if feature not in config.get("input_features", {}):
                have = [k for k in config.get("input_features", {}) if k.startswith("observation.images.")]
                raise ValueError(f"This model was trained on {have}, but the cell provides {feature}.")
            if not cell_plan.running(cell):
                raise ValueError("Start the cell before starting a policy.")
            planned = policy.run("plan")
            if planned.returncode:
                raise ValueError("Cannot resolve the policy plan.")
            check_policy_plan(json.loads(planned.stdout), root)
            result = policy.run_profile(
                "up",
                env={
                    "MRP_ACT_CHECKPOINT": f"/checkpoints/{body['model']}",
                    "ROS_DOMAIN_ID": str(PRESETS[ident]["domain"]),
                    "MRP_POLICY_ROUTER_PORT": "7450"
                    if PRESETS[ident]["simulation"]
                    else os.environ.get("MOCK_ZENOH_PORT", "17447"),
                    "MRP_POLICY_SIM_TIME": "true" if PRESETS[ident]["simulation"] else "false",
                    "MRP_POLICY_CAMERA_TOPIC": PRESETS[ident]["camera_topic"],
                    "MRP_POLICY_IMAGE_FEATURE": feature,
                },
            )
            self.reply(
                200 if result.returncode == 0 else 502,
                {"exit_code": result.returncode, "error": result.stderr[-2000:]},
            )

        def upload_model(self, body):
            if set(body) != {
                "job_id",
                "model_id",
                "repo_id",
                "visibility",
                "path",
                "token",
                "confirm_upload",
                "confirm_public",
            }:
                raise ValueError("Invalid model upload request.")
            ident, model_id, repo_id = body["job_id"], body["model_id"], body["repo_id"]
            visibility, token, path = body["visibility"], body["token"], body["path"]
            match = CHECKPOINT.fullmatch(path) if isinstance(path, str) else None
            if (
                not canonical_uuid(ident)
                or not canonical_uuid(model_id)
                or not match
                or not isinstance(repo_id, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repo_id)
                or visibility not in ("private", "public")
                or body["confirm_upload"] is not True
                or (visibility == "public" and body["confirm_public"] is not True)
                or not isinstance(token, str)
                or not 1 <= len(token) <= 4096
                or any(c in token for c in "\r\n\x00")
            ):
                raise ValueError("Invalid upload identifiers, confirmation or credential.")
            load_checkpoint(runs_dir, path)
            root = Path(runs_dir).resolve()
            checkpoint = root / path
            if any(
                (root.joinpath(*Path(path).parts[:index])).is_symlink()
                for index in range(1, len(Path(path).parts) + 1)
            ) or any(p.is_symlink() for p in checkpoint.rglob("*")):
                raise ValueError("Model checkpoint may not contain symbolic links.")
            script = (
                "import json,os,sys; from huggingface_hub import HfApi; "
                "api=HfApi(token=os.environ['HF_TOKEN']); path,repo,visibility=sys.argv[1:]; "
                "api.create_repo(repo_id=repo,repo_type='model',private=visibility=='private',exist_ok=True); "
                "info=api.repo_info(repo_id=repo,repo_type='model'); "
                "assert info.private == (visibility=='private'), 'Repository visibility differs'; "
                "result=api.upload_folder(repo_id=repo,repo_type='model',folder_path=path); "
                "print(json.dumps({'revision': result.oid}))"
            )
            env = os.environ.copy()
            env["HF_TOKEN"] = token
            try:
                result = subprocess.run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--network",
                        "bridge",
                        "-v",
                        "mrp-training_runs:/data/runs:ro",
                        "-e",
                        "HF_TOKEN",
                        "--entrypoint",
                        "python",
                        "mrp-training-lerobot:dev",
                        "-c",
                        script,
                        "/data/runs/" + path,
                        repo_id,
                        visibility,
                    ],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=3500,
                    check=False,
                )
                if result.returncode:
                    return self.reply(
                        502,
                        {"error": "Model upload failed. Check Hub permissions, connection and visibility."},
                    )
                revision = json.loads(result.stdout.strip().splitlines()[-1])["revision"]
                if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", revision):
                    raise ValueError("Invalid revision")
                return self.reply(200, {"job_id": ident, "state": "complete", "revision": revision})
            except OSError:
                return self.reply(502, {"error": "Model upload could not start."})
            except (subprocess.TimeoutExpired, ValueError, KeyError, IndexError, TypeError):
                return self.reply(
                    502, {"state": "interrupted", "error": "Model upload result could not be verified."}
                )
            finally:
                env.pop("HF_TOKEN", None)
                token = None

        def upload(self, body):
            required = {
                "job_id",
                "export_id",
                "repo_id",
                "visibility",
                "token",
                "confirm_upload",
                "confirm_public",
            }
            if set(body) != required:
                raise ValueError("Invalid upload request.")
            ident, export_id, repo_id = body["job_id"], body["export_id"], body["repo_id"]
            visibility, token = body["visibility"], body["token"]
            if (
                not canonical_uuid(ident)
                or not canonical_uuid(export_id)
                or not isinstance(repo_id, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repo_id)
                or visibility not in ("private", "public")
                or body["confirm_upload"] is not True
                or (visibility == "public" and body["confirm_public"] is not True)
                or not isinstance(token, str)
                or not 1 <= len(token) <= 4096
                or any(c in token for c in "\r\n\x00")
            ):
                raise ValueError("Invalid upload identifiers, confirmation or credential.")
            folder = exports_dir / export_id
            dataset = folder / "dataset"
            report_path = folder / "report.json"
            if (
                folder.is_symlink()
                or dataset.is_symlink()
                or not folder.resolve().is_relative_to(exports_dir)
                or not dataset.is_dir()
                or not report_path.is_file()
            ):
                raise ValueError("Completed export not found.")
            export_report = read_json(report_path)
            if export_report.get("state") != "complete" or export_report.get("job_id") != export_id:
                raise ValueError("Export has not completed successfully.")
            ident_preset, preset = choose({})
            cell_plan.plan(ident_preset, preset)
            with preset.lock:
                command = preset.command(
                    "run",
                    "--rm",
                    "--no-deps",
                    "-T",
                    "-e",
                    "HF_TOKEN",
                    "upload",
                    "--dataset-dir",
                    f"/data/exports/{export_id}/dataset",
                    "--repo-id",
                    repo_id,
                    "--visibility",
                    visibility,
                    "--confirm-upload",
                )
                if visibility == "public":
                    command.append("--confirm-public")
                env = os.environ.copy()
                env["HF_TOKEN"] = token
                try:
                    proc = subprocess.run(
                        command, env=env, capture_output=True, text=True, timeout=3500, check=False
                    )
                except subprocess.TimeoutExpired:
                    return self.reply(
                        502,
                        {"state": "interrupted", "error": "Upload timed out. Inspect the Hub repository."},
                    )
                except OSError:
                    return self.reply(502, {"error": "Upload could not start."})
                finally:
                    env.pop("HF_TOKEN", None)
                    token = None
                if proc.returncode:
                    return self.reply(
                        502, {"error": "Upload failed. Check Hub permissions, connection and visibility."}
                    )
                try:
                    result = json.loads(proc.stdout.strip().splitlines()[-1])
                    revision = result["commit_revision"]
                    if (
                        result.get("repo_id") != repo_id
                        or result.get("visibility") != visibility
                        or not re.fullmatch(r"[0-9a-fA-F]{40,64}", revision)
                    ):
                        raise ValueError
                except (IndexError, KeyError, TypeError, ValueError):
                    return self.reply(
                        502,
                        {
                            "state": "interrupted",
                            "error": "Upload result could not be verified; inspect the Hub before retrying.",
                        },
                    )
                return self.reply(200, {"job_id": ident, "state": "complete", "revision": revision})

    server = ThreadingHTTPServer((host, port), Handler)
    server.allowed_hosts = {"127.0.0.1", "localhost", "::1", "agent"}
    return server


class ProfilePreset(ComposePreset):
    """Compose project whose services all live under the 'policy' profile."""

    def run_profile(self, action, env=None):
        operations = {
            "up": ["--profile", "policy", "up", "-d", "--no-build", "--pull", "never"],
            "down": ["--profile", "policy", "down"],
        }
        with self.lock:
            # Compose needs the checkpoint variable to render even for "down"; the value is irrelevant there.
            merged = {**os.environ, "MRP_ACT_CHECKPOINT": "/checkpoints/unused", **(env or {})}
            return subprocess.run(
                self.command(*operations[action]),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
                env=merged,
            )

    def run(self, action, doc=None, env=None):
        if action == "plan":
            with self.lock:
                # The policy file requires a checkpoint variable even to render; any value works for a plan.
                env = {**os.environ, "MRP_ACT_CHECKPOINT": "/checkpoints/plan-only"}
                return subprocess.run(
                    self.command("--profile", "*", "config", "--format", "json"),
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                    env=env,
                )
        return super().run(action, doc, env)


def main():
    parser = argparse.ArgumentParser(description="MRP deployment agent for vetted presets")
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--exports-dir", default="/data/exports", type=Path)
    parser.add_argument("--runs-dir", default="/data/runs", type=Path)
    parser.add_argument("--port", default=8090, type=int)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    root = args.workspace_root
    # The cell joins the application's Docker network (see cell.compose.yaml), so the application
    # reaches its Zenoh router by service name. The ROS domain must match the application's.
    os.environ.setdefault("MOCK_ROS_DOMAIN_ID", "42")
    overlay = root / "application/backend/deployment"
    presets = {
        "mock-so101": ComposePreset(
            [overlay / "mock-cell/compose.yaml", overlay / "cell.compose.yaml"], "mrp-mock-so101"
        ),
    }
    # The Gazebo tabletop preset ships separately; offer it only when its base file is installed.
    sim_base = root / "config/sim-so101/compose.yaml"
    if sim_base.is_file():
        presets["sim-so101"] = ComposePreset([sim_base, overlay / "sim.compose.yaml"], "mrp-so101-tabletop")
    # Real-hardware presets share the mock cell's Compose project, files and topic layout; the
    # agent adds device overlays at start time. One project means one running cell at a time.
    for ident in ("hwleader-so101", "real-so101"):
        presets[ident] = ComposePreset(
            [overlay / "mock-cell/compose.yaml", overlay / "cell.compose.yaml"], "mrp-mock-so101"
        )
        presets[ident].lock = presets["mock-so101"].lock
    training_file = root / "core/ai_lerobot/training.compose.yaml"
    training = ProfilePreset([training_file], "mrp-training") if training_file.is_file() else None
    # Same project, plus the NVIDIA reservation; only used when a GPU run was requested and detected.
    gpu_file = root / "core/ai_lerobot/training.gpu.compose.yaml"
    training_gpu = (
        ProfilePreset([training_file, gpu_file], "mrp-training") if training and gpu_file.is_file() else None
    )
    if training_gpu:
        training_gpu.lock = training.lock
    policy_file = root / "core/ai_lerobot/policy.compose.yaml"
    policy = ProfilePreset([policy_file], "mrp-policy") if policy_file.is_file() else None
    server = make_server(
        presets,
        args.exports_dir,
        host=args.host,
        port=args.port,
        training=training,
        training_gpu=training_gpu,
        policy=policy,
        runs_dir=args.runs_dir,
        workspace_root=root,
    )
    print(f"Deployment agent: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
