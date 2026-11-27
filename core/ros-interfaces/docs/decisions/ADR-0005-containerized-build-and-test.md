# ADR-0005: Containerized build and test

- Status: Accepted
- Date: 2026-07-23

## Decision

Run repository validation, ROS builds, tests, and evidence generation in the
approved ROS 2 Jazzy container with `rmw_cyclonedds_cpp`. The host supplies only
Docker or compatible Podman, Git, and Make.

Mount source read-only at `/workspace/source` and results read-write at
`/workspace/results`. Copy source to an isolated container-local workspace.
Use a unique `ROS_DOMAIN_ID`, run communicating processes in the same container,
and reject an active middleware other than Cyclone DDS.

The verification script always atomically writes
`interface-test-results.json`, retains diagnostics, and returns the failing
stage's exit status.

Release-impacting pipelines must set `ROS_BASE_IMAGE` to an owner-approved
immutable digest. A mutable default is allowed only for initial local bootstrap
and is rejected by protected release jobs.

## Consequences

Host ROS state cannot hide undeclared dependencies. The tooling image is a
development artifact, not a production runtime artifact.
