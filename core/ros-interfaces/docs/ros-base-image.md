# ROS Base Image

`containers/Dockerfile.jazzy-zenoh` packages ROS 2 Jazzy, `rmw_zenoh_cpp`, and
all four compiled platform interface packages for AMD64 and ARM64. The
entrypoint sources ROS and `/opt/platform/install/setup.bash`. No production
nodes or deployment services are added. Zenoh is a ROS middleware, not DDS.
Cyclone DDS remains the interface qualification environment; each Zenoh image
also receives an architecture-native discovery/import/middleware smoke test.

## GitLab Setup

Use the existing interface repository pipeline; no separate image repository
or interface clone is needed. Configure project CI/CD variables:

| Variable | Value |
| --- | --- |
| `DOCKERHUB_USERNAME` | Account with write access; images go to `$DOCKERHUB_USERNAME/<image>` |
| `DOCKERHUB_IMAGE` | Optional override; default `$DOCKERHUB_USERNAME/mrp-ros-base` |
| `DOCKERHUB_TOKEN` | Write-access token; masked and protected |
| `AMD64_RUNNER_TAG` | Native AMD64 runner tag; default `amd64` |
| `ARM64_RUNNER_TAG` | Native ARM64 runner tag; default `arm64` |
| `TOOLING_RUNNER_TAG` | Native tooling/verification runner tag; default `arm64` |
| `ROS_BASE_UPSTREAM_IMAGE` | Upstream image to monitor; default `docker.io/library/ros:jazzy-ros-base` |
| `ROS_BASE_FORCE_REBUILD` | Set to `true` to force a scheduled rebuild; default `false` |

Create the Docker Hub repository first. Protect the default branch and release
tags. Automatic image jobs run on the protected default branch or protected
version tags such as `v0.1.0` and `v0.1.0-rc.1`, after the existing verification
and release gates. This same repository builds its Cyclone DDS verification
image automatically and stores it in the project's GitLab Container Registry.
Enable that registry; no separate tooling project or manual
`CI_INTERFACE_TOOLING_IMAGE` variable is needed. The Zenoh image does not
replace the verification image.

Both tagged runners need to support `quay.io/buildah/stable:v1.40.1` and
Buildah builds with `vfs` storage and `chroot` isolation. Configure executor
security permissions accordingly. No ARM emulation is needed. The AMD64
runner also performs registry checks and manifest publication. Docker Hub
credentials are project variables available to the child pipeline; never
store tokens in the repository. GitLab secret detection runs in `image-check`, and
`image:context` runs gitleaks over the tracked sources first
(`.gitlab/ci/docker-hub.yml`, shared by all MRP repositories).

## Updates And Schedules

Default-branch pushes rebuild the current interface checkout automatically.
The check job resolves the upstream multi-architecture manifest digest once;
both native builds use that exact digest. Only after both builds and smoke
tests succeed does publication update the shared Docker Hub manifest.

In GitLab, create a pipeline schedule targeting the protected default branch
under **Build > Pipeline schedules**, for example daily with `0 3 * * *` in
your chosen timezone. The schedule owner must have access to protected refs
and variables. No special schedule variables are required.

Scheduled pipelines retain the repository's existing verification gates,
then inspect the published `jazzy` image for both architectures. Builds are
skipped when both images record the current interface commit and upstream ROS
digest. Missing images, missing labels, or inspection failures trigger a
rebuild attempt; failure to resolve the upstream image fails the check job.
A skipped build produces a successful no-op child pipeline.

APT-only updates, including a new Zenoh package with no change to the upstream
ROS image digest, are not detected by this comparison. Use
`ROS_BASE_FORCE_REBUILD=true` on a schedule or manually triggered pipeline to
refresh these dependencies. Manual non-scheduled pipelines always rebuild.
For reproducibility rather than upstream tracking, set the upstream variable
to an immutable multi-architecture digest.

Published tags:

- `jazzy-<commit>-<child-pipeline>-amd64` and `...-arm64`: native images.
- `jazzy-<commit>-<child-pipeline>`: combined manifest.
- `jazzy`: rolling default-branch manifest.
- `latest`: the same rolling default-branch multi-architecture manifest as `jazzy`.
- `jazzy-<release-tag>`: versioned manifest from a protected release tag.

Pipeline-specific tags keep architectures from separate builds from mixing.
Manifest publication is serialized. Do not retry an old rolling-manifest job
after a newer pipeline has published; use the newest pipeline instead.

## Downstream Use

Docker selects the matching architecture automatically:

```dockerfile
FROM yourorg/mrp-ros-base:jazzy
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
```

`FROM yourorg/mrp-ros-base:latest` also selects the matching architecture.
Both rolling tags are updated after the native builds and smoke tests pass;
release pipelines publish a separate versioned tag.

Install your package build/runtime dependencies, copy only your package
sources, and source `/opt/platform/install/setup.bash` before `colcon build`.
Docker build steps do not execute the entrypoint. Source your application's
install overlay at runtime as well. For reproducible builds, use a versioned
tag such as `jazzy-v0.1.0` or the published manifest digest. Private Docker Hub
repositories require pull credentials in downstream projects.

Downstream CI builds should pull the base (`docker build --pull` or
`buildah bud --pull`). Publishing a new base does not automatically rebuild
existing application images; downstream triggers or schedules are separate.

The image does not automatically start a Zenoh router. Run
`ros2 run rmw_zenoh_cpp rmw_zenohd` in a separate container/service. Configure
compatible Zenoh endpoints and `ROS_DOMAIN_ID` for participating application
nodes; Cyclone DDS nodes do not communicate directly with Zenoh nodes.

## Local Build

From the interface repository root:

```sh
docker buildx build --platform linux/amd64 --load \
  -f containers/Dockerfile.jazzy-zenoh -t mrp-ros-base:jazzy .
docker run --rm mrp-ros-base:jazzy ros2 interface list
```

Use `linux/arm64` on an ARM64 builder. Local builds do not publish anything.
