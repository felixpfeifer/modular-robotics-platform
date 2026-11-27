# Platform ROS 2 Interfaces

Versioned, vendor-neutral ROS 2 contracts shared by the Modular Robotics
Platform. The repository contains interface definitions, their verification
fixtures, and downstream interface packaging; it does not contain runtime
nodes, drivers, arbitration, safety policy, or deployment logic.

The four packages are released in lockstep:

- `platform_common_interfaces`
- `platform_device_interfaces`
- `platform_control_interfaces`
- `platform_episode_interfaces`

The supported build and test environment is ROS 2 Jazzy on Ubuntu 24.04 using
Cyclone DDS. A host ROS installation is neither required nor used.

## Quick start

Requirements: Docker (or a Docker-compatible Podman command), Git, and Make.

```sh
make verify
```

Verification runs in the repository tooling container and always writes
`artifacts/interface-test-results.json`, including when a stage fails. Other
evidence is written below `artifacts/`.

GitLab CI builds its own verification image from
`containers/Dockerfile.jazzy-cyclone` in this repository and pushes it to this
project's GitLab Container Registry. Its immutable digest is passed to the
verification jobs automatically; no separate tooling project or manually
configured tooling-image variable is required.

The reusable Jazzy/Zenoh image is built from this checkout on native AMD64 and
ARM64 runners and published to Docker Hub after verification. Scheduled
pipelines rebuild it only when the upstream ROS image or interface revision
has changed. See [ROS base image](docs/ros-base-image.md) for setup.

Useful targets:

```sh
make image       # build the pinned Jazzy/Cyclone DDS tooling image
make build       # clean interface build in the container
make test        # build and run tests in the container
make verify      # all validation, build, tests, and evidence generation
make validate    # fast repository checks (also containerized)
make commit      # Commitizen prompt in the tooling container
```

## CI tooling image setup

Enable the Container Registry for this GitLab project. The `tooling:build`
job uses GitLab's built-in `CI_REGISTRY_USER` and `CI_REGISTRY_PASSWORD` to
publish `$CI_REGISTRY_IMAGE/interface-tooling:<commit>-<pipeline>`. No extra
registry project, Docker Hub tooling repository, or stored tooling credentials
are needed. GitLab Runner must be able to pull from the project's registry
using its job credentials.

Set the project variable `TOOLING_RUNNER_TAG` to your native build runner's
tag; it defaults to `arm64`. The tooling job and all ROS verification jobs
share this tag, so the single-architecture tooling image runs on matching
hardware. The runner must support Buildah with `vfs` storage and `chroot`
isolation; configure its executor security permissions accordingly.

The tooling job emits a dotenv artifact named
`CI_INTERFACE_BUILT_TOOLING_IMAGE` containing the pushed image's digest.
Later jobs inherit this variable; jobs with explicit `needs` also request the
tooling artifact. Do not define this generated variable in project settings.
The old `CI_INTERFACE_TOOLING_IMAGE` project variable is no longer required
and can be removed. Candidate publication still requires explicit approval
and an immutable verification-image reference.

Start a new pipeline after pushing this configuration. Verification jobs run
directly inside the generated ROS image; no Docker-in-Docker service is
required. The final Jazzy/Zenoh base is separately built on native AMD64/ARM64
runners and published to Docker Hub.

## Contract and compatibility policy

Read [REPO_CONTRACT.md](REPO_CONTRACT.md) before proposing an interface.
Field semantics, units, bounds, ownership, producer/consumer information, and
examples are catalogued in `docs/contracts/catalog.json`.

All package versions and `VERSION` must match. Existing fields, their order,
their types, and their bounds are immutable within a major compatibility line.
Breaking evolution uses expand–migrate–contract; see
`docs/decisions/ADR-0002-contract-evolution.md`.

## License

Apache License 2.0. See [LICENSE](LICENSE).
