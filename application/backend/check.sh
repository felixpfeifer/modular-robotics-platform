#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

export PYTHONPATH="$PWD/backend${PYTHONPATH:+:$PYTHONPATH}"
uv lock --check
for requirements in requirements.txt requirements-media.txt; do
    extras=()
    if [[ "$requirements" == requirements-media.txt ]]; then
        extras=(--extra media)
    fi
    exported=$(uv export --locked --no-dev --no-hashes --quiet "${extras[@]}" | sed '/^#/d')
    diff -u <(sed '/^#/d' "$requirements") <(printf '%s\n' "$exported")
done
uv run --locked ruff check backend deployment tests
uv run --locked ruff format --check backend deployment tests
MYPYPATH=backend:deployment uv run --locked mypy --follow-imports=silent --disallow-untyped-defs \
    backend/mrp_app/api_boundary.py backend/mrp_app/recording.py backend/mrp_app/jobs.py \
    deployment/cell_plan.py deployment/device_checks.py
uv run --locked python -m compileall -q backend deployment
uv run --locked python tests/run.py
