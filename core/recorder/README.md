# Production VLA Episode Recorder

Records immutable, UUID-addressed ROS 2 Jazzy episodes as one MCAP per episode,
validates their training quality, and exports only accepted recordings to
LeRobot Dataset v3.

## Lifecycle

```text
preflight -> .staging/<uuid> -> close/hash -> episodes/<uuid>
                                            -> validate -> accepted/rejected
```

Raw MCAP is authoritative. `status.json` controls training eligibility; rejected
episodes are never repaired with padded, truncated, zero-filled, future, or
stale data.

Public endpoints:

| Name | Type |
|---|---|
| `/platform/episode/record` | `platform_episode_interfaces/action/RecordEpisode` |
| `/platform/episode/validate` | `platform_episode_interfaces/action/ValidateEpisode` |
| `/platform/episode/mark` | `platform_episode_interfaces/srv/MarkEpisode` |
| `/platform/episode/state` | `platform_episode_interfaces/msg/EpisodeState` |
| `/platform/episode/events` | `platform_episode_interfaces/msg/EpisodeEvent` |
| `/platform/control/joint_intent` | `platform_control_interfaces/msg/JointIntent` |

The recorder is robot-agnostic. The initial `so101_vla_rgb_30_v1` deployment
requires 640×480 JPEG RGB at 30 FPS and a named/timestamped six-joint intent,
but those details are resolved from configuration rather than compiled into the
recorder, validator, or exporter.

Configuration is split by ownership:

| File | Owns |
|---|---|
| `config/robots/so101.yaml` | state/action topics, ordered joints, units, limits, controller groups |
| `config/cameras/top_rgb_30.yaml` | camera name/topic/type, dimensions, encoding, rate, quality thresholds |
| `config/recording_profiles.yaml` | robot/camera composition and episode-level quality rules |
| `config/workspaces/local_so101.yaml` | deployed profile, task, storage, calibration and producer provenance |

To add a UR arm, define its joint set and usually one `joint_trajectory_topic`
group. For a humanoid, partition all configured joints across multiple
trajectory groups. Every joint must appear in exactly one command group. Add
one camera YAML per observation camera, reference them from a new recording
profile, then select that profile in a workspace file. No recorder code change
is required. A profile's hash covers the resolved robot and all camera files,
so edits cannot silently reuse old validation results.

## Run locally

From this workspace, with camera and robot topics already running:

```bash
docker compose up --build episode_recorder
```

The default launch loads `config/workspaces/local_so101.yaml`. Select another
deployment with:

```bash
ros2 launch episode_recorder recorder.launch.py \
  workspace_config:=/absolute/path/to/my_workspace.yaml
```

Before recording, replace the example calibration digest in the workspace file
with the SHA-256 of the active immutable calibration artifact.
Preflight rejects placeholder hashes, missing provenance, stale streams, a
camera outside its configured rate tolerance, or less than the configured free
storage reserve.

Keyboard controls:

| Key | Action |
|---|---|
| `Space` / `s` | Start after preflight |
| `y` | Mark success and finalize |
| `n` | Mark failure and finalize |
| `a` | Add an operator annotation |
| `q` / `Esc` | Cancel, retain rejected partial, quit |

After rejection, inspect `validation/validation.json` and explicitly start a
replacement. There is no automatic robot retry.

## Validation evidence and metrics

Camera freeze detection compares each frame to the first frame of the current
unchanged interval. A mean absolute pixel difference of at least 0.5 (over all
channels) starts a new interval; more than one second without that cumulative
change while robot state or action changes is rejected. This catches a static
frame while permitting small visible changes that accumulate over time.

Each finalized directory contains its bag, `manifest.json`, `status.json`,
`validation/validation.json`, and `validation/validation.junit.xml`. The
validator exposes low-cardinality Prometheus text at
`http://127.0.0.1:9108/metrics` by default.

Rejected artifacts are retained for 14 days. Cleanup is a dry-run unless
`--delete` is supplied:

```bash
ros2 run episode_recorder cleanup.py --dataset-dir /data/datasets/teleop
ros2 run episode_recorder cleanup.py --dataset-dir /data/datasets/teleop --delete
```

## Export accepted episodes

Create an explicit immutable selection:

```bash
ros2 run episode_recorder build_accepted_manifest.py \
  --dataset-dir /data/datasets/teleop \
  --output /data/datasets/accepted.json
```

Then use the converter container, which is locked to `lerobot==0.6.1` by
`uv.lock`:

```bash
docker compose run --rm convert \
  --workspace-config /app/config/workspaces/local_so101.yaml \
  --dataset-dir /data/datasets/teleop \
  --accepted-manifest /data/datasets/accepted.json \
  --output-dir /data/lerobot/teleop \
  --repo-id organization/teleop
```

The converter also accepts `--downsample-hz-ratio N`, keeping every Nth valid
camera tick in each recording. For example, `2` converts a 30 FPS
recording to 15 FPS. The resulting frame rate must be a positive integer; the
default is `1`. The application exposes the same setting as Frame stride on the
dataset page. Each export is a separate dataset, so variants can coexist.

The slowest configured camera supplies the export timestamps (the configured
`timeline_camera` breaks ties). At each timestamp, the exporter takes the nearest
robot state within the configured maximum skew, the latest unexpired action that
was already issued, and the nearest image from every camera within half that
camera's nominal frame period. Other high-rate samples are discarded. An image
that is missing, undecodable, incorrectly sized, or blank/unusable causes that
tick to be dropped. Blank/unusable means grayscale standard deviation below 2,
mean at most 5, or mean at least 250 on the 0–255 scale.

Like the external pipeline, the exporter assigns evenly spaced playback timestamps
at the configured FPS to available frames. It does not repeat missing images or
preserve the duration of camera slowdowns and gaps: those intervals are compressed
in playback and training. The original camera timestamps remain in
`observation.source_timestamp_ns`, and `meta/source_episodes.json` maps each output
episode back to its original MCAP episode. Validation still enforces the other recording
and safety rules; image decode, blank-frame, rate, coverage, and gap findings
are warnings. The exporter finalizes, reopens, and iterates the dataset before
returning success.

## Optional Hugging Face upload

Export stays local. Upload is a separate, explicit operation and accepts only a
complete LeRobot Dataset v3.0 directory. The destination is private by default;
an existing repository must have matching visibility. The command requires an
acknowledgement flag before making any Hub request. Public visibility requires
an additional acknowledgement.

Authenticate on the host with `hf auth login`, or supply `HF_TOKEN` through the
environment using `docker compose run -e HF_TOKEN upload ...`. Do not put tokens in command arguments, compose files, shell
history, or source control. The upload container mounts the Hugging Face
credential cache read-only and the dataset volume read-only.

```bash
docker compose run --rm upload \
  --dataset-dir /data/lerobot/teleop \
  --repo-id YOUR_HF_NAMESPACE/teleop \
  --confirm-upload
```

Only if public release is intended, add `--visibility public --confirm-public`
alongside `--confirm-upload`. The upload CLI checks `meta/info.json` for
`codebase_version: v3.0`, episode metadata, parquet data, and symlinks, then
opens the directory with the pinned `lerobot==0.6.1` reader and reads every
frame, including video decoding, before connecting. On success it prints JSON
with the Hub commit revision, visibility, episode count, and frame count. It
never runs as part of recording or export. `make export-test` includes an
end-to-end local mock export and offline tests with a mocked Hub client; it does
not upload anything.

## Build and verification

The repository pins platform interfaces in `dependencies.repos`.

```bash
make test
make integration
make export-test
make verify
```

`make hil` requires `MRP_HIL=1`, `HIL_ESTOP_CONFIRMED=1`, and a non-placeholder
`HIL_CALIBRATION_HASH`. It is reserved for the tagged SO-101/RealSense runner.
GitLab publishes GTest/Pytest and per-rule JUnit evidence on every pipeline.

Legacy `ep_N` SQLite bags are not training eligible. Convert them explicitly
with the migration command, which assigns a UUID, converts to MCAP, and invokes
the current validator without imputing missing data:

```bash
ros2 run episode_recorder migrate_legacy.py \
  --legacy-bag /path/to/ep_N \
  --dataset-dir /data/datasets/teleop \
  --recording-profiles /path/to/recording_profiles.yaml \
  --task-catalog /path/to/task_catalog.yaml \
  --profile-id so101_vla_rgb_30_v1 \
  --task-id default_demo \
  --configuration-hash sha256:<recording-configuration-sha256> \
  --calibration-id so101-calibration \
  --calibration-hash sha256:<real-calibration-sha256> \
  --producer-revision <immutable-source-revision>
```

Missing real gripper actions or other required streams remain hard failures.
