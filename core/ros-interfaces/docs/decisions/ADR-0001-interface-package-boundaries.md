# ADR-0001: Interface package boundaries

- Status: Accepted
- Date: 2026-07-23

## Context

Platform consumers need coordinated contracts without taking dependencies on
domains they do not use.

## Decision

Keep four ROS packages in one repository and release them in lockstep:
`platform_common_interfaces`, `platform_device_interfaces`,
`platform_control_interfaces`, and `platform_episode_interfaces`.

The three domain packages may depend on common. Common has no first-party
dependency, domain packages do not depend on one another, and no interface
package depends on a first-party runtime repository.

## Consequences

Cross-domain changes have one version and release gate. Consumers can still
depend on only the generated packages they need. CI enforces the graph.
