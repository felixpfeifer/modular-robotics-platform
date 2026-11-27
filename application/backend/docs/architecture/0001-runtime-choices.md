# ADR 0001: Local recording application runtime

Status: accepted for baseline 0.1.

Use Python 3.12 and its standard-library HTTP server, SQLite, JSON and threading
for this single-user, localhost application. The frontend is buildless HTML,
CSS and JavaScript, served by the same process with no CDN assets. This avoids
a package installation or frontend build before the first usable workflow.
There are no third-party Python dependencies in demo mode. ROS mode obtains
`rclpy`, shared interfaces and recorder configuration loaders from the existing
ROS Jazzy recorder image/workspace. The CLI calls the same HTTP API as the UI.

The API contract is served at `/openapi.json`. Local input validation, allowed
host checks, JSON-only writes and same-origin checks bound the initial API.
This server has no authentication or TLS and is not a public hosted service.
Use an authenticated boundary and revisit the HTTP framework before remote or
multi-user deployment.

The application never receives Docker access. A separate agent wraps the
`cell_config.ComposePreset` runner, which reuses the existing deployment lock
and Docker Compose mechanism. It renders no second cell schema: its only input
is the trusted mock Compose preset provided at deployment time. The agent
rejects real robot backends/device mappings and exposes fixed operations.

Keep existing recorder artifacts authoritative. SQLite holds projects, session
snapshots and export-job references. UI demo sessions never produce accepted
artifacts. Export jobs freeze a selection of accepted recordings and delegate
conversion to the recorder converter, which reopens the complete dataset.

The API starts independently of ROS. A background adapter waits for a reachable
router before opening a client-mode Zenoh session. The application resolves
`DOCKER_GATEWAY` from its Linux container route to reach the host-networked cell,
including on Docker Desktop. Native laptop tools also use client mode while the
router is running. All ROS participants use domain 42.

Application restart interrupts local session ownership and reconciles persisted
export reports. It never automatically starts recording or enables teleop.
Externally active recordings block new starts until the recorder is idle.
Automatic adoption/control of a recording goal after a client restart is deferred.

The source development stack is implemented first. Docker Hub publication,
release image digest catalog and the single-file installation without source
mounts remain later release work; no published image names are assumed.

Reference: [Jazzy Zenoh router checks](https://github.com/ros2/rmw_zenoh/blob/jazzy/README.md#checking-for-a-zenoh-router).
