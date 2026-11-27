# Modular Robotics Platform (MRP)

**An extensible, offline-first Physical AI platform built around ROS 2 Jazzy.**

> **Status:** Active development and architectural roadmap — Master's project at Hochschule Heilbronn. This document describes both the initial pipeline and the intended platform. Items described as *planned* must not be treated as implemented.

## Vision

MRP should let a user assemble a robot cell from interchangeable hardware and software components, collect demonstrations, prepare datasets, train or fine-tune a policy on a chosen compute platform, evaluate it, and deploy it to a robot. A future project-based web application should guide users through this workflow without locking them into a robot, camera, AI framework, cloud provider, or hardware vendor.

The default mode is **local and offline**. Networked services, cloud jobs, and Hugging Face synchronization are optional, explicit choices.

## End-to-end workflow

1. **Create a project** and define tasks (for example, pick and place).
2. **Configure a robot cell:** robot, leader/teleoperation device, cameras, compute, calibration, ROS configuration, and safety constraints.
3. **Record demonstrations:** operator-controlled episodes via ROS 2; capture synchronized observations/actions and metadata in MCAP.
4. **Validate and convert:** check timestamps, missing streams, schema, episode boundaries, action/observation alignment, and produce a versioned LeRobot v2/v3 dataset.
5. **Train or fine-tune:** select a supported model/policy adapter and a compatible compute backend, either local or remote.
6. **Evaluate:** inspect metrics, replay episodes in Gazebo where meaningful, and test policies in simulation before hardware deployment.
7. **Deploy:** export a compatible model, validate the target/runtime, and run inference on edge compute with explicit safety gating.
8. **Track artifacts and runs:** retain provenance, configuration, model/dataset versions, logs, metrics, and reproducibility information.

The workflow must support pause/resume and re-running individual stages. Recording, training, and deployment are separate jobs, potentially on different machines.

## Layered architecture (bottom to top)

| Layer | Responsibility | Examples |
| --- | --- | --- |
| **1. Hardware and compute** | Physical devices and execution resources | UR CB-Series, SO-101, Quest 3, RealSense, USB/OpenCV cameras, Jetson AGX Orin, workstation, DGX Station |
| **2. Drivers and adapters** | Implement stable interfaces for concrete hardware and external systems | ROS robot/camera drivers, teleop input adapters, local/Azure/Jupyter training backends, model-framework adapters, artifact stores |
| **3. Core** | Hardware- and provider-independent contracts, workflows, and state | ROS interfaces, robot-cell registry, orchestration, recording, dataset validation/conversion, artifact metadata, job tracking, configuration, safety coordination |
| **4. Applications** | User-facing workflows and use cases | CLI, existing episode-control UI, planned web GUI, project/task wizard, monitoring, visualization, deployment workflows |

**Dependency rule:** upper layers consume documented lower-layer interfaces; the core must not hard-code a robot brand, camera model, model framework, or cloud provider. Keep ROS-specific runtime code at appropriate boundaries; cloud training APIs and web backend services need not be ROS nodes. Prefer capability-based interfaces and explicit versioned contracts over assumptions about a particular image or repository.

## Extensibility and plugin contracts

The platform should discover and validate registered components before starting them. Proposed plugin categories:

- **Robot:** capabilities (joints, action/control mode, gripper), ROS topics/actions, limits, description, calibration, compatibility, safety prerequisites.
- **Sensor:** camera modality, frame identifiers, timestamps, calibration, observation schema, ROS topics, device access.
- **Teleoperation:** input device, leader/follower mapping, rate, safety/deadman requirements.
- **Model/policy:** dataset and observation/action requirements, preprocessing, training, inference, export, evaluation, runtime compatibility.
- **Training backend:** local Docker, Jetson where feasible, Azure ML, DGX/Jupyter, Google Colab/notebook workflows.
- **Deployment backend:** local/edge runner, supported CPU/GPU architecture, model runtime and hardware constraints.
- **Artifact store:** local filesystem by default, optional Hugging Face datasets/model Hub synchronization.

Each plugin should declare an identifier, version, configuration schema, capabilities, supported architectures/ROS distribution when relevant, image reference or launch mechanism, dependencies, and health/readiness checks. Define interfaces first; do not implement a generic plugin system without a concrete end-to-end use case.

**Robot-cell composition:** a configuration selects a robot driver, one or more sensors, a teleoperation source, compute placement, and required core services. MRP resolves compatible plugin versions, pulls public Docker Hub images where configured, generates/combines Docker Compose services for the cell, and validates device permissions, networking, and ROS/DDS discovery. Compose is a deployment mechanism, not the public plugin API. Pin images by immutable digest for reproducible releases.

## Supported and targeted systems

| Area | Systems | Notes |
| --- | --- | --- |
| Robots | Universal Robots CB-Series; SO-101 leader/follower | Initial hardware targets; keep drivers swappable |
| Teleoperation | SO-101 leader, Meta Quest 3 | Virtual leader and input mappings may evolve |
| Cameras | Intel RealSense, OpenCV-compatible cameras | Standardize timestamps, frames and observations |
| Edge | NVIDIA Jetson AGX Orin | Recording and inference; training only when resources permit |
| Training | Local machine, Azure ML, DGX Station via Jupyter, Google Colab | Planned interchangeable backends, subject to authentication and runtime support |
| Model frameworks | Hugging Face LeRobot (including ACT), NVIDIA GR00T N1.x, other compatible VLA policies | Integrations are incremental, not automatically supported |
| Research extensions | NVIDIA Cosmos/world models and additional VLA/world-model frameworks | Exploratory: may require different modalities, objectives and pipelines |

**Important distinction:** acceptance of LeRobot-formatted data does **not** imply that a framework works with LeRobot's training code or inference API. GR00T, Cosmos, and other models can require dedicated adapters, preprocessing, training jobs, model packaging, and evaluation. A world model is not necessarily a drop-in robot-action policy.

## Dataset and model contracts

- **Recording source of truth:** ROS 2 topics captured in MCAP with episode boundaries and acquisition metadata.
- **Conversion target:** explicit LeRobot dataset format version (v2 or v3), not an unspecified latest format.
- **Validation:** schema, camera/depth modalities, clock synchronization, dropped samples, action/observation alignment, joint units, calibration, episode integrity, and dataset splits.
- **Provenance:** associate each dataset with project, task, cell configuration, robot/sensor versions, calibration, conversion version, and source MCAP files.
- **Model artifacts:** record policy/framework version, input/output schema, training configuration, dataset revision, checkpoints, metrics, license, and deployment compatibility.
- **Reproducibility:** lock container versions, dependencies, configurations, seeds where applicable, and job metadata. Do not commit large datasets or model weights to Git.

## Offline-first storage and optional Hugging Face

By default, recordings, datasets, checkpoints, and models remain local. A user may opt into Hugging Face download or upload for specific datasets or fine-tuned models. Hub operations must be explicit and independently configurable; do not assume automatic publication or use public repositories for private data. Support private repos when authorized.

Credentials (Hugging Face tokens, Azure credentials, Docker Hub secrets) must use environment-based secret injection or a suitable secret manager. Never put tokens in project YAML, Git, logs, images, or exported experiment metadata. Cloud training requires a visible data-transfer decision and a way to track the remote job and retrieved artifacts.

## Project and task model (planned web application)

- **Project:** groups users' robot-cell configurations, tasks, datasets, models, and deployment targets.
- **Robot cell:** reusable versioned composition of drivers, sensors, teleop, calibration, compute and safety settings.
- **Task:** defines the desired behavior, observations, actions, success criteria, and relevant datasets/policies.
- **Workflow run:** immutable snapshot of a configuration and the state of recording, validation, conversion, training, evaluation, and deployment steps.
- **Artifact:** a versioned dataset, recording, checkpoint, export, report, or log related to a run.

The planned GUI should provide a guided setup wizard, capability/compatibility checks, episode controls, job progress and logs, artifact browsing, evaluation results, and deployment controls. Keep the CLI and API usable without the GUI.

## Repository organization

The existing GitLab group is **[Modular Robotics Platform](https://gitlab.com/global-dynamics/robot-foundation-models/modular-robotics-platform)**. It already uses a layered hierarchy. Preserve those groups and repositories rather than renaming or flattening them to fit a hypothetical layout.

| GitLab subgroup | Known existing repositories | Architectural role |
| --- | --- | --- |
| **Foundation** | `ros-interfaces` | Shared ROS message/service/action definitions and low-level contracts |
| **Drivers** | `robot_so101`, `camera_opencv` | Robot and camera-specific integration; additional drivers are extensibility targets |
| **Core** | `cell_config`, `recorder`, `control_arbiter` | Cell configuration, recording and arbitration/control services |
| **Applications** | Repositories not yet specified here | End-user workflows and eventual web GUI |

The GitLab listing indicates there are more repositories than shown above. **This table is intentionally incomplete**: inspect the actual group and source trees before assigning ownership or claiming capabilities. Names such as `dataset-tools`, `simulation`, `training`, `atm`, `deployment`, or `workspace` elsewhere in earlier design notes are *proposed or unverified*, not confirmed repositories in this group.

The group hierarchy and the runtime dependency architecture are related but not identical: **Foundation** supplies cross-layer interfaces; hardware itself is outside GitLab; **Drivers** expose hardware to ROS; **Core** implements stable services and orchestration; **Applications** consumes those services. Training backends and model adapters should be placed by interface ownership, without forcing all cloud or notebook code into ROS nodes.

An integration workspace repository (if present or added) can own `mrp.repos`, Compose profiles, cross-repository tests, and the entry point for Codex/Claude Code. Do not assume the integration repository already exists. `vcstool` and Docker Compose remain the intended integration mechanisms.

Do not force every conceptual layer into one repository. Assign code to the repository that owns its stable interface and lifecycle. An adapter may live in its own repository. Avoid cyclic dependencies and hidden cross-repository imports.

## Development and deployment conventions

The local recording application baseline is implemented in
[`application/mrp_app`](application/mrp_app/README.md). It provides a dashboard,
API and CLI, a hardware-free UI demo, and integration with the mock SO-101
recording/validation/export pipeline. See
[`RECORDING_BASELINE_PLAN.md`](RECORDING_BASELINE_PLAN.md) for the broader plan.
The source-free Docker Hub release described below remains planned.

- ROS 2 **Jazzy** for robot-side components; use `colcon`, `rosdep`, launch files, and standard ROS interfaces where appropriate.
- Docker-first for reproducible services; multi-architecture builds where needed (`amd64` and Jetson-compatible `arm64`). Release runtime images are intended to be public on **Docker Hub**, subject to redistribution rights.
- Multi-repo checkout managed with **vcstool** (`mrp.repos`). Keep the manifest pinned for reproducible project states; update intentionally.
- **Every first-party package must be covered by GitLab CI/CD.** Each repository must provide a `.gitlab-ci.yml`, directly or through shared includes, covering all packages it owns: build, lint, relevant unit/contract tests, and container build checks for containerized services. Release pipelines publish verified runtime images to Docker Hub with version tags and immutable digests. Keep publication credentials masked/protected and unavailable to untrusted merge requests. Interface/library packages may share a tested base image rather than each having a runtime container.
- Default deployed ROS communication: **ROS 2 Jazzy with `rmw_zenoh_cpp` and a Zenoh router**. Zenoh is ROS middleware, not DDS; DDS implementations used for contract qualification or explicit development profiles remain separate supported configurations. Record middleware settings and `ROS_DOMAIN_ID` in the cell configuration.
- Tooling includes MCAP/rosbag2, Foxglove bridge, RViz2 and Gazebo. Prefer native laptop installations of RViz2 and other interactive tools for responsive visualization; configure them to join the cell's Zenoh router.
- Promote changes through unit tests, adapter contract tests, simulated integration tests, then explicitly authorized hardware tests.
- License intention: **AGPL-3.0-or-later** for MRP-owned repositories where compatible. Review third-party dependencies, datasets, pretrained model licenses and distributed artifacts separately; AGPL does not override their terms.

### Application and cell packaging (planned)

The intended user installation is a published **application Compose file** that pulls released images; users should not need to clone or build the component repositories. Source checkouts and `vcstool` remain the developer workflow. Local configuration, calibration and persistent data are still required and can be created during setup.

Use two independently managed Compose projects:

| Stack | Services and ownership |
| --- | --- |
| Application (`mrp-app`) | Web GUI, backend/API, persistent project/job metadata, and a cell deployment agent |
| Cell (`mrp-cell-<id>`) | A Zenoh router, selected robot/camera drivers, teleoperation source, control arbiter, recorder and optional policy runtime |

The backend validates a saved cell configuration, resolves a compatible versioned component catalog, and asks the deployment agent to render and apply the cell Compose plan. Ship the catalog and Compose templates inside a released application/agent image so the application Compose file can remain the sole downloaded entry point. Production Compose plans reference public Docker Hub `image:` digests and contain no source `build:` contexts. Persist each generated plan, resolved image digests and configuration snapshot for status, restart, reconciliation and reproducibility.

The deployment agent runs Docker Compose against the **host Docker Engine**, creating sibling containers. It does not run a nested Docker daemon. Only the agent receives Docker access; the GUI and general backend do not need the Docker socket. Docker access grants powerful host control, so expose a restricted deployment API using validated component templates rather than accepting arbitrary Compose or shell input. Resolve bind mounts as paths on the Docker host; files present only inside the agent container cannot be bind-mounted into sibling containers. Use named volumes for recordings and application state where practical.

Start the application independently of the cell. Users configure and review a cell before explicitly starting it; launching the GUI must not automatically enable real robot hardware. The agent must distinguish container state from ROS readiness, serialize changes per cell, and reconcile existing containers after an application restart. Stopping a cell must leave the application available. Separate Compose project names isolate Docker resources; ROS domains, namespaces and router endpoints must also be configured to avoid cross-cell collisions. A later remote cell host should run its own deployment agent behind an authenticated connection.

The cell owns its Zenoh router. ROS containers and native laptop tools use `rmw_zenoh_cpp`, the same ROS domain, compatible interface versions, and an explicit reachable router endpoint. Laptop tools should use Zenoh client mode so access does not depend on reaching container peer addresses. Router endpoints differ between Compose networks, a local laptop and a remote robot host; `localhost` always refers to the current network namespace. Publish or bind the router endpoint accordingly. Keep router configuration with the cell release. Native RViz2 also needs locally installed robot descriptions/meshes and compatible display plugins. A laptop DDS node does not automatically communicate with a Zenoh cell.

Release acceptance should include pulling the application images and starting a complete mock cell on a clean host without source checkouts, verifying ROS readiness and native-tool connectivity, and checking restart/shutdown with persistent data retained. First installation and updates need network access; operation remains local/offline once the selected images and artifacts are available.

References: [ROS 2 Jazzy Zenoh middleware](https://github.com/ros2/rmw_zenoh/blob/jazzy/README.md), [Compose project names](https://docs.docker.com/compose/how-tos/project-name/), and [Docker daemon security](https://docs.docker.com/engine/security/).

### Start the application with one command

From the workspace root (needs Docker with Compose and initialized driver submodules):

```bash
./start.sh
```

It pulls the cell and application images from `felixpfeifer` on Docker Hub, building any that cannot be pulled from the local source, then serves the web UI at
**http://127.0.0.1:5173** (the backend API and `/docs` are on port 8088). Stop it with `./start.sh down`. Use
`WITH_USB_CAMERA=1 ./start.sh` once if you want a real USB camera. Details and the
hardware-free UI demo are in `application/backend/README.md`.

### Example entry point (after repositories and manifests exist)

```bash
git clone <gitlab-workspace-url> mrp_ws
cd mrp_ws
vcs import src < mrp.repos
docker compose --profile teleop up
```

This is an intended workflow, not a guarantee that every service or profile is implemented today. Each repository should document its own prerequisites and commands.

## Guidance for Codex, Claude Code, and contributors

Treat this document as the **product vision and architectural direction**, not proof of existing functionality. Before implementing a task:

1. Inspect the actual repositories, current interfaces, `mrp.repos`, Compose files, and tests. Distinguish **implemented**, **in progress**, and **planned** features.
2. Identify the owning layer/repository and the smallest stable interface to change. Prefer additive, backwards-compatible adapters and versioned schemas.
3. Avoid coupling core recording, datasets, and workflows to one robot, cloud, model framework, GPU, or frontend.
4. Keep **offline/local** operation functional; make network uploads and cloud spending opt-in.
5. Never send robot motion commands as part of automatic tests without operator approval and verified safety procedures. Simulate first; preserve hardware interlocks, deadman controls, limits and emergency stops.
6. Protect credentials, recordings, human images, dataset permissions, and cloud resource access. Do not log or commit secrets.
7. Provide a concrete implementation plan, acceptance criteria, relevant tests, documentation updates, and migration notes for cross-repository changes.
8. Do not invent package names, supported model versions, command flags, container tags, or completed features. Verify them in code and upstream documentation.
9. Keep shared design decisions in `docs/architecture/` or ADRs. Root `AGENTS.md` and `CLAUDE.md` should be short pointers to these contracts and to repository-specific commands, not competing architecture specifications.

### Priority roadmap (proposed)

1. **Reliable vertical slice:** one SO-101/UR-compatible cell → MCAP → validated LeRobot dataset → ACT training → safe inference, with repeatable local Compose setup.
2. **Formalize contracts:** robot/sensor capabilities, cell schema, task/run/artifact metadata, model and backend adapters, CI contract tests.
3. **Backends and portability:** local, Azure ML, DGX/Jupyter and Colab workflows, with clear compatibility and artifact movement.
4. **Project-based application:** API and web GUI that guide users through configurable, resumable workflows.
5. **Plugin ecosystem:** documented extension SDK, third-party drivers, model families, deployment targets and optional Hub integration.

## Project context

Developed as a Master's project at **Hochschule Heilbronn** with the goal of practical, reproducible and extensible imitation learning for Physical AI.
find . -name .git -prune -print0 | while IFS= read -r -d '' gitdir; do git -C "${gitdir%/.git}" fetch; done