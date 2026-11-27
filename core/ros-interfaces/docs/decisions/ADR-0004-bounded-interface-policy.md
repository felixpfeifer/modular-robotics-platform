# ADR-0004: Bounded interface policy

- Status: Accepted
- Date: 2026-07-23

## Decision

All variable-size strings and sequences are bounded. Initial limits are:

| Value | Bound |
| --- | ---: |
| Stable IDs and type labels | 64 characters |
| Frame IDs, revisions, hashes, URIs, evidence references | 128 characters |
| Semantic versions | 32 characters |
| Human summaries | 256 characters |
| Detailed event text | 1024 characters |
| Joint names and values | 32 elements |
| Capabilities and related references | 32 elements |
| Devices, events, and validation findings per response | 256 elements |

An exception requires an ADR with a memory/transport analysis. A bound change is
a structural breaking change.

## Consequences

Serialization cost is predictable and oversize data fails rather than silently
truncating. Bulk content remains outside ROS interface messages.
