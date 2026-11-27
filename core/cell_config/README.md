# cell_config

A ROS 2 Jazzy backend for storing one robot cell's configuration. It describes
leader and follower arms, their control links, cameras, device connections and
ROS names. The HTTP API stores configuration and can start and stop supported drivers using
Docker Compose. It does not discover hardware, verify devices, or command robots.

## Run

Build in a sourced ROS 2 Jazzy workspace:

```sh
colcon build --packages-select cell_config
source install/setup.bash
ros2 run cell_config cell_config --ros-args -p config_path:=$PWD/cell.json
```

The default listen address is `127.0.0.1:8080`, and the default file is
`/data/cell.json`. Set `host`, `port`, and `config_path` as ROS parameters at
startup. The container listens on all interfaces; bind its port to localhost
unless a trusted reverse proxy provides authentication and access control.
The API itself has no authentication or TLS.

```sh
docker build -t cell-config .
docker run --rm -p 127.0.0.1:8080:8080 -v cell-config-data:/data \
  -v /var/run/docker.sock:/var/run/docker.sock cell-config
```

The default base is `docker.io/felixpfeifer/mrp-ros-base:latest`, as used by the existing services.
To use your own compatible ROS Jazzy base image, supply
`docker build --build-arg BASE_IMAGE=your-image:tag -t cell-config .`. The replacement image must provide `/opt/platform/install/setup.bash`.
The base must contain ROS Jazzy, colcon and ament Python build tools.

GitLab CI builds the package with colcon and runs its pytest suite using the
ROS Jazzy base image. The runner needs Docker executor access and network access
to install the test and build tools.

## API

Open `http://127.0.0.1:8080/docs` for Swagger UI, or `/openapi.json` for
the OpenAPI document. Swagger UI requires internet access to load its assets.
The API has no authentication or TLS. Anyone who can call it can start and
stop containers and potentially enable robot hardware; Docker socket access
also grants powerful control over the host. Keep it on a trusted host or behind
an authenticated, access-controlled proxy.

All bodies are JSON. There is initially no cell; `GET /api/v1/cell` returns
404 until the first save. `PUT /api/v1/cell` validates and atomically replaces
the complete document, persists it to disk, and returns the document and an
`ETag`. `GET` returns the same document and its `ETag`. Invalid documents
return 400. `GET /health` checks that the HTTP server is running, not hardware.

```sh
curl -i -X PUT -H 'Content-Type: application/json' --data-binary @examples/cell.json http://127.0.0.1:8080/api/v1/cell
curl -i http://127.0.0.1:8080/api/v1/cell
```

For safe GUI edits, send the ETag received from GET in `If-Match` on PUT. A
stale ETag returns 412, allowing the GUI to reload instead of overwriting a
newer edit. Use `If-None-Match: *` to create only if no cell exists. A PUT
without a precondition overwrites the current document. This protection applies
to requests handled by one service instance; run only one instance per file.
The API is intended for a same-origin GUI or a reverse proxy; it does not
provide cross-origin access.

## Document

See [examples/cell.json](examples/cell.json). IDs are unique across robots and
cameras; control links refer to robot IDs with matching roles. Camera
`attached_to` optionally references a robot. Connections support `serial` and
`usb` with a `/dev/` path, `network` with an address and optional port, or
`simulated` without additional fields. Use stable `/dev/serial/by-id/` and
`/dev/v4l/by-id/` paths where available. Example paths are placeholders: replace
them with the paths on your machine. ROS namespaces and camera topics must be
absolute; use `/` for the root namespace. Driver names are descriptive strings,
not a driver registry. Version 1 rejects unknown fields so mistakes are visible.
Do not store credentials in this document.

## Running cell modules

The deploy tool renders a Docker Compose plan from the saved configuration.
Currently it supports `robot_so101` with a serial connection (real hardware) or
`simulated` connection (the driver's mock backend), and `camera_opencv` with a
USB or simulated connection. Images must already be built on the Docker host with the names
`mrp-robot-so101` and `mrp-camera-opencv`. ROS communication uses Fast DDS and
host networking; other ROS processes must use the same ROS domain and RMW.
The camera driver uses privileged access and `/dev`, following its existing
Compose configuration. An SO-101 real arm may need calibration; this initial
integration does not yet configure calibration files.

For a hardware-free demo, build the `mrp-robot-so101` and `mrp-camera-opencv`
images from their respective driver directories, then run:

```sh
ros2 run cell_config cell_deploy plan --project mrp-demo --config examples/demo.json
ros2 run cell_config cell_deploy up --project mrp-demo --config examples/demo.json
ros2 run cell_config cell_deploy status --project mrp-demo
ros2 run cell_config cell_deploy down --project mrp-demo
```

The demo starts mock leader and follower arms and two synthetic compressed JPEG
camera streams at `/wrist_camera/image/compressed` and
`/overview_camera/image/compressed`. The moving test pattern is generated in the
camera image; it is not a rendered robot scene. The mock arm backend provides
ROS control interfaces without physics simulation. The control link is only
descriptive, so it does not make the follower track the leader.

On the Docker host, with this ROS package installed and sourced:

```sh
# Inspect before starting: this does not contact Docker.
ros2 run cell_config cell_deploy plan --config /path/to/cell.json
# Start or reconcile this project's containers; no image build or pull.
ros2 run cell_config cell_deploy up --config /path/to/cell.json
ros2 run cell_config cell_deploy status
ros2 run cell_config cell_deploy down
```

The tool uses the Compose project `mrp-cell` by default; choose an isolated
project with `--project NAME`. `up` removes containers for services no longer in
the configuration in that project. `down` stops and removes that project's
containers. Starting real arms can enable hardware, so check the plan and the
cell before applying it. Docker Compose and Docker daemon access are required.
The HTTP API exposes the same plan and can run Compose directly:

```sh
curl http://127.0.0.1:8080/api/v1/deployment/plan
curl -X POST http://127.0.0.1:8080/api/v1/deployment/up
curl http://127.0.0.1:8080/api/v1/deployment/status
curl -X POST http://127.0.0.1:8080/api/v1/deployment/down
```

Save a configuration with `PUT /api/v1/cell`, review its plan, then start it.
Pass the plan response's ETag as `If-Match` on `up` to reject a changed
configuration. Each `up` uses a snapshot of the saved document; changing the
file does not automatically reconcile running containers. The project defaults
to `mrp-cell` and can be changed with the `compose_project` ROS parameter.
Docker Compose commands are serialized within one API process. Do not run
multiple instances or other deploy tools against the same project concurrently.
Compose errors return 502; a command timeout returns 504 and may leave changes
behind, so inspect status. Images must already exist on the Docker host. The
API container requires the Docker socket as shown above; when running on the
host, the service user needs access to the Docker daemon and Compose plugin.

Control links are currently descriptive; this does not start or configure the
control arbiter. VLA model deployment is not implemented because its image,
inputs, GPU requirements and runtime contract are not yet defined. The tool
does not report ROS node readiness or detect hardware availability; Compose
status only reports container state.
