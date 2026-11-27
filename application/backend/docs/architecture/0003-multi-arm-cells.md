# ADR 0003: Cells with several arms and any number of cameras

Status: accepted. Mock arms are verified end to end in a live cell. Real arms are covered by
the agent gating tests only.

## Context

The workspace layout (Cell page) lets users place any number of arms and cameras. The cell
that actually ran had a fixed shape:

- one `leader`, one `follower`;
- a `camera` and an optional `camera2`;
- one bridge.

The recorder (`core/recorder`) records exactly one robot: one joint-state topic and one action
topic. It already records any number of cameras.

## Decision

### Spec

A cell spec may list its components. In the UI these lists come from the layout modules.

| Key | Entry |
| --- | --- |
| `arms` | `id`, `role` (leader/follower), `backend` (mock/real), `model`, optional `name`, `module`, `device` (real only), and for followers `leader` and `joint_mapping` |
| `cameras` | `id`, `source` (synthetic/opencv_usb), `width`, `height`, `fps`, optional `name`, `module`, `device` |

The original single-pair keys still work, and either list can be used alone.

Limits:

- 1–4 leaders and 1–4 followers.
- 1–6 cameras. The recorder needs at least one.

Pairing rules:

- Every follower names its leader. One leader may drive several followers.
- A real follower needs a real leader.

The lists stand for the single-pair keys: any real arm of a role makes that role `real`.
Preset matching and gating are therefore unchanged. `components.expand` turns both forms into
the same arm and camera lists. `components.topology` adds Compose services, namespaces and
topics.

### Runtime

**One leader and one follower keep the original wiring.** Services, topics, the bridge
config and the recording profile are unchanged. Existing recordings stay compatible.

**Cameras:**

- Camera *i* publishes `/<id>/image/compressed` and is recorded as `observation.images.<id>`.
- Cameras 1 and 2 use the base `camera`/`camera2` services, with the topic set via
  `CAMERA_TOPIC`/`CAMERA2_TOPIC`.
- Further cameras become generated `camera_<id>` services.

**More than one leader or follower:**

- Every arm runs in namespace `arm_<id>`. The first of each role uses the base service; the
  others become `arm_<id>`.
- The **arm adapter** (`deployment/mock-cell/arm_adapter.py`, logic in `arm_merge.py`) does
  three things:
  - merges follower states into `/joint_states` and leader states into
    `/leader/joint_states`, with joints prefixed by the arm id (`left_shoulder_pan_joint`);
  - publishes on the first arm's clock and stops if any arm is silent for 0.5 s;
  - splits the arbiter's combined `JointIntent` into one intent per follower on
    `/platform/control/arms/<id>/joint_intent`. A combined intent that doesn't name exactly
    the followers' joints is rejected as a whole.
- **Control:** one teleop source and one arbiter run over the combined joints. Each follower
  joint follows the same-named joint of *its* leader unless its `joint_mapping` says
  otherwise. The handover gate, timeouts and the `none`/`teleop`/`policy` switch therefore
  cover all arms at once.
- **Bridges:** one per follower (`bridge`, `bridge_<id>`), each with a generated robot config.
  These keep the recorder's joints and limits, but use namespaced topics and controllers and
  their own `target_id`.
- **Recording:** the recorder records the combined robot (`robots/cell.yaml`,
  profile `<mode>_<robot>_cell_v1`). A LeRobot export of two SO-101 followers therefore has a
  12-dimensional state and action. Episodes with different arm or camera sets use different
  contracts, and the exporter refuses to mix them.
- **Mock motion:** one instance runs per mock leader, tracking that leader's first follower.

### Deployment safety

- The agent rebuilds the spec from the request and re-validates it against the preset. It
  renders the extra services into a Compose overlay (`$MRP_AGENT_STATE_DIR/<project>.cell.json`).
- `check_plan` accepts only the extra services the agent announced, only with cell-component
  names. Every arm service must have the expected backend, and the preset bounds what each
  backend may be.
- Each real arm gets exactly its own serial device and calibration file. The connection test
  covers every real arm, camera and leader/follower pair. Starting still needs a fresh passing
  test and the operator's confirmation.
- `up` and `down` pass `--remove-orphans`. After a cell shrinks, no container from the larger
  cell (possibly a real arm) keeps running.

### Calibration

A real arm uses `<role>.yaml` when it is the only arm of its role, and `<id>.yaml` otherwise.
The wizard and the driver's `so101_probe.py calibrate --name` write that file. Recording
provenance hashes every real arm's file.

## Consequences

- The C++ recorder, exporter, arbiter, teleop source and bridge are unchanged; everything new
  is generated configuration plus the adapter.
- Policies trained on a combined robot expect all of its arms. Whether the policy deployment
  path rejects a mismatched arm set has not been checked yet.
- The Gazebo preset still simulates one follower and one rendered camera.
- Not yet verified: a live recording and export of a multi-arm episode, and real multi-arm
  hardware.
