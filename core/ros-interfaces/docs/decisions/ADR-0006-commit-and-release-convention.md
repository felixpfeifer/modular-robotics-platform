# ADR-0006: Commit and release convention

- Status: Accepted
- Date: 2026-07-23

## Decision

Use Commitizen with Conventional Commits. All packages, `.cz.toml`, and
`VERSION` share one SemVer value. `feat` normally requests a minor bump;
`fix`, `perf`, and compatible `refactor` request a patch; breaking changes use
`!` and a `BREAKING CHANGE:` footer.

Merge-request CI validates the exact target range and performs a dry-run bump.
The structural compatibility report may require a stronger bump than commit
categories imply.

Only a protected, manually approved release job may update versions and the
changelog, create the release commit, or create the annotated `v${version}` tag.
The job verifies an existing tag target and is idempotent.

## Consequences

Automation provides consistency, not authorization. Humans still approve
contract meaning and release promotion.
