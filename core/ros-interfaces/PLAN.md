# Task: Establish the Platform ROS 2 Interface Repository

## Document control

| Field | Value |
| --- | --- |
| Proposed GitLab project | `foundation/platform-ros-interfaces` |
| Parent group | `global-dynamics/robot-foundation-models/modular-robotics-platform` |
| Plan state | Active |
| Initial release target | `v0.1.0` |
| Candidate target | `v0.1.0-rc.1` |
| ROS baseline | ROS 2 Jazzy on Ubuntu 24.04 |
| Proposed license | Apache-2.0, pending owner approval |
| Development and CI environment | Pinned ROS 2 Jazzy build/test container |
| ROS middleware under test | Eclipse Cyclone DDS through `rmw_cyclonedds_cpp` |
| Host requirement | Docker or Podman, Git, and Make; no host ROS 2 installation |
| Production runtime container | None |
| Primary artifacts | Source tag, generated interface packages, type descriptions/hashes, install archive; Debian packages later |

## 1. Goal

Create the versioned ROS 2 contract foundation used by all first-party platform components.

The repository is complete for `v0.1.0` when:

- The initial common, device, control, and episode contracts are defined.
- ROS 2 generates C and C++ typesupport and Python bindings for every contract.
- C++ and Python processes can exchange representative messages, services, and actions.
- Interface type descriptions and hashes are captured as release evidence.
- Bounds, units, identity rules, timestamps, frames, and failure semantics are documented.
- A candidate version can rebuild the first downstream vertical slice without unpinned dependencies.
- The complete build and test suite runs inside the pinned Jazzy/Cyclone DDS container.
- Every test run writes a machine-readable result file into a mounted host workspace directory, including failed runs.
- Commit messages, package versions, tags, and changelog generation follow the repository's Commitizen policy.
- No runtime node, robot-specific algorithm, driver behavior, or deployment logic has entered the repository.

## 2. Problem to solve

The platform contains independently developed drivers, controllers, teleoperation sources, safety services, recording tools, applications, and AI components. Without a single contract repository, each component can invent its own:

- Device identity format.
- Topic fields and naming.
- Timestamp and frame conventions.
- Command validity and ownership representation.
- Safety event format.
- Episode state and validation result format.
- Compatibility assumptions.

That creates compile-time drift, runtime type mismatches, ambiguous semantics, and coordinated release failures. The interface repository solves the representation and interoperability problem. It does **not** implement the behavior represented by those contracts.

## 3. Scope

### 3.1 In scope

- ROS 2 `.msg`, `.srv`, and `.action` definitions.
- Package manifests and rosidl generation configuration.
- Shared constants and bounded identifiers needed by several domains.
- Human-readable semantic documentation for every contract.
- Generated ROS type descriptions and hashes.
- Cross-language serialization and transport acceptance fixtures.
- Compatibility policy and change-classification tooling.
- Example payloads and consumer fixtures.
- A reproducible ROS 2 Jazzy development and CI container definition.
- Container entry scripts that build, test, and export results.
- Commitizen configuration and commit-message validation.
- Release notes, provenance, license inventory, SBOM, and CI evidence.

### 3.2 Out of scope

- ROS nodes, executors, launch files, lifecycle implementations, or hardware plugins.
- Device discovery and registry algorithms.
- Quest/Oculus connectivity and coordinate mapping.
- SO-101, camera, UR, MoveIt, or Gazebo adapters.
- Lease arbitration and lease-expiry behavior.
- Safety policy, collision checking, or physical stopping.
- Episode recording, validation, export, and upload implementations.
- REST, WebSocket, protobuf, database, or configuration-schema ownership.
- Production Docker images.
- Native host or bare-metal ROS 2 builds and test execution.
- Public GitHub monorepo generation.

The separate `platform-config-schema` repository owns configuration schemas. Runtime repositories own behavior. The distribution repository owns integrated installation artifacts. The development/CI container is a reproducible tool environment, not a shipped platform runtime.

## 4. Repository contract

Create `REPO_CONTRACT.md` before implementing the first interface. It must state:

### Responsibility

Own stable, vendor-neutral ROS 2 data contracts shared by two or more platform repositories.

### Non-responsibilities

Do not:

- Encode a single vendor's SDK object model.
- publish or subscribe to topics.
- Open hardware, network, file, or database resources.
- Decide whether a command is safe or authorized.
- Embed configuration documents as arbitrary JSON or YAML strings.
- Duplicate a suitable standard ROS message.
- depend on a first-party runtime package.

### Inputs

- Approved architecture decisions.
- Accepted domain requirements from producer and consumer owners.
- Standard ROS message definitions.
- Version and compatibility policy.
- Bounded size and timing requirements.

### Outputs

- Generated, introspectable ROS 2 types.
- Stable package dependency graph.
- Interface documentation and examples.
- Type-description and type-hash baseline.
- Cross-language acceptance evidence.
- Versioned release artifact consumable by downstream builds.

## 5. Architectural decisions

Create these ADRs during milestone M0:

| ADR | Decision |
| --- | --- |
| `ADR-0001-interface-package-boundaries.md` | Use four domain packages in one repository and release them in lockstep. |
| `ADR-0002-contract-evolution.md` | Use semantic versions, candidate releases, type-hash evidence, and expand–migrate–contract for breaking changes. |
| `ADR-0003-identifier-time-and-frame-rules.md` | Define stable IDs, UUID use, timestamps, validity deadlines, SI units, and coordinate-frame requirements. |
| `ADR-0004-bounded-interface-policy.md` | Bound variable-size strings and sequences based on realistic platform limits. |
| `ADR-0005-containerized-build-and-test.md` | Run all repository builds and tests in a pinned Jazzy/Cyclone DDS container and export results through a mounted workspace directory. |
| `ADR-0006-commit-and-release-convention.md` | Use Commitizen, Conventional Commits, lockstep package versions, generated changelogs, and protected release jobs. |

### 5.1 One repository, four packages

Use one repository because common changes usually require coordinated releases and compatibility review. Split it into packages so consumers only depend on the domains they use:

```text
platform_common_interfaces
    ├── platform_device_interfaces
    ├── platform_control_interfaces
    └── platform_episode_interfaces
```

Rules:

- The three domain packages may depend on `platform_common_interfaces`.
- The domain packages must not depend on one another.
- Runtime repositories may depend on one or more interface packages.
- No interface package may depend on a first-party runtime repository.
- All four packages use the same semantic version and Git tag.

### 5.2 Contract repository, not utility repository

Do not place ordinary Python or C++ helpers here. If consumers repeatedly need semantic validation beyond generated type constraints, put that behavior in a separate foundation library. This keeps language bindings free from unexpected runtime dependencies.

### 5.3 Standard ROS contracts first

Use standard ROS packages where their meaning matches:

- `builtin_interfaces/Time`
- `std_msgs/Header`
- `geometry_msgs/PoseStamped`
- `geometry_msgs/TwistStamped`
- `sensor_msgs/JointState`
- `trajectory_msgs/JointTrajectory`
- `unique_identifier_msgs/UUID`
- `diagnostic_msgs/DiagnosticStatus`
- `lifecycle_msgs` services and states

Do not wrap standard messages merely to rename them. Create a platform contract only when platform-specific identity, validity, ownership, provenance, or state semantics are required.

### 5.4 Container-only build and test contract

The repository does not require or support a native host ROS installation for normal development or CI. The host is an orchestration environment only.

Host tools:

- Docker Engine or Podman with Docker-compatible invocation.
- Git.
- Make or an equivalent task runner.

Container tools:

- Ubuntu 24.04.
- ROS 2 Jazzy.
- `rmw_cyclonedds_cpp`.
- Cyclone DDS runtime and an approved repository-local configuration.
- `colcon`, rosidl generators, CMake, compilers, test tools, Python fixtures, Commitizen, and report generators.

Rules:

- Pin the base image by immutable digest in release-impacting pipelines.
- Set `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` explicitly.
- Set a unique test `ROS_DOMAIN_ID`.
- Record the actual RMW identifier in the test evidence.
- Run communicating test processes inside one build/test container.
- Do not require host networking, privileged mode, a Docker socket mount, or hardware-device mounts.
- Mount repository source read-only when practical.
- Mount only the results directory read-write.
- Keep container caches separate from release evidence.
- Make local `make verify` and GitLab CI call the same container entry script.
- Return the container test exit code after writing the result summary.

The container is a development and verification artifact. It must not be included automatically in the customer installation bundle.

### 5.5 Commitizen and release-management contract

Use Commitizen with the Conventional Commits convention.

Developer workflow:

```text
make commit
    → run Commitizen inside the tooling container
    → create a Conventional Commit message
    → Git commit-msg hook validates the message
    → merge-request CI validates all commits in the branch
```

Commit examples:

```text
feat(control): add CartesianIntent interface
fix(common): correct ConfigurationReference bound
docs(device): clarify device identity rules
test(transport): cover Python to C++ service exchange
feat(control)!: replace command validity representation
```

Rules:

- `feat` represents an additive public capability and normally produces a minor version.
- `fix`, `perf`, or a compatible `refactor` normally produces a patch version.
- Breaking contract changes use `!` and a `BREAKING CHANGE:` footer.
- `docs`, `test`, `build`, `ci`, and `chore` do not claim an interface feature.
- A commit category does not override the type-hash compatibility classifier.
- Commitizen updates the one repository version and all four `package.xml` versions together.
- `cz bump --check-consistency` must succeed before a tag is created.
- Commitizen generates `CHANGELOG.md` as part of the protected release job.
- Release tags use `v${version}` and SemVer 2.
- While the project is below `v1.0.0`, the release policy must explicitly define how breaking changes affect `0.x` versions.
- Only a protected, manually approved release job may create the release commit and tag.
- Commitizen does not grant an AI agent or developer permission to commit, tag, push, or release without the authorization required by `AGENTS.md`.

## 6. Proposed repository layout

```text
platform-ros-interfaces/
├── AGENTS.md
├── README.md
├── REPO_CONTRACT.md
├── CHANGELOG.md
├── LICENSE
├── VERSION
├── .cz.toml
├── .pre-commit-config.yaml
├── .gitlab-ci.yml
├── .gitignore
├── Makefile
├── containers/
│   ├── Dockerfile.jazzy-cyclone
│   └── cyclonedds.xml
├── scripts/
│   ├── container-build.sh
│   ├── container-test.sh
│   ├── container-verify.sh
│   └── write-test-summary.py
├── platform_common_interfaces/
│   ├── CMakeLists.txt
│   ├── package.xml
│   └── msg/
├── platform_device_interfaces/
│   ├── CMakeLists.txt
│   ├── package.xml
│   ├── msg/
│   └── srv/
├── platform_control_interfaces/
│   ├── CMakeLists.txt
│   ├── package.xml
│   ├── msg/
│   └── srv/
├── platform_episode_interfaces/
│   ├── CMakeLists.txt
│   ├── package.xml
│   ├── msg/
│   ├── srv/
│   └── action/
├── docs/
│   ├── contracts/
│   ├── decisions/
│   └── plans/
├── examples/
│   ├── messages/
│   ├── services/
│   └── actions/
├── tests/
│   ├── cpp_roundtrip/
│   ├── python_roundtrip/
│   ├── transport/
│   ├── consumer_fixture/
│   └── type_hash_baseline/
├── artifacts/
│   └── .gitkeep
└── tools/
    ├── check_contract_catalog.py
    ├── compare_type_hashes.py
    └── render_interface_docs.py
```

The top level is a multi-package ROS repository. Full-system development imports it into the distribution workspace with the pinned source manifest.

## 7. Interface design rules

### 7.1 Naming

- Package names use lowercase snake case and end in `_interfaces`.
- Message, service, and action types use `UpperCamelCase`.
- Fields use lowercase snake case.
- Constants use uppercase snake case.
- Stable instance IDs are human-readable bounded strings.
- Event, command, episode, and request correlation IDs use UUIDs.
- Do not encode meaning in topic names that must also be present in recorded data.

### 7.2 Bounds

Variable-size fields must be bounded unless a written exception is approved.

Initial proposed limits:

| Data | Proposed bound |
| --- | ---: |
| Device, component, source, target, and binding IDs | 64 characters |
| Frame IDs | 128 characters |
| Semantic version | 32 characters |
| Git commit or content hash | 128 characters |
| Human summary | 256 characters |
| Detailed event message | 1024 characters |
| Joint names and joint values | 32 elements |
| Validation findings in a single summary message | 256 elements |

Confirm these values with consumers before freezing `v0.1.0`. Changing a bound changes the interface type.

### 7.3 Time

- Continuous sensor or state data includes `std_msgs/Header` when acquisition time and frame are meaningful.
- Commands include `issued_at` and `valid_until`.
- Events include an occurrence timestamp and may include a received timestamp in the recording layer.
- Zero or invalid deadlines are not assigned an implicit meaning; the message documentation must define them.
- Simulated workcells use ROS time consistently.
- The contract does not implement clock synchronization.

### 7.4 Frames and units

- Use SI units.
- Use REP-103 coordinate conventions.
- Every Cartesian command identifies its reference frame.
- A pose without a resolvable frame is invalid for control consumers.
- Joint arrays are aligned by `joint_names`, never by undocumented device order.
- Each numeric field documents units and valid range.

### 7.5 Semantics

- Every command identifies its source, target, command ID, ownership lease, and deadline where applicable.
- Raw teleoperator state remains independent of robot model.
- Safety status describes observable state; it does not contain policy implementation.
- Episode messages identify immutable raw recordings and derived processing operations separately.
- Do not add arbitrary key/value maps to avoid designing a contract.
- Do not include secrets, file contents, images, rosbags, or model weights in these contracts.

## 8. Initial interface catalog

The catalog is proposed. Owners of the first consumers must review field-level drafts before implementation.

### 8.1 `platform_common_interfaces`

| Type | Purpose | Planned phase |
| --- | --- | --- |
| `ComponentIdentity.msg` | Component ID, name, semantic version, source revision, and build identity. | M1 |
| `ConfigurationReference.msg` | Schema ID, schema version, configuration ID, and content hash. | M1 |
| `ProvenanceReference.msg` | References immutable build, source, configuration, and calibration provenance without repeating full manifests. | M1 |

Keep common types minimal. A type belongs here only when at least two domain packages require it.

### 8.2 `platform_device_interfaces`

| Type | Purpose | Planned phase |
| --- | --- | --- |
| `DeviceDescriptor.msg` | Stable instance ID, adapter type, model, role, namespace, capabilities, and component identity. | M1 |
| `DeviceState.msg` | Current lifecycle/availability state, connection status, last observation time, and diagnostic summary. | M1 |
| `DeviceStateArray.msg` | Snapshot of known device instances. | M1 |
| `CalibrationReference.msg` | Calibration ID, type, version, content hash, and relevant frames. | M1 |
| `ListDevices.srv` | Return descriptors and current states for discoverable registered devices. | M1 |
| `GetDeviceState.srv` | Return the state of one stable device ID. | M1 |

Use standard ROS lifecycle services to change lifecycle state. Do not invent a duplicate `ActivateDevice` service.

### 8.3 `platform_control_interfaces`

| Type | Purpose | Planned phase |
| --- | --- | --- |
| `TeleopState.msg` | Vendor-neutral pose, velocities, gripper input, clutch state, tracking validity, and source identity. | M2 |
| `CartesianIntent.msg` | Bounded Cartesian target or delta with frame, target robot, limits, lease, and validity deadline. | M2 |
| `JointIntent.msg` | Named joint targets with source, target, lease, and validity deadline. | M2 |
| `CommandLease.msg` | Lease identity, owner, follower target, issue time, and expiry. | M2 |
| `CommandLeaseStatus.msg` | Observable ownership state and reason for the latest transition. | M2 |
| `BindingDescriptor.msg` | Declarative relationship between source, mapper, solver, and target. | M2 |
| `BindingState.msg` | Current enabled, eligible, and ownership state for a binding. | M2 |
| `SafetyStatus.msg` | Current safety level, motion permission, limiting condition, and relevant references. | M2 |
| `SafetyEvent.msg` | Timestamped safety transition or rejection with severity and correlation IDs. | M2 |
| `CommandRejection.msg` | Rejected command identity and machine-readable rejection reason. | M2 |
| `AcquireCommandLease.srv` | Request exclusive command ownership for a target and bounded duration. | M2 |
| `ReleaseCommandLease.srv` | Relinquish an owned lease. | M2 |
| `SetActiveBinding.srv` | Request an enabled binding; arbitration remains in the control service. | M2 |

Streaming motion commands use topics. Lease acquisition is a short request/response operation and therefore uses a service. The interface package does not decide whether a request is granted.

### 8.4 `platform_episode_interfaces`

| Type | Purpose | Planned phase |
| --- | --- | --- |
| `EpisodeState.msg` | Episode identity and lifecycle state. | M3 |
| `EpisodeEvent.msg` | Timestamped operator, system, safety, or processing event associated with an episode. | M3 |
| `EpisodeMetadata.msg` | Workcell, task, recording, configuration, calibration, and component provenance references. | M3 |
| `ValidationFinding.msg` | Machine-readable rule, severity, time range, evidence reference, and disposition state. | M3 |
| `MarkEpisode.srv` | Record a short operator marker such as success, failure, or annotation. | M3 |
| `RecordEpisode.action` | Start a long-running recording, report status, support cancellation, and return the immutable raw artifact reference. | M3 |
| `ValidateEpisode.action` | Validate a recorded episode, stream progress, support cancellation, and return a summary. | M3 |

Defer `ExportDataset.action` until the data-export repository has proven the required format-independent semantics. Avoid prematurely coupling the foundation contract to LeRobot or Hugging Face.

## 9. Field-definition workflow

For each proposed type:

1. Identify at least one producer and one consumer.
2. Write the observable use case.
3. Check whether a standard ROS type already expresses it.
4. Define identity, timestamp, frame, units, bounds, optionality, and invalid-value behavior.
5. Write one valid and at least two invalid example payloads.
6. Review memory and transport cost for high-rate messages.
7. Review recording and replay behavior.
8. Review whether the type exposes vendor-specific details.
9. Generate C++ and Python bindings.
10. Add transport and compatibility acceptance coverage.
11. Obtain code-owner approval.

No interface should be merged solely because one producer wants a convenient field.

## 10. Compatibility and release policy

### 10.1 Lockstep semantic versions

All packages in this repository use the repository version:

```text
v0.1.0-rc.1
v0.1.0
v0.2.0
v1.0.0
```

Consumers pin a tag, package version, or immutable package artifact. They must not depend on an unpinned `main` branch.

### 10.2 Change classification

| Change | Version effect | Required work |
| --- | --- | --- |
| Comments, prose documentation, CI, or build fix with identical generated types | Patch | Regenerate and prove hashes unchanged. |
| New message/service/action that does not change existing generated types | Minor | Rebuild all consumers and update catalog. |
| New constants whose interpretation does not invalidate existing values | Minor | Consumer review and compatibility test. |
| Field addition, removal, rename, reordering, type change, or bound change | Breaking | Expand–migrate–contract and planned major version. |
| Semantic reinterpretation of an existing field | Breaking | New type or major version, migration ADR required. |
| Removal of a type | Breaking | Deprecation period and major version. |

ROS type hashes are evidence of structural identity; semantic compatibility still requires human review.

### 10.3 Expand–migrate–contract

For a breaking contract:

1. Add a new type, for example `CartesianIntentV2`, while retaining the original.
2. Publish a candidate release.
3. Update producers to emit the new form, optionally with a compatibility bridge.
4. Update and qualify all consumers.
5. Pin the integrated distribution to the compatible set.
6. Mark the old form deprecated with an explicit removal release.
7. Remove it only in the declared major version.

Do not edit the old type in place and expect separately deployed consumers to remain compatible.

### 10.4 Foundation-outward candidate propagation

```text
interface branch
    → vX.Y.Z-rc.N package
    → foundation service rebuilds
    → device/control/simulation rebuilds
    → data/AI/application rebuilds
    → distribution integration acceptance
    → final interface tag
    → final downstream pins
    → distribution release last
```

The interface repository triggers candidate pipelines for known consumers. A downstream failure blocks final promotion but does not cause an unreviewed automatic modification of that consumer.

## 11. CI/CD plan

Reuse the versioned ROS 2 `ament_cmake` component from:

```text
engineering/ci/platform-ci-components
```

The initial pipeline stages are:

```text
validate
→ format-and-static-analysis
→ build
→ unit
→ component-acceptance
→ compatibility
→ security-and-license
→ sbom
→ package
→ candidate-publication
```

### 11.1 Container execution model

All pipeline jobs that inspect, build, test, package, or release ROS interfaces run inside the pinned build/test container. A native GitLab shell runner must not substitute its installed ROS packages.

The image starts from:

```dockerfile
FROM ros:jazzy-ros-base@sha256:<approved-digest>

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
       ros-jazzy-rmw-cyclonedds-cpp \
       python3-colcon-common-extensions \
    && rm -rf /var/lib/apt/lists/*

ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ENV CYCLONEDDS_URI=file:///opt/platform/cyclonedds.xml
```

The final implementation must pin every additional tool and dependency through the approved development-image build. The shortened example shows the required base and middleware choice, not the complete Dockerfile.

Local and CI entry point:

```text
make verify
    → build or pull the pinned Jazzy/Cyclone image
    → create a clean artifacts directory
    → mount repository source at /workspace/source
    → mount ./artifacts at /workspace/results
    → execute /opt/platform-ci/container-verify.sh
    → collect the container exit code
    → retain ./artifacts/interface-test-results.json
```

Required container environment:

```text
RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
CYCLONEDDS_URI=file:///opt/platform/cyclonedds.xml
ROS_DISTRO=jazzy
ROS_DOMAIN_ID=<isolated-test-domain>
RESULTS_DIR=/workspace/results
```

The verification entry script must:

1. Capture image digest, OS, architecture, ROS distribution, RMW identifier, compiler, Python, and Git commit.
2. Create an isolated workspace inside the container.
3. Copy or link the mounted source into the workspace.
4. Resolve only declared dependencies.
5. Build with `colcon`.
6. Run `colcon test`.
7. Run interface-specific acceptance tests.
8. Run `colcon test-result`.
9. Export reports to the mounted results directory.
10. Always write the final JSON summary, even when a build or test fails.
11. Exit with a non-zero status when any required stage fails.

### 11.2 Result artifact contract

Every local and CI verification run writes:

```text
artifacts/
├── interface-test-results.json
├── junit/
│   └── interface-tests.xml
├── colcon-test-result.txt
├── environment.json
├── type-hashes.json
├── compatibility-report.json
└── logs/
```

`interface-test-results.json` is the required top-level result file. It contains:

```json
{
  "schema_version": "1.0",
  "status": "passed",
  "git_commit": "<commit>",
  "container_image": "<image>@sha256:<digest>",
  "ros_distribution": "jazzy",
  "rmw_implementation": "rmw_cyclonedds_cpp",
  "started_at": "<RFC3339>",
  "finished_at": "<RFC3339>",
  "build": {"status": "passed"},
  "tests": {"status": "passed", "total": 0, "failed": 0},
  "acceptance": {"status": "passed"},
  "compatibility": {"status": "passed"},
  "report_paths": []
}
```

Rules:

- The `artifacts/` directory is ignored except for `.gitkeep`.
- A stale result file is removed before starting a new run.
- The summary uses an atomic temporary-file-to-final-file rename.
- A failed or interrupted run reports `failed` or `incomplete`; it must not leave an old `passed` result.
- GitLab publishes JUnit XML through `artifacts:reports:junit`.
- GitLab also publishes the complete `artifacts/` directory with `artifacts:when: always`.
- Release evidence records the result-file checksum.

### 11.3 Validate

- Validate `package.xml`, `CMakeLists.txt`, and package versions.
- Check the repository catalog matches files on disk.
- Check naming, bounds, dependency direction, and required documentation.
- Reject first-party runtime dependencies.
- Verify every public type has an owner, producer, consumer, and example.
- Run `cz check` over all commits introduced by the merge request.
- Verify `.cz.toml`, `VERSION`, and all four `package.xml` versions agree.
- Verify the selected image digest and Cyclone DDS configuration are approved.

### 11.4 Build

- Build from a clean ROS 2 Jazzy workspace inside the container using `colcon`.
- Generate all configured C, C++, and Python support.
- Build on AMD64 for every merge request.
- Add ARM64/Jetson-compatible package qualification before the first platform release.
- Do not use host-installed compilers, ROS packages, Python packages, or CMake modules.
- Write build status and log paths into `interface-test-results.json`.

### 11.5 Component acceptance

- Introspect each contract with `ros2 interface`.
- Run C++ to Python and Python to C++ round trips.
- Exercise one representative service.
- Exercise action goal, feedback, cancellation, and result.
- Exercise serialization limits.
- Build a minimal downstream consumer fixture.
- Assert that the active RMW identifier is `rmw_cyclonedds_cpp`.
- Write JUnit XML and the summarized acceptance result into the mounted results directory.

These tests validate the contracts and transport. They do not validate runtime arbitration, robot stopping, recording integrity, or hardware behavior.

### 11.6 Compatibility

- Generate ROS type-description JSON.
- Generate and archive type hashes.
- Compare the merge request against the latest released baseline.
- Classify additions, identical shapes, and breaking changes.
- Fail when the declared semantic version or migration record does not match the change.
- On candidate tags, trigger known downstream compatibility pipelines.

### 11.7 Security, license, and SBOM

- Secret scan the repository.
- Scan build dependencies and CI image.
- Generate an SPDX or CycloneDX SBOM for the release artifact.
- Record standard ROS dependencies and their licenses.
- Require human review when a dependency introduces unclear redistribution or copyleft obligations.

### 11.8 Commitizen release gate

Merge-request pipelines:

- Validate branch commits with `cz check --use-default-range` or the exact target-branch revision range.
- Reject malformed commit messages.
- Calculate the proposed next version without creating a commit or tag.
- Compare the proposed bump with the structural compatibility report.
- Reject a breaking type change represented only as `fix`, `docs`, or another non-breaking commit.

Protected release pipeline:

1. Fetch complete Git history and tags.
2. Require all containerized verification and downstream candidate jobs to pass.
3. Run Commitizen consistency checking.
4. Generate the version bump and changelog.
5. Update `.cz.toml`, `VERSION`, and all `package.xml` files in lockstep.
6. Create the release commit and annotated `v${version}` tag using the authorized release identity.
7. Build release artifacts from the tagged commit inside the pinned container.
8. Publish release evidence and trigger downstream pin updates.

The protected release job must be idempotent: if the intended tag already exists, it verifies the tag target and stops rather than creating a second release.

Proposed `.cz.toml` intent:

```toml
[tool.commitizen]
name = "cz_conventional_commits"
version_provider = "commitizen"
version = "0.1.0"
version_scheme = "semver2"
tag_format = "v${version}"
update_changelog_on_bump = true
major_version_zero = true
annotated_tag = true
version_files = [
  "VERSION",
  "platform_common_interfaces/package.xml",
  "platform_device_interfaces/package.xml",
  "platform_control_interfaces/package.xml",
  "platform_episode_interfaces/package.xml",
]
```

Validate the exact `version_files` replacement behavior in M0 before relying on automatic release writes.

### 11.9 Package

For `v0.1.0` publish:

- Immutable Git source tag.
- Source archive with checksums.
- Clean install-space archive for integration builds.
- Type-description and hash manifest.
- SBOM, license inventory, and acceptance report.
- Container-produced `interface-test-results.json` and its checksum.

Add Debian packages when the distribution installer is ready to consume an internal APT repository. Do not build a production container for this repository.

## 12. Acceptance specifications

The following are language-independent specifications. They describe the tests that must exist before `v0.1.0`; they are not all required before the first interface file is drafted.

### AT-01: Generate and introspect every public type

**Maturity:** Executable in the pinned ROS 2 Jazzy/Cyclone DDS container.

```text
TEST "Every catalogued contract generates and is introspectable"
GIVEN the approved ROS 2 Jazzy/Cyclone DDS container image
AND no ROS installation from the host is visible
AND a clean container-local ROS workspace
AND the repository is the only first-party source package
WHEN the workspace is built
THEN every package completes rosidl generation
AND C++ typesupport exists for every catalogued type
AND Python bindings exist for every catalogued type
AND "ros2 interface show <type>" succeeds for every catalogued type
AND the discovered types exactly match the committed contract catalog
ON FAILURE preserve build logs and the missing or unexpected type list
```

### AT-02: Cross-language message round trip

**Maturity:** Executable with mocks inside the pinned Cyclone DDS container.

```text
TEST "TeleopState survives a C++ to Python transport round trip"
GIVEN RMW_IMPLEMENTATION is rmw_cyclonedds_cpp
AND the runtime reports rmw_cyclonedds_cpp as the active RMW
AND one C++ publisher and one Python subscriber in an isolated ROS domain
AND a TeleopState fixture containing non-default values
WHEN the C++ process publishes the fixture
THEN the Python process receives one sample before 2 seconds
AND every scalar, bounded string, timestamp, frame, pose, velocity,
    button, gripper, and validity field equals the fixture
AND the test reports the selected RMW implementation
FINALLY stop both processes and verify no orphan ROS process remains
```

Repeat the direction from Python to C++.

### AT-03: Service representation round trip

**Maturity:** Executable with mocks.

```text
TEST "AcquireCommandLease carries request and response semantics"
GIVEN a mock service server that records the complete request
AND a client request with source, target, requested duration, and request UUID
WHEN the client calls AcquireCommandLease
THEN the server receives fields identical to the request
AND the server can return granted=false with a machine-readable reason
AND the client receives the same request UUID and reason before 2 seconds
AND no runtime lease arbitration policy is asserted by this test
FINALLY stop the mock server
```

### AT-04: Action goal, feedback, cancellation, and result

**Maturity:** Executable with mocks.

```text
TEST "RecordEpisode supports the complete ROS action lifecycle"
GIVEN a mock RecordEpisode action server
AND a valid goal containing episode identity and metadata references
WHEN a client sends the goal
THEN the goal fields arrive unchanged
AND the server can emit at least two progress feedback messages
WHEN the client requests cancellation
THEN the server observes the cancellation request
AND returns a canceled result with a partial-artifact disposition
AND the client correlates feedback and result to the original goal
FINALLY remove temporary test artifacts
```

### AT-05: Enforce declared bounds

**Maturity:** Executable during build and transport tests.

```text
TEST "Bounded fields reject oversized values"
FOR EACH bounded string or sequence in the contract catalog
GIVEN a value exactly at the documented bound
WHEN it is assigned, serialized, and deserialized
THEN the operation succeeds and preserves the value
GIVEN a value one element beyond the documented bound
WHEN assignment or serialization is attempted
THEN the operation fails observably
AND no truncated value is published
AND the failure identifies the type and field
```

### AT-06: Preserve type hashes in a patch release

**Maturity:** Executable in compatibility CI.

```text
TEST "Patch releases do not alter generated contract shapes"
GIVEN the approved type-description and type-hash manifest for vX.Y.Z
AND a proposed version vX.Y.(Z+1)
WHEN current type descriptions and hashes are generated
THEN every previously released type has the identical hash
AND any new public type causes the version classifier to reject patch level
AND the comparison report is stored as release evidence
```

### AT-07: Block an undeclared breaking change

**Maturity:** Executable in merge-request CI.

```text
TEST "A breaking contract edit requires a migration"
GIVEN a released message with a recorded type hash
AND a merge request changes a field name, order, type, or bound
WHEN compatibility CI compares the generated descriptions
THEN the change is classified as breaking
AND the pipeline fails if no major-version migration ADR is present
AND the report lists affected types and known downstream consumers
AND no candidate artifact is published
```

### AT-08: Keep the dependency graph acyclic

**Maturity:** Executable in validation CI.

```text
TEST "Interface packages have only approved dependency directions"
GIVEN package manifests and the approved package graph
WHEN the dependency graph is constructed
THEN platform_common_interfaces has no first-party package dependency
AND each domain package depends only on common and approved standard packages
AND no domain package depends on another domain package
AND no interface package depends on a runtime, driver, application, or distribution package
AND the graph contains no cycle
```

### AT-09: Rebuild the first downstream consumers

**Maturity:** Executable for candidate tags.

```text
TEST "A candidate interface release builds the first vertical slice"
GIVEN immutable candidate interface artifacts
AND pinned candidate branches for the device registry, Quest bridge,
    retargeting, command arbitrator, safety supervisor, and episode recorder
WHEN downstream pipelines resolve only the candidate artifacts
THEN all consumers compile
AND their interface-facing acceptance fixtures pass
AND the distribution mock-workcell launch uses one consistent interface version
AND results are returned to the candidate release pipeline
ON ANY FAILURE block final interface promotion and identify the consumer
```

### AT-10: Install the released package on a clean system image

**Maturity:** Executable before `v0.1.0`.

```text
TEST "Released interfaces are consumable by a clean ROS installation"
GIVEN a fresh container that represents supported Ubuntu and ROS 2 Jazzy
AND contains no repository build workspace or development cache
AND only the published interface artifact and declared dependencies
WHEN the artifact is installed
THEN a separate example package can find all selected interface packages
AND compile a C++ consumer
AND import a Python message module
AND introspect the installed types
AND no repository source checkout is required
AND the result is written to the mounted test-results workspace
```

### AT-11: Build and test only inside the approved container

**Maturity:** Executable in local development and every merge-request pipeline.

```text
TEST "The host does not provide ROS build or test dependencies"
GIVEN a host with Docker or Podman, Git, and Make
AND no host ROS 2 installation is required
AND the approved container image is available
WHEN the developer runs "make verify"
THEN the source is built inside the container
AND every test process runs inside the same container
AND host compilers, ROS packages, Python site-packages, and CMake modules are not used
AND the container exits with zero only when all required checks pass
FINALLY remove the temporary container and retain only mounted result artifacts
```

### AT-12: Always export an accurate result file

**Maturity:** Executable in the container entry-script test suite.

```text
TEST "Verification writes an accurate mounted result on success or failure"
GIVEN a host workspace with an empty writable artifacts directory
AND repository source mounted according to the container contract
WHEN the container verification succeeds
THEN artifacts/interface-test-results.json exists on the host
AND its status is "passed"
AND it records the Git commit, image digest, ROS distribution,
    active RMW, timestamps, stage results, and report paths
WHEN a controlled test fixture is changed to fail
THEN the container exits non-zero
AND artifacts/interface-test-results.json still exists on the host
AND its status is "failed"
AND it identifies the failed stage
AND no stale "passed" result survives
```

### AT-13: Reject a middleware other than Cyclone DDS

**Maturity:** Executable in every transport test job.

```text
TEST "Interface transport qualification uses Cyclone DDS"
GIVEN the approved Jazzy container and Cyclone DDS configuration
WHEN the transport test environment starts
THEN RMW_IMPLEMENTATION equals "rmw_cyclonedds_cpp"
AND the runtime RMW identifier equals "rmw_cyclonedds_cpp"
AND the identifier is recorded in environment.json and interface-test-results.json
WHEN either configured or active RMW differs
THEN transport tests stop before publishing test data
AND the final result reports a middleware-configuration failure
```

### AT-14: Enforce Commitizen commits and lockstep versions

**Maturity:** Executable in merge-request and protected release pipelines.

```text
TEST "Commit history and release versions follow the repository policy"
GIVEN a merge request with commits not present on the target branch
WHEN Commitizen checks the exact revision range
THEN every commit follows the configured Conventional Commit schema
AND an invalid commit message blocks the merge request
GIVEN an authorized protected release job
WHEN Commitizen calculates and applies the release bump
THEN .cz.toml, VERSION, and all four package.xml versions are identical
AND the proposed bump is compatible with the interface type-hash classification
AND CHANGELOG.md contains the release changes
AND the annotated tag is exactly "v<version>"
AND no unprotected job or ordinary merge request creates a release tag
```

## 13. First vertical slice

Do not implement the full catalog at once. The first useful slice supports this path:

```text
Quest bridge
→ TeleopState
→ retargeting
→ CartesianIntent
→ command arbitration and CommandLease
→ SafetyStatus and SafetyEvent
→ simulated SO-101 adapter
```

Implement first:

1. `ComponentIdentity.msg`
2. `ConfigurationReference.msg`
3. `DeviceDescriptor.msg`
4. `DeviceState.msg`
5. `TeleopState.msg`
6. `CartesianIntent.msg`
7. `JointIntent.msg`
8. `CommandLease.msg`
9. `CommandLeaseStatus.msg`
10. `SafetyStatus.msg`
11. `SafetyEvent.msg`
12. `AcquireCommandLease.srv`
13. `ReleaseCommandLease.srv`

The episode contracts follow after the control path can run through mock or Gazebo components.

## 14. Implementation milestones

### M0 — Repository contract and decisions

- [ ] Create the GitLab project under `foundation`.
- [x] Add the root `AGENTS.md`.
- [x] Add `README.md`, `REPO_CONTRACT.md`, `LICENSE`, `VERSION`, and `CHANGELOG.md`.
- [x] Create ADR-0001 through ADR-0006.
- [x] Add `CODEOWNERS` for interface and release review.
- [ ] Create the package skeleton and shared CI include.
- [x] Add the pinned `Dockerfile.jazzy-cyclone` and Cyclone DDS configuration.
- [x] Add `Makefile` targets for `image`, `build`, `test`, `verify`, and `commit`.
- [x] Add the container verification and result-summary scripts.
- [x] Add `.cz.toml` and the pinned commit-message hook.
- [x] Prove Commitizen updates all four `package.xml` files and `VERSION` consistently.
- [ ] Confirm the proposed Apache-2.0 license.

**Exit condition:** Repository boundaries and policies are approved, and an empty scaffold can build and export a passing result from the container before public types are frozen.

### M1 — Common and device contracts

- [x] Define field-level drafts and examples.
- [ ] Review with device-registry and two adapter owners.
- [x] Implement common and device packages.
- [x] Generate C++ and Python bindings.
- [x] Add introspection, dependency-graph, bounds, and round-trip acceptance tests.
- [x] Record initial type descriptions and hashes.

**Exit condition:** Two mock device instances with the same adapter type can be represented unambiguously.

### M2 — Control contracts

- [x] Define raw teleoperation, Cartesian, and joint intent semantics.
- [x] Define lease identity and status without implementing arbitration.
- [x] Define binding and safety observability.
- [ ] Review with Quest, SO-101, retargeting, MoveIt Servo, arbitration, and safety owners.
- [x] Implement representative message and service round trips.
- [ ] Benchmark serialized size and transport rate for high-rate messages.

**Exit condition:** The first Quest-to-Gazebo SO-101 consumer set builds against one candidate version.

### M3 — Episode contracts

- [x] Define episode identity and state values.
- [x] Define immutable raw artifact and provenance references.
- [x] Define validation finding semantics.
- [x] Implement recording and validation actions.
- [x] Exercise goal, feedback, cancellation, failure, and result paths.
- [ ] Review with recorder, validator, API, UI, exporter, and distribution owners.

**Exit condition:** A mock recording lifecycle is representable without embedding storage-provider behavior.

### M4 — Compatibility and evidence automation

- [x] Generate the complete contract catalog.
- [x] Generate type-description JSON and SHA-256 type hashes.
- [x] Implement version-aware comparison.
- [x] Add downstream consumer fixture.
- [ ] Add license inventory, SBOM, and scan report.
- [x] Export JUnit, environment, type-hash, compatibility, and JSON summary results through the mounted artifacts directory.
- [x] Test the result writer under successful, failed, and interrupted executions.
- [ ] Publish CI evidence as immutable job artifacts.

**Exit condition:** CI distinguishes identical, additive, and breaking changes and blocks an invalid release version.

### M5 — Candidate qualification

- [ ] Tag `v0.1.0-rc.1`.
- [ ] Publish candidate artifacts.
- [ ] Trigger the known downstream consumer matrix.
- [ ] Build the integrated mock/Gazebo workspace.
- [ ] Resolve all field-semantics and compatibility findings.
- [ ] Repeat with later release candidates if generated types change.

**Exit condition:** Every required downstream repository pins and passes the same release candidate.

### M6 — Initial release

- [ ] Freeze hashes and catalog.
- [ ] Generate changelog and migration statement.
- [ ] Generate checksums, SBOM, license inventory, acceptance report, and provenance.
- [ ] Use the manually approved Commitizen release job to create the release commit, changelog, and annotated `v0.1.0` tag.
- [ ] Build the release artifact from the tagged commit in the pinned Jazzy/Cyclone DDS container.
- [ ] Update downstream pins from candidate to final.
- [ ] Update the distribution manifest last.
- [ ] Regenerate the public GitHub monorepo only after the GitLab release is complete.

**Exit condition:** A fresh supported system image can install the artifact and build C++ and Python consumers, while the repository itself remains reproducibly buildable and testable without a host ROS installation.

## 15. Dependencies

### Upstream build and standard interface dependencies

Expected initial dependencies:

- `ament_cmake`
- `rosidl_default_generators`
- `rosidl_default_runtime`
- `builtin_interfaces`
- `std_msgs`
- `geometry_msgs`
- `sensor_msgs`
- `trajectory_msgs`
- `unique_identifier_msgs`
- `diagnostic_msgs`
- `lifecycle_msgs`

Add only the dependencies actually used by an interface. Record versions through the pinned ROS distribution and build image rather than adding language package managers unnecessarily.

### Development-only dependencies

- Docker Engine or Podman on the host.
- Make and Git on the host.
- A digest-pinned ROS 2 Jazzy base image.
- `ros-jazzy-rmw-cyclonedds-cpp`.
- `colcon`
- `ament_lint_auto`
- `ament_lint_common`
- `pytest` for Python transport fixtures
- C++ test framework supplied by the ROS build environment
- `ruff` only for repository-owned Python tools and fixtures
- Commitizen with a pinned version.
- A pinned commit-message hook runner.
- SBOM, secret, dependency, and license scanners supplied by shared CI

Except for Docker or Podman, Git, and Make, development-only tools are installed and executed inside the build/test container.

### Downstream consumers for the first candidate matrix

- Device registry.
- Quest bridge.
- SO-101 adapter.
- Retargeting.
- Command arbitrator.
- Safety supervisor.
- MoveIt Servo integration.
- Episode recorder.
- Platform API.
- Distribution integration workspace.

## 16. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Too many speculative types before a working vertical slice | Implement M1 and M2 first; defer exporter and AI-specific contracts. |
| Duplicate or incompatible standard ROS semantics | Require a standard-message review in every interface proposal. |
| Unbounded messages create unpredictable allocation and latency | Require explicit bounds and boundary acceptance tests. |
| A structural hash remains unchanged while meaning changes | Require semantic review, examples, changelog, and code-owner approval. |
| One interface edit breaks many repositories | Candidate releases, known-consumer matrix, and distribution-last promotion. |
| Package dependencies become cyclic | Enforce the approved graph in CI. |
| High-rate contracts carry excessive provenance | Use compact immutable references and publish full manifests separately. |
| Vendor-specific fields leak into shared contracts | Keep vendor details in adapter-private topics or configuration schemas. |
| Consumers mix interface versions in one workspace | Pin one repository version through the distribution manifest and reject duplicates. |
| Generated bindings are assumed to behave equally | Test C++ and Python in both transport directions. |
| A mutable container tag changes build behavior | Pin release-impacting images by digest and record that digest in every result. |
| A developer's host ROS installation hides missing dependencies | Run all builds and tests inside the container with no host ROS paths. |
| A failed container run leaves a stale passing report | Delete stale output first and atomically write a final success, failure, or incomplete result. |
| Cyclone DDS is configured but another RMW is active | Check the environment and runtime RMW identifier before transport tests. |
| Commitizen version files drift from ROS package versions | Run consistency checks in merge-request and protected release jobs. |
| Conventional Commit type disagrees with contract compatibility | Make the type-hash classifier authoritative and fail the proposed release. |

## 17. Verification checklist

- [ ] Container image builds from the approved digest.
- [x] Container reports ROS 2 Jazzy.
- [x] Container reports `rmw_cyclonedds_cpp`.
- [x] `make verify` requires no host ROS installation.
- [x] Source and result mounts follow the read-only/read-write contract.
- [x] Success writes a passing `interface-test-results.json`.
- [x] Failure writes a failing `interface-test-results.json` and exits non-zero.
- [ ] GitLab ingests the JUnit result and retains artifacts on failure.
- [x] Static package and manifest checks.
- [x] Clean Jazzy build.
- [x] C++ generated bindings.
- [x] Python generated bindings.
- [x] Interface introspection.
- [x] Bounds acceptance.
- [x] C++ to Python message round trip.
- [x] Python to C++ message round trip.
- [x] Service request and response round trip.
- [x] Action goal, feedback, cancellation, and result.
- [x] Type-description and hash generation.
- [ ] Compatibility baseline comparison.
- [x] Dependency graph validation.
- [ ] Downstream candidate build matrix.
- [ ] AMD64 package installation.
- [ ] ARM64 package qualification.
- [x] License inventory.
- [ ] Secret and dependency scans.
- [x] SBOM and release evidence.
- [x] Commitizen merge-request revision-range check.
- [x] Commitizen lockstep version consistency.
- [x] Commitizen dry-run bump agrees with compatibility classification.
- [ ] Protected release job creates the expected annotated tag and changelog.

No real robot and no host/bare-metal ROS installation are required to qualify the interface repository.

## 18. Current status

**Last completed step:** The local M0–M4 implementation is complete: all 29
catalogued contracts generate C, C++, and Python support in the pinned Jazzy
container; transport, service, action, bounds, consumer, compatibility, and
result-writer checks pass with Cyclone DDS. The passing local evidence is under
`artifacts/`.

**Current step:** Obtain owner review, provision the protected CI image/project
settings, and qualify the first release candidate against downstream consumers.

**Blockers:** External approval or infrastructure is required for:

- Package names and boundaries.
- Initial catalog and field bounds.
- Proposed Apache-2.0 license.
- First candidate consumer matrix.
- Approval of the pinned Jazzy base-image digest and Cyclone DDS configuration.
- Conventional Commit scopes and the pre-`v1.0.0` breaking-change policy.
- Publication of or adaptation to the shared `ros2-ament-cmake` CI component;
  its current workspace/rosdep execution contract does not call the required
  mounted-result container entry point.
- Protected `CI_INTERFACE_TOOLING_IMAGE`, tag rules, and downstream pipeline
  trigger credentials in GitLab.

**Exact next step:** Review the field-level catalog and bounds with the named
producer/consumer owners, publish the approved tooling image by immutable
digest, then run the protected `v0.1.0-rc.1` candidate matrix.

## 19. Handoff notes

- This document is a plan; no ROS package has been generated or tested yet.
- The catalog deliberately excludes AI-provider, LeRobot, Quest, SO-101, and storage-provider-specific types.
- Lease and safety messages describe inputs and observable results. Their algorithms remain in control repositories.
- Type hashes should be treated as structural evidence, not as proof of semantic compatibility.
- The plan interprets the host requirement as no native/bare-metal ROS build or test environment; only Docker or Podman, Git, and Make are required on the host.
- The repository uses a development/CI container but publishes no production runtime container.
- The main test handoff is `artifacts/interface-test-results.json`, supported by JUnit, logs, environment, and compatibility evidence.
- Commitizen automates commit-message validation, version calculation, version-file updates, tags, and changelog generation only inside the authorized workflow.
- The distribution repository must remain the final pin and integration gate.

## 20. Primary references

- [ROS 2 Jazzy: Topics, services, and actions](https://docs.ros.org/en/jazzy/How-To-Guides/Topics-Services-Actions.html)
- [ROS 2 Jazzy: About interfaces](https://docs.ros.org/en/jazzy/Concepts/Basic/About-Interfaces.html)
- [ROS 2 Jazzy: Type description generator and type hashes](https://docs.ros.org/en/ros2_packages/jazzy/api/rosidl_generator_type_description/__README.html)
- [ROS 2 tutorial: Creating an interface package](https://docs.ros.org/en/foxy/Tutorials/Beginner-Client-Libraries/Single-Package-Define-And-Use-Interface.html)
- [ROS 2 Jazzy: `diagnostic_msgs`](https://docs.ros.org/en/jazzy/p/diagnostic_msgs/)
- [ROS 2 Jazzy: RMW implementations](https://docs.ros.org/en/jazzy/Installation/RMW-Implementations.html)
- [Commitizen: Checking commit messages](https://commitizen-tools.github.io/commitizen/commands/check/)
- [Commitizen: Version bumping and consistency checking](https://commitizen-tools.github.io/commitizen/commands/bump/)
- [Commitizen: Changelog generation](https://commitizen-tools.github.io/commitizen/commands/changelog/)
- [GitLab: CI/CD artifact report types](https://docs.gitlab.com/ci/yaml/artifacts_reports/)
