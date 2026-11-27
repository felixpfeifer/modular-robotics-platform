# MRP recording backend

An API and CLI for the mock SO-101 cell. The browser dashboard lives in the
separate `../frontend` Vite project.
Includes persistent projects/session snapshots, recording controls, episode
validation reports, and tracked local LeRobot v3 export through the existing
recorder converter. Training, inference and real hardware remain outside scope.

## Run a mock robot workspace locally (no hardware)

Three levels, from lightest to most realistic. None of them needs a physical
robot, serial device or webcam; all arms and cameras are simulated.

| Level | What runs | Needs | Records data / exports |
| --- | --- | --- | --- |
| 1. UI demo | Backend + frontend only | Python 3.12+, uv, Node/yarn | No |
| 2. Mock ROS cell (`mock-so101`) | Backend, agent, mock arms, synthetic camera, recorder | Linux Docker + Compose | Yes (synthetic) |
| 3. Gazebo tabletop (`sim-so101`) | Level 2 plus Gazebo physics, red cube, green target | Level 2 + a capable CPU/GPU | Yes |

All commands start from the workspace root (`mrp/`) unless stated otherwise.

### Level 1 - UI demo (fastest, no ROS, no Docker)

Terminal 1, backend:

```bash
cd application/backend
uv sync --locked
make run            # API on http://127.0.0.1:8088
```

Terminal 2, frontend:

```bash
cd application/frontend
corepack enable
yarn install
yarn dev            # normally http://127.0.0.1:5173
```

Open **http://127.0.0.1:5173**. Create a project, start the demo cell, enable
teleoperation, then start an episode and mark success/failure or add an
annotation. Session metadata persists under `.data/demo/` across restarts.
Ctrl+C stops each process.

**Demo mode is a UI demonstration.** It starts no ROS nodes or Docker containers,
writes no MCAP, and cannot export datasets. Successful demo sessions are labelled
`demo_complete`, never `accepted`. The moving preview is a browser illustration.
The recording and deployment views show explicitly labelled simulated SO-101
joint positions, velocities and teleoperation commands. Enabling teleoperation
moves the demo joints, with a small follower delay; disabling it holds their pose.
These signals illustrate the UI only: they are not sensor readings, robot physics
or trained-policy inference. Real recording and inference require the ROS runtime.

Backend only, in Docker (no frontend dev server needed):

```bash
cd application/backend
docker compose -f compose.demo.yaml up --build
```

### Level 2 - Mock ROS cell (`mock-so101`)

Prerequisites: Linux Docker host with Compose, the full MRP workspace checkout,
initialized robot driver submodules (`git submodule update --init --recursive`),
free ports 7447/8088/9108, and 10 GiB free storage for recorder preflight. Do not
run another cell on ROS domain 42. No physical devices are mounted.

```bash
# 1. Build the cell images (./start.sh does this): robot, recorder, converter.
docker build -t mrp-robot-so101 driver/robot_so101
docker build -t mrp-episode-recorder -f core/recorder/Dockerfile core
docker compose -f application/backend/deployment/mock-cell/compose.yaml \
  -f application/backend/deployment/cell.compose.yaml --profile tools build

# 2. Build and start the application (backend + agent).
export MRP_WORKSPACE_ROOT="$PWD"
docker compose -f application/backend/compose.dev.yaml build
docker compose -f application/backend/compose.dev.yaml up -d
```

Open the UI at **http://127.0.0.1:5173** (port 8088 is the backend API only, see `/docs`). The application starts independently of the cell.

1. Create/select a project. The baseline task is fixed to `pipeline_check`.
2. Review the mock deployment plan and click **Start cell**.
3. Wait for fresh streams, camera rate, command bridge, validator and recorder.
4. Explicitly enable teleoperation. The mock arms initially share a zero pose.
5. Start recording and capture at least five seconds. Mark success or failure.
6. Inspect the validation report; task success alone does not imply accepted data.
7. Select accepted episodes and click **Export dataset**. The converter runs
   only for that job. There is no training, inference or network upload.

You can also run the cell by hand without the app (arms, camera, arbiter,
recorder keyboard UI, optional leader pose commands): see
`deployment/mock-cell/compose.yaml`.

The ROS preview uses the synthetic JPEG topic and streams up to 10 FPS to the
browser. Recording continues at its configured 30 FPS. Recordings contain
synthetic pipeline-check data.
Recorder preflight and validation remain authoritative.

The web port is published to laptop localhost. The agent is reachable only on
the private application network. The cell joins the shared `mrp-cell` Docker
network and the ROS adapter connects to its Zenoh router by service name (client
mode); the API stays available while waiting. Docker Desktop and native Linux
Docker use this same setup; native laptop RViz2 remains a separate client.

### Level 3 - Gazebo tabletop simulation (`sim-so101`)

A physics follower with a rendered camera, a movable red cube and a green target
(tasks `red_cube_to_rectangle`, `scene_motion_check`; ROS domain 43, Zenoh port
7450). Build the images listed in `config/sim-so101/README.md`, then start the
application as in Level 2 with the project's follower set to Gazebo and camera
to the Gazebo scene. The app starts the cell for you from the **Cell** page.
Note: the app's ROS runtime is bound at start-up to one preset, so to record
from the simulation start the backend with `MRP_RUNTIME_PRESET=sim-so101`.

### Stopping and cleaning up

Finish or cancel a recording first, stop the cell from the UI, then:

```bash
docker compose -f application/backend/compose.dev.yaml down      # keeps volumes
docker compose -f application/backend/compose.dev.yaml down -v   # deletes app data
```

Troubleshooting: if the UI shows the cell as unreachable, check that no other
cell uses ROS domain 42 and that `MRP_WORKSPACE_ROOT` is still exported.

## Guided project workflow

The app is organised per project: **Overview** (next step), **1 Cell**, **2 Record**,
**3 Dataset**, **4 Train**, **5 Deploy**. Each project stores its own cell choice
(leader, follower, camera, task). Combinations are validated against
`backend/mrp_app/catalog.py` and resolved to a vetted preset that the agent can
run (`mock-so101`, `sim-so101`); hardware options are listed as *planned* and
cannot be selected. The agent never accepts arbitrary Compose or shell input.

- **Train** runs offline CPU ACT training from a completed export. Optionally
  start from an existing model path (`<run-id>/output/checkpoints/last/pretrained_model`
  in the `mrp-training_runs` volume) to fine-tune.
- **Deploy** starts the policy server for the cell, then separately hands control to
  it with an explicit confirmation. The agent checks the checkpoint is a complete ACT
  model trained on this cell's camera feature. Mock/simulation only.

Getting a model (Train page): train locally in Docker; generate a Jupyter notebook for a
GPU server (dataset from the Hub or as a ZIP) and import the resulting `pretrained_model.zip`;
import an ACT checkpoint from a Hugging Face model repo (public, or with the token saved in
Settings); or import a checkpoint zip. All routes produce a project-owned *model* in the same
layout, which Deploy and "start from model" use. Datasets: download a ZIP from the Dataset page
for a training node, or upload to the Hub (token entered once, or the saved one).
The Hugging Face token lives in `settings.json` (0600) in the application data volume and is
never returned by the API.

Networking: the mock cell's router is reached over `mrp-cell`; it is additionally published
for other nodes on `MOCK_ZENOH_BIND` (default 127.0.0.1, port 17447, ROS domain 42). The router
has no authentication; choose a wider address only deliberately.

Known limits: the application's ROS runtime is bound at start-up to one preset
(`MRP_RUNTIME_PRESET`, default `mock-so101`); projects with another cell can be configured but
recording, export and deployment are refused until runtime switching exists. Selecting the policy
source does not yet verify that the policy source node is publishing; the arbiter watchdog
stops forwarding if it is silent. Only ACT is importable/trainable today (Diffusion and VLA
policies are listed as planned).

## Storage and shutdown

| Volume | Contents |
| --- | --- |
| `mrp-app_app_data` | SQLite project/session/job metadata |
| `mrp-mock-so101_recordings` | Raw episodes and validation reports |
| `mrp-app_exports` | Per-job accepted selection, converter log, report and dataset |

Export output is `/data/exports/<job-id>/dataset` inside the export volume.
`repo_id` is a local LeRobot identifier, not an upload request. Each job gets a
fresh destination. Successful export includes reopening the complete dataset.
Changed MCAP hashes, rejected episodes and stale validation evidence block export.

To copy an exported dataset to your laptop, run from the workspace root with
the job UUID shown in the dashboard:

```bash
docker compose -f application/backend/compose.dev.yaml \
  cp app:/data/exports/<job-uuid>/dataset ./my-dataset
```

Finish or cancel a recording before stopping the cell from the UI. The app stays
available after the cell stops. From the workspace root, stop the app separately:

```bash
docker compose -f application/backend/compose.dev.yaml down
```

Keep `MRP_WORKSPACE_ROOT` set. Stopping the app does not implicitly stop the cell.
Volumes remain after `down`; `down -v` deletes their contents. On restart,
interrupted sessions remain visible; inspect external recordings through the
recorder rather than blindly retrying. Persisted export reports reconcile jobs
that finish during a backend restart. Automatic goal adoption is not implemented.

## CLI and API

From this application directory:

```bash
PYTHONPATH=backend python3 -m mrp_app.cli status
PYTHONPATH=backend python3 -m mrp_app.cli project "Tabletop collection"
PYTHONPATH=backend python3 -m mrp_app.cli cell plan
PYTHONPATH=backend python3 -m mrp_app.cli cell up
PYTHONPATH=backend python3 -m mrp_app.cli source teleop
PYTHONPATH=backend python3 -m mrp_app.cli start <project-uuid>
PYTHONPATH=backend python3 -m mrp_app.cli mark <episode-uuid> success
PYTHONPATH=backend python3 -m mrp_app.cli episodes
PYTHONPATH=backend python3 -m mrp_app.cli export <accepted-episode-uuid>
```

Use `--request-id <uuid>` with `start`/`export` and reuse it on retries. The CLI
prints generated IDs before sending. One episode and one export run at a time.
Open **http://127.0.0.1:8088/** to reach the interactive Swagger UI at `/docs`.
Expand an operation and use **Try it out** to enter its parameters or request body
and send a request. The API schema is at `/openapi.json`. Swagger UI loads its
JavaScript and CSS from jsDelivr, so the documentation page requires internet
access; the API and schema do not.
`/health` checks the application process; `/api/v1/status` reports runtime readiness.

## Live camera viewing

The Record page shows configured cameras together and streams the latest ROS
JPEG from each over a WebSocket at up to 10 FPS per view. The backend subscribes
to additional cameras only while they have viewers and skips intermediate frames.
Recording uses its own camera subscriptions and configured rates. The optional
WebRTC API shows the primary camera.

## Camera types: built-in, found on the host, custom

The **type** dropdown of a camera module (Cell page) lists every camera model a cell can run,
grouped by where it comes from:

| Group | Source | How it gets there |
| ----- | ------ | ----------------- |
| Built-in | `backend/mrp_app/cameras.py` (`BUILTIN`) | First-party drivers: USB webcam, RealSense, IDS uEye |
| Found on this host | Local Docker images labelled as MRP camera drivers | The deployment agent scans `docker image ls` (cached 15 s) |
| Custom | Added with **+ Add custom camera…** in the dropdown | Stored by the application, read by the agent |

A type whose driver image is not on the deployment host is marked *not on this host*; select it
and use **Pull image** (custom and found types), or `./start.sh` for built-in ones. Custom types
can be removed again once no project's layout or cell uses them.

### Camera driver contract

Any image (yours or a vendor's) works as a camera type if it follows the same contract as
`driver/camera_opencv`, `camera_realsense`, `camera_ids` and `camera_genicam`:

- ROS 2 Jazzy with `rmw_zenoh_cpp`; building `FROM docker.io/felixpfeifer/mrp-ros-base` gives both.
- The image **entrypoint** starts the driver node and appends its arguments (`"$@"`): the cell
  runs it with `--ros-args -r __node:=camera_<id> -p image_width:=… -p image_height:=… -p fps:=…
  -r image/compressed:=<topic>`, plus `-p serial_number:='…'` (USB) or `-p address:='…'` (network).
- It publishes `sensor_msgs/msg/CompressedImage` on `image/compressed` with `format: "jpeg"`
  at exactly the configured width and height (the recorder checks both).
- The **probe command** (e.g. `ros2 run camera_acme camera_node`) starts the same node for the
  connection test. That test sources `/opt/platform/install/setup.bash` and
  `/app/install/setup.bash` when present (else `/opt/ros/$ROS_DISTRO/setup.bash`), and needs `python3`
  with `rclpy` in the image.

Two access types are possible for found and custom types (built-in V4L2 webcams use `video_node`):

- `usb_bus`: the driver gets `/dev/bus/usb` and the USB character-device rule `c 189:* rmw`,
  like RealSense. It never gets `privileged`, other devices or extra capabilities.
- `network`: an IP camera. The driver gets the cell network and no host device. Its cell entry
  needs an `address`.

### Make an image show up automatically

Add two labels to the driver's Dockerfile. The manifest uses the same fields as the custom form:

```dockerfile
LABEL io.mrp.driver.kind="camera" \
      io.mrp.driver.manifest='{"id": "acme_x1", "label": "Acme X1", "access": "usb_bus", "fps_type": "int", "probe_command": ["ros2", "run", "camera_acme", "camera_node"], "variants": {"mono": "Mono"}, "usb": {"vendor_id": "1d6b", "product": "acme"}, "note": "Optional text shown in the UI."}'
```

| Field | Required | Meaning |
| ----- | -------- | ------- |
| `id` | yes | 2-32 lowercase letters, digits, `_`; not a built-in id |
| `label` | yes | Name in the dropdown (max 60 characters) |
| `probe_command` | yes | 1-12 plain arguments that start the node (no shell) |
| `access` | no | `usb_bus` (default) or `network` |
| `fps_type` | no | `int` (default) or `float`: the type the node declares `fps` as |
| `variants` | no | Up to 20 `id: label` pairs, e.g. sensor variants |
| `usb` | no | `vendor_id` (4 hex digits) and optional `product` text, so the connection test can find the camera on USB; without it only opening the camera tells |
| `note` | no | Shown under the camera on the setup page |

Build or pull the image on the deployment host and it appears under *Found on this host*.
`driver/camera_genicam` carries these labels, so GenICam USB3 Vision cameras are selectable in
cells after `./start.sh` built `mrp-camera-genicam`. Broken labels are listed in
`GET /api/v1/cameras` → `problems` instead of hiding the other images. This is also the way to
make a custom camera a permanent part of the platform: give its driver its own repository with
these labels, and remove the custom entry.

### Add a custom camera in the UI

**Cell page → camera module → type → + Add custom camera…**: name, Docker image, connection (USB
or network), the type of the `fps` parameter, the driver node command, optional variants and USB
vendor id. You must confirm that you trust the image. With a deployment agent, *Pull the image
now* pulls it right away. Then pick the type, choose *Real* on the cell setup page, and run the
connection test. It starts the driver once in a throwaway container with the cell's settings and
checks resolution, frame rate and a snapshot.

Custom types are stored in `MRP_CAMERA_MODELS_FILE` (default `<data dir>/camera_models.json`).
The Compose files keep it on the `mrp-camera-models` volume, mounted read-write in the app and
read-only in the agent, so both validate cells against the same types. The agent checks every
entry again and never gives one more access than its `access` type allows. If the agent lacks
that volume, the catalogue reports that it cannot see the custom cameras.

API (also in `/docs`):

| Method and path | Purpose |
| --------------- | ------- |
| `GET /api/v1/cameras[?refresh=true]` | Every camera model with `origin`, `installed` and `problems` |
| `POST /api/v1/cameras` | Add or replace a custom model: the manifest fields plus `image`, `trusted: true`, optional `pull` |
| `POST /api/v1/cameras/{id}/pull` | Pull a custom or found model's image (never an arbitrary image) |
| `POST /api/v1/cameras/{id}/delete` | Remove a custom model (409 while a project uses it) |

## Custom Docker Hub images

In Components, optional Docker Hub references such as `namespace/image:tag` can replace the
leader, follower, main camera, or side camera image for a project. The deployment agent pulls
each selected image before starting the cell. Use a digest to pin an image; private images need
Docker Hub credentials available to the agent's Docker CLI. Pull failures stop startup.

Only use trusted images: they execute code on the deployment host and may access the selected
hardware. A custom image must implement the existing SO-101 or camera preset's commands, ROS
topics, and configuration. The connection test checks the hardware, not third-party image
behavior. Images alone do not add support for new robot profiles, sensors, or protocols; the
simulation preset does not support these overrides. For remote model training or serving, the
launch command dialog also accepts an image compatible with the selected runtime; Docker pulls
it on the remote host when needed. This does not add a new local model adapter.

## Token storage and container secrets

Hugging Face tokens are write-only: neither status nor settings API responses
return them. They are encrypted before being written to `settings.json`; the
application image uses a Fernet key mounted independently of the data volume.
For an actual container deployment, create a 0400 key file outside this checkout
(`python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`
once, then save the output as the file contents) and start with the secret overlay:

```bash
export MRP_SETTINGS_KEY_FILE=/absolute/private/path/mrp-settings.key
docker compose -f compose.dev.yaml -f compose.secrets.yaml up -d
```

The key must not be committed, placed in Compose environment variables, or copied
into an image. The app creates a 0400 local-development key only when no secret
path is configured. Container administrators with host-root/Docker access can
always inspect a running container; use your platform's secret manager and least
privilege to control that boundary.

After sourcing ROS Jazzy and a built recorder workspace, native ROS mode is:

```bash
PYTHONPATH=backend python3 -m mrp_app --mode ros \
  --workspace-config /absolute/path/to/workspace.yaml
```

Configure ROS domain/middleware/Zenoh variables consistently and use a workspace
whose dataset path is locally readable. Without `--agent-url`, deploy the cell
manually; automated deployment/export controls stay unavailable. ROS startup
errors never silently switch the app to demo mode.

## Verification and GitLab CI

```bash
make check
```

The `make check` command, local CI, and GitLab all verify dependency exports,
run Ruff and mypy, compile the source, and run the Python suite.
The tests use in-process HTTP requests,
loopback sockets for WebSockets and server lifecycle, and temporary fixtures.
The runner writes JUnit results to `artifacts/junit.xml`. Use `make test`
to run the Python suite on its own.

### Backend review standards

- Put request and response schemas at the HTTP boundary. Validate deployment
  agent replies before updating persisted state. Preserve the v1 JSON and
  error contracts when changing implementation details.
- Type new workflow interfaces and return values. Prefer small functions
  with dependencies passed in explicitly. Use Ruff for imports and formatting.
- Use guarded updates for state transitions and one transaction for writes
  that must succeed together. Preserve legacy SQLite rows when changing storage.
- Catch expected errors where the workflow can recover. Log the operation
  and record ID without logging credentials or raw agent payloads. Check
  external evidence before explicitly retrying an interrupted job.
- Add regression coverage for behavior changes, using a fake agent or runtime
  for deterministic timeout and concurrency tests.

When dependencies change, regenerate the container requirements from the lock.

```bash
uv export --locked --no-dev --no-hashes -o requirements.txt
uv export --locked --no-dev --no-hashes --extra media -o requirements-media.txt
```

The current frontend browser tests live in the sibling frontend repository. See
its README for the isolated demo-backend end-to-end test.

With the ROS-mode app available, run the actual mock recording/export check:

```bash
python3 tests/integration/record_export.py
```

It verifies a mock-only plan, starts the cell and teleop, records and validates
an episode, then runs conversion. Artifacts and `artifacts/record-export.json`
are retained. Successful completion disables teleop; inspect state after a
failed test. Stop the test cell from the UI. No existing artifacts are deleted.

GitLab runs the backend checks and builds the app, demo, and agent images.
Actual ROS acceptance is opt-in (`MRP_FULL_INTEGRATION=1`) on tag `mrp-mock`,
with the synthetic mock app already running.

## Boundaries and next work

This is a local, source-based development baseline. Only the agent has Docker
socket access and accepts fixed mock operations; it still has powerful host
access and must remain local. HTTP has no authentication/TLS. Public Docker Hub
releases, immutable release catalogs, source-free installation, multiple
configurable cells/tasks, and hardware qualification remain later work. Keep
interactive RViz2 native on the laptop.

See `docs/architecture/0001-runtime-choices.md` and
`../../RECORDING_BASELINE_PLAN.md`. `mrp.repos` pins observed repository HEADs;
review, commit and repin local integration changes before a reproducible release.

## Upload an existing export to Hugging Face

After building the updated recorder converter image, an explicit one-off upload
can read an application export without copying it between Docker volumes. From
the workspace root, make an authorized write token available in `HF_TOKEN`, then:

```bash
docker compose -f application/backend/deployment/mock-cell/compose.yaml \
  -f application/backend/deployment/cell.compose.yaml run --rm --no-deps -e HF_TOKEN upload \
  --dataset-dir /data/exports/<export-job-id>/dataset \
  --repo-id <namespace>/<dataset> --confirm-upload
```

The default is a private repository. A public repository additionally requires
`--visibility public --confirm-public`. Check the dataset and permissions before
uploading. The uploader and converter use the pinned LeRobot v3 environment; no
upload runs during recording, export, or training. Never put the token in a
Compose file, command-line argument, project configuration or Git.
