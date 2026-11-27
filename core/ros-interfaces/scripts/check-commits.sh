#!/usr/bin/env bash
set -Eeuo pipefail

if [[ -n "${CI_MERGE_REQUEST_DIFF_BASE_SHA:-}" ]]; then
  revision_range="${CI_MERGE_REQUEST_DIFF_BASE_SHA}..${CI_COMMIT_SHA}"
  cz check --rev-range "${revision_range}"
elif git describe --tags --abbrev=0 >/dev/null 2>&1; then
  cz check --use-default-range
else
  printf 'No tag or merge-request base is available; skipping historical commit validation.\n'
fi

set +e
cz bump --dry-run --check-consistency --yes
bump_status=$?
set -e
# Commitizen uses 21 for a consistent tree with no bump-eligible commits.
if [[ ${bump_status} -ne 0 && ${bump_status} -ne 21 ]]; then
  exit "${bump_status}"
fi
