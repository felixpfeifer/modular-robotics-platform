# ADR 0002: Leader and follower arm interface

Status: accepted. The interface exists. SO-101 is the only available model. Meta Quest 3,
Universal Robots, FANUC and the Trossen arms are catalogued as `planned`.

## Context

The cell spec chose only a backend per arm role (`leader`/`follower`: `mock`, `gazebo`, `real`),
and SO-101 was implied everywhere. Supporting other leaders and followers needs a stable answer
to two questions that do not depend on any particular driver image:

1. What does a device in each role expose?
2. Given a leader and a follower, how does one drive the other?

## Decision

`backend/mrp_app/arms.py` (`mrp-arm-interface/v1`) describes every arm **model** by its
capabilities, independently of the **backend**:

| Cell spec key | Meaning | Default |
| --- | --- | --- |
| `leader`, `follower` | backend: `mock`, `gazebo`, `real` | unchanged |
| `leader_model`, `follower_model` | model id from `GET /api/v1/catalog` → `arms.models` | `so101` |

Older saved cells carry no model keys and keep meaning SO-101. No migration is needed.

Each model declares:

- `roles`: whether it can be a `leader`, a `follower`, or both.
- `backends` per role.
- `connection`: `usb_serial` (available), `ethernet` or `wifi_xr` (both planned). This defines
  what `devices.<role>` will hold.
- `leader_output`: `joint_state` (`sensor_msgs/JointState` on the profile's leader topic) or
  `cartesian_pose` (`geometry_msgs/PoseStamped` on `/leader/pose`, plus gripper and deadman topics).
- `command_interfaces`: what a follower accepts from the control arbiter, `joint`
  (`platform_control_interfaces/JointIntent`) and/or `cartesian` (`CartesianIntent`, planned).
- `kinematics`: a family id. Joint-space teleop only maps between arms of the same family.
- `robot_profile`: the `driver/*/profile.json` id. It is required before a model can become available.
- `safety`: the prerequisites the cell must enforce, taken from `arms.SAFETY`.

The leader-to-follower path is derived from these capabilities alone. It mirrors
`platform_control_interfaces/BindingDescriptor` (source → mapper → solver → target):

| Leader output | Follower accepts | Mapper | Solver | Command |
| --- | --- | --- | --- | --- |
| joint, same kinematics | joint | `joint_mapping` (available) | `none` | joint |
| joint, other kinematics | any | unsupported | | |
| cartesian pose | cartesian | `pose_retarget` (planned) | `none` | cartesian (planned) |
| cartesian pose | joint only | `pose_retarget` (planned) | `ik` (planned) | joint |

The catalog publishes the derived binding for every pair (`arms.bindings`). Validation rejects
a cell when:

- a model is unknown, planned, or in the wrong role;
- a model lacks the chosen backend;
- a real backend uses a connection that is not available;
- the binding is not fully available;
- no deployment preset lists exactly those models (`PRESETS[*].models`).

The UI lists planned models disabled and shows their note.

## Making a planned model available

The application side is a catalog change. The heavy lifting is the driver image. Do these in order:

1. **Driver image** (in its own `driver/<name>` repository): publish the leader output and/or
   consume the command interface above, and report joint states on the profile's `joint_states`
   topic. Expose controller faults and stops as the `safety` list requires.
2. **Robot profile**: ship `driver/<name>/profile.json` (`robot-profile/v1`) with joint names,
   topics and recorder config. Then set `robot_profile` on the model.
3. **Connection**: for `ethernet`/`wifi_xr`, add `devices.<role>` validation in `catalog.py`.
   Add a connection test in the deployment agent, then flip the connection to `available`.
4. **Missing chain steps**: implement the pose retargeting mapper, IK solver or Cartesian
   intent in the control arbiter if the pairing needs them, then flip them to `available`.
5. **Preset**: add a preset to the agent and a row in `catalog.PRESETS` with `models`,
   `match`, `hardware` and the tasks. Add the services to `deployment.PRESET_SERVICES` and
   `ALLOWED_BACKENDS`.
6. Set the model's `status` to `available`. Keep the existing operator confirmation and
   handover gate.
7. Promote through simulation first, then an explicitly authorised hardware test.

## Consequences

- Core recording, datasets and the arbiter contract stay robot-agnostic. Only the catalog
  and presets know which models exist.
- Joint mapping between different kinematic families (for example an SO-101 leader driving
  a UR arm) is intentionally unsupported. Use a pose leader such as the Quest instead.
- The per-model notes for UR, FANUC and Trossen describe the expected integration path
  only. They do not claim a driver, package or controller option has been chosen or verified.
