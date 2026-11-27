#!/usr/bin/env bash
set -euo pipefail

test "${MRP_HIL:-}" = "1"
test "${HIL_ESTOP_CONFIRMED:-}" = "1"

hil_dataset="${HIL_DATASET_DIR:-$PWD/hil-data}"
hil_artifacts="${HIL_ARTIFACT_DIR:-$PWD/hil-artifacts}"
hil_workspace="${HIL_WORKSPACE_CONFIG:-}"
mkdir -p "$hil_dataset" "$hil_artifacts"

launch_args=(dataset_dir:="$hil_dataset")
qualification_args=()
if test -n "$hil_workspace"; then
  launch_args+=(workspace_config:="$hil_workspace")
  qualification_args+=(--workspace-config "$hil_workspace")
fi

ros2 launch episode_recorder recorder.launch.py "${launch_args[@]}" \
  >"$hil_artifacts/recorder.log" 2>&1 &
recorder_pid=$!
cleanup() {
  kill "$recorder_pid" 2>/dev/null || true
  wait "$recorder_pid" 2>/dev/null || true
}
trap cleanup EXIT

ros2 run episode_recorder hil_qualification.py \
  --dataset-dir "$hil_dataset" \
  --artifact-dir "$hil_artifacts" \
  "${qualification_args[@]}"
