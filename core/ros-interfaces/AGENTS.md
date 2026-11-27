# Repository instructions

These instructions apply to the entire repository.

- Keep this repository limited to ROS interface definitions, contract
  documentation, compatibility tooling, and acceptance fixtures.
- Do not add production ROS nodes, drivers, policies, hardware access,
  deployment logic, or ordinary utility libraries.
- Keep all four ROS packages on the exact version in `VERSION`.
- Domain packages may depend on `platform_common_interfaces`; they must not
  depend on one another or on first-party runtime packages.
- Bound every variable-size string and sequence unless an ADR documents an
  approved exception.
- Update `docs/contracts/catalog.json` and examples with every public interface.
- Treat field additions, removals, renames, reordering, type changes, and bound
  changes as breaking. Use expand–migrate–contract.
- Run `make verify` before requesting review. Do not rely on a host ROS
  installation.
- Use Conventional Commits. Do not commit, tag, push, publish, or release unless
  the user explicitly authorizes that action.
- Preserve generated evidence only in `artifacts/`; do not commit run output.
