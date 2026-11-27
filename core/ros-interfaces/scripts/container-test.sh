#!/usr/bin/env bash
set -Eeuo pipefail

WORK_DIR="${WORK_DIR:-/workspace/work}"
RESULTS_DIR="${RESULTS_DIR:-/workspace/results}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROS_WORKSPACE="${WORK_DIR}/ros_ws"

if [[ ! -f "${ROS_WORKSPACE}/install/setup.bash" ]]; then
  bash "${SCRIPT_DIR}/container-build.sh"
fi

cd "${ROS_WORKSPACE}"
set +u
source install/setup.bash
set -u
colcon test --merge-install --event-handlers console_direct+
colcon test-result --all --verbose | tee "${RESULTS_DIR}/colcon-test-result.txt"

mkdir -p "${RESULTS_DIR}/junit"
while IFS= read -r -d '' result; do
  package_name="$(basename "$(dirname "${result}")")"
  mkdir -p "${RESULTS_DIR}/junit/${package_name}"
  cp "${result}" "${RESULTS_DIR}/junit/${package_name}/$(basename "${result}")"
done < <(find "${ROS_WORKSPACE}/build" -path '*/test_results/*/*.xml' -print0)

if ! find "${RESULTS_DIR}/junit" -name '*.xml' -print -quit | grep -q .; then
  echo "No JUnit XML was exported to ${RESULTS_DIR}/junit" >&2
  exit 1
fi
