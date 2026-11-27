# ADR-0003: Identifier, time, and frame rules

- Status: Accepted
- Date: 2026-07-23

## Decision

- Stable component, device, source, target, binding, and artifact IDs are
  bounded human-readable strings. They are stable across process restarts.
- Events, commands, lease requests, and episode runs use UUIDs for correlation.
- State and observations use `std_msgs/Header` when acquisition time or frame is
  meaningful.
- Commands carry `issued_at` and `valid_until`. A zero `valid_until` is invalid;
  no implicit "forever" meaning exists.
- Events carry their occurrence timestamp.
- Durations use `builtin_interfaces/Duration`.
- Numeric physical values use SI units and REP-103 conventions.
- Cartesian contracts identify a resolvable reference frame. An empty frame is
  invalid.
- Joint arrays align exclusively by `joint_names`; undocumented device order is
  invalid.

## Consequences

Clock synchronization and frame resolution remain runtime responsibilities.
Recordings retain sufficient identity, timing, and frame data for replay.
