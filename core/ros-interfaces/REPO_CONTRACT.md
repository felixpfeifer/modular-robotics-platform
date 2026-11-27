# Repository contract

## Responsibility

Own stable, vendor-neutral ROS 2 data contracts shared by two or more platform
repositories.

## Non-responsibilities

This repository does not:

- encode a single vendor SDK object model;
- publish or subscribe to topics in production;
- open hardware, network, file, or database resources;
- decide whether a command is safe or authorized;
- embed configuration documents as arbitrary JSON or YAML strings;
- duplicate a suitable standard ROS message; or
- depend on a first-party runtime package.

Acceptance fixtures may create short-lived mock publishers, subscribers,
service servers, and action servers solely to qualify generated contracts.

## Inputs

- Approved architecture decisions.
- Accepted domain requirements from producer and consumer owners.
- Standard ROS message definitions.
- Version and compatibility policy.
- Bounded size and timing requirements.

## Outputs

- Generated, introspectable ROS 2 types.
- A stable, acyclic package dependency graph.
- Interface documentation and valid/invalid examples.
- Type-description and type-hash baselines.
- Cross-language acceptance evidence.
- A versioned release artifact consumable by downstream builds.

## Change gate

A public type is eligible for review only when the contract catalog names an
owner, at least one producer, at least one consumer, all units and invalid-value
rules, and one valid plus two invalid examples. Structural hashes are evidence
of shape identity; they do not replace semantic review.
