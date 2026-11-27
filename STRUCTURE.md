# Repository Structure

Snapshot of the Modular Robotics Platform (MRP) workspace, taken on 2026-11-27. This file describes the layout only. For the project vision and architecture, see [README](README).

## Workspace layout

This is a monorepo: every component under `core/`, `driver/` and `application/` lives in this single repository. `driver/robot_so101/src/ros2_so_arm` is a git submodule (clone with `--recurse-submodules`); `driver/robot_so101/src/feetech_ros2_driver` is vendored (BSD-3-Clause) with local patches. The IDS SDK installers are not included; see `driver/camera_ids/sdk/README.md`.

```
mrp/
├── README                 Project vision, architecture and roadmap
├── LOCAL_CI.md            How to run local CI (./ci.local) across components
├── STRUCTURE.md           This file
├── start.sh               Start/stop the application stack (docker compose)
├── ci.local               Run local CI for all components in order
├── config/
│   └── mock-so101/        Mock SO-101 cell configuration (empty in this snapshot)
├── core/                  Hardware-independent contracts and workflows
│   ├── ai_lerobot/        LeRobot training and policy serving (ACT, SmolVLA, GR00T)
│   ├── camera_manager/    Hardware-independent multi-camera manager (ROS 2 C++)
│   ├── cell_config/       Robot-cell configuration backend (ROS 2 / Python)
│   ├── control_arbiter/   Command router for the SO-101 follower (ROS 2 / Python)
│   ├── recorder/          Production VLA episode recorder (MCAP, validation, export)
│   └── ros-interfaces/    Versioned, vendor-neutral ROS 2 message/service/action packages
├── driver/                Concrete hardware adapters (ROS 2 Jazzy)
│   ├── camera_genicam/    GenICam industrial cameras (GigE Vision, USB3 Vision)
│   ├── camera_ids/        IDS uEye cameras (USB 2/3, GigE)
│   ├── camera_opencv/     V4L2 cameras via OpenCV
│   ├── camera_realsense/  Intel RealSense via librealsense2
│   ├── mrp_camera_common/ Header-only base shared by the camera drivers (watchdog, diagnostics, JPEG)
│   └── robot_so101/       SO-ARM101 bring-up (ros2_control, Feetech driver)
├── application/           User-facing workflows
│   ├── backend/           MRP HTTP API, CLI and deployment agent (Python)
│   └── frontend/          Browser dashboard (Vite + TypeScript + React)
└── build/                 Generated CMake/Ninja build tree (not source)
```

Directories such as `.git`, `.venv`, `node_modules`, `install/`, `log/`, `build/` inside components, `.pytest_cache`, and `.ruff_cache` are generated or local state and are omitted from the descriptions above.

## Components

| Path | Language / stack | Role | Git HEAD | Uncommitted files |
| --- | --- | --- | --- | --- |
| `core/ai_lerobot` | Python (uv) | Train and serve LeRobot policies | `e24303b` test(compose): validate volume mounts | 0 |
| `core/camera_manager` | C++ / ROS 2 | Multi-camera manager core | `7beead2` ci: update trivy command | 0 |
| `core/cell_config` | Python / ROS 2 | Store one robot cell's configuration | `05394d2` fix(docker): ensure git is not present | 0 |
| `core/control_arbiter` | Python / ROS 2 | Select one `JointIntent` for the follower | `522362f` style(teleop): format code | 0 |
| `core/recorder` | Python (uv) / ROS 2 | Record, validate, export episodes | `40f16a1` fix(docker): ensure git is not present | 1 |
| `core/ros-interfaces` | ROS 2 IDL | Shared `platform_*_interfaces` packages | `fcfba0d` fix(docker): ensure git is not present | 0 |
| `driver/camera_genicam` | C++ / ROS 2 | GenICam camera driver | `e671c13` feat(docker): add camera driver labels | 0 |
| `driver/camera_ids` | C++ / ROS 2 | IDS uEye camera driver | `2abbeeb` fix(docker): update IDS_SDK_EXCLUDE | 0 |
| `driver/camera_opencv` | C++ / ROS 2 | OpenCV/V4L2 camera driver | `5f2d9ff` fix(docker): ensure git is not present | 0 |
| `driver/camera_realsense` | C++ / ROS 2 | RealSense camera driver | `f620475` fix(docker): ensure git is not present | 0 |
| `driver/robot_so101` | Python / ROS 2 | SO-101 arm bring-up | `0d9ccc5` style(probe): format error message | 0 |
| `application/backend` | Python (uv) | HTTP API, CLI, deployment agent | `811032f` feat(deployment): add support for custom camera models | 9 |
| `application/frontend` | TypeScript / Vite | Browser dashboard | `0b8d723` feat(camera): add custom camera functionality | 11 |

## Component details

### core/

- **ai_lerobot**: `ai_lerobot/` (CLI entry), `policy_lerobot/` (policy serving, `server.py`, `contract.py`), `training_lerobot/` (`job.py`, `hub_import.py`). Compose files for CPU and GPU training and for policy serving.
- **camera_manager**: C++ sources in `src/` (`camera_manager_node`, `camera_worker`, `frame_synchronizer`), headers in `include/`, `launch/`, `test/`, `config/`, and `docs/`. Includes Trivy scan reports and build scripts for CI and sanitizers.
- **cell_config**: `cell_config/` package with `model.py`, `server.py`, `openapi.py`, `deploy.py`, `compose_preset.py`, `node.py`. Ships `examples/`, `resource/`, and `test/`.
- **control_arbiter**: `control_arbiter/` with `arbiter.py`, `arbitration.py`, `intent.py`, `policy_source.py`, `policy_validation.py`, `teleop_source.py`. Launch files, config, and a compose file.
- **recorder**: `episode_recorder_py/` (`validator_node.py`, `validation.py`, `export_lerobot.py`, `upload_lerobot.py`, `build_accepted_manifest.py`, `hil_qualification.py`, `joint_intent_bridge.py`, `cleanup.py`, `migrate_legacy.py`), `src/` and `include/` (C++), `launch/`, `scripts/`, `config/`, `test/`. Has a `Makefile`, `pyproject.toml`, and a `Dockerfile.convert`.
- **ros-interfaces**: `platform_common_interfaces`, `platform_control_interfaces`, `platform_device_interfaces`, `platform_episode_interfaces`. Each contains `msg/`, `srv/` and/or `action/` plus `CMakeLists.txt`. Also `docs/`, `examples/`, `tests/`, `tools/`, `scripts/`, `containers/`, `artifacts/`, and the governing files `REPO_CONTRACT.md`, `PLAN.md`, `CHANGELOG.md`, `VERSION`, `CODEOWNERS`.

### driver/

- **camera_genicam**: `src/genicam_node.cpp`, `include/`, `test/`, `docker-compose.yaml`.
- **camera_ids**: `src/`, `include/`, `sdk/` (vendor SDK), `tools/`, `test/`, and sample frames (`*.jpg`) used by its docs.
- **camera_opencv**: `src/`, `include/`, `tools/`, `test/`, `docker-compose.yaml`.
- **camera_realsense**: `src/`, `include/`, `test/`, `docker-compose.yaml`.
- **mrp_camera_common**: `include/mrp_camera_common/` (`camera_node.hpp`, `image.hpp`, `frame_stats.hpp`, `heartbeat.hpp`, `parameters.hpp`), `test/`, and `ci/driver-check.sh`, the check script every camera driver's CI runs. The camera images are built with `driver/` as context so they can include it.
- **robot_so101**: `src/` contains `feetech_ros2_driver`, `ros2_so_arm` (submodule-style checkout), and `so101_bringup`. Also `so101/`, `config/`, `docker/`, `tools/`, `profile.json`, `docker-compose.yaml`, and `Dockerfile.gazebo` / `Dockerfile.tabletop` variants.

### application/backend/

- `backend/mrp_app/`: application package. Key modules: `server.py` and `http.py` (HTTP API), `service.py` and `runtime.py` (orchestration), `cameras.py`, `arms.py`, `calibration.py`, `deployment.py`, `dataset_validation.py`, `configbundle.py`, `artifacts.py`, `hub.py` (Hugging Face sync), `mcap.py`, `ros_runtime.py`, `webrtc.py`, `storage.py`, `settings.py`, `cli.py` (CLI entry, `__main__.py`), `api_models.py`, `models.py`.
- `deployment/`: `agent.py` (deployment agent), `devices.py`, `sdk_camera_probe.py`, cell templates (`cell-templates/`, `mock-cell/`), and per-mode compose files (`cell.compose.yaml`, `sim.compose.yaml`, `real_leader.compose.yaml`, `real_follower.compose.yaml`, `usb_camera.compose.yaml`, `usb_side_camera.compose.yaml`).
- `tests/`: unit tests (`test_*.py`), `test_api_contract.py`, `test_application.py`, `run.py`, and an `integration/` directory.
- `docs/`: `architecture.md`, `verification.md`.
- Root: `Dockerfile`, `Dockerfile.agent`, `Dockerfile.demo`, `compose.dev.yaml`, `compose.demo.yaml`, `compose.secrets.yaml`, `pyproject.toml`, `uv.lock`, `requirements*.txt`, `ruff.toml`, `Makefile`, `mrp.repos`, `artifacts/`.

### application/frontend/

- `src/App.tsx`, `main.tsx`, `api.ts`, `types.ts`, `theme.ts`.
- `src/pages/`: `ProjectsPage`, `OverviewPage`, `CellSetupPage`, `CellPage`, `RecordPage`, `EpisodesPage`, `DatasetPage`, `TrainPage`, `DeployPage`, `SettingsPage`.
- `src/components/`: `AppShell`, `WorkspaceCanvas`, `PipelineStepper`, `HubBrowser`, `TargetPicker`, `LaunchDialog`, `CustomCameraDialog`, `RobotTelemetry`, `TrainingProgress`, `ValidationVerdict`, and others.
- `src/lib/`: `cellSpec.ts`, `cellComponents.ts`, `layout.ts`, `validation.ts`, `format.ts`.
- `tests/`: `unit/` (Vitest), `e2e/` (Playwright), `demo_server.py`, `setup.ts`.
- Root: `vite.config.ts`, `vitest.config.ts`, `playwright.config.ts`, `nginx.conf`, `Dockerfile`, `package.json`, `yarn.lock`, `.yarn/` and `.pnp.*` (Yarn PnP).

## Tooling and CI files

Every component carries the same set of local-CI files: `ci.local`, `.gitlab-ci.yml`, `.gitlab/`, `.dockerignore`, and a `Dockerfile` (or several). Repository-level docs and CI behavior are described in [LOCAL_CI.md](LOCAL_CI.md).

## Notes

- Several components contain generated or local-only content in this snapshot (`build/`, `install/`, `log/`, `.venv/`, `node_modules/`, `test-results/`, `dist/`). These are not source and are not listed above.
- `application/backend` and `application/frontend` have uncommitted changes at snapshot time (9 and 11 files). `core/recorder` has 1.
- `core/recorder/.test-artifacts` was not readable during the snapshot (permission denied), so its contents are not described.
