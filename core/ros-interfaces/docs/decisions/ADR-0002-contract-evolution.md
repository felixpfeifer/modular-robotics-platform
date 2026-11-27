# ADR-0002: Contract evolution

- Status: Accepted
- Date: 2026-07-23

## Context

Separately deployed ROS producers and consumers require structural and semantic
compatibility. Generated type hashes detect shape changes but not meaning
changes.

## Decision

Use lockstep Semantic Versioning, candidate releases, committed type-hash
baselines, and downstream qualification. Existing fields, ordering, types, and
bounds are immutable within a major compatibility line.

Breaking changes use expand–migrate–contract: add a versioned replacement type,
qualify producers and consumers, deprecate the old type, and remove it only in
the declared breaking release.

Before `1.0.0`, compatible additions increment the minor version, compatible
fixes increment the patch version, and a breaking removal or in-place change
increments the minor version while being treated operationally as a major
release: it requires `!`, a `BREAKING CHANGE:` footer, a migration ADR, and
candidate qualification. Versioned replacement types remain preferred.

## Consequences

Hash comparison is authoritative for structural classification. Human review
remains authoritative for semantics. Release automation rejects a version bump
that understates either classification.
