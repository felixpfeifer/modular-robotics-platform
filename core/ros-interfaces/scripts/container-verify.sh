#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_DIR="${SOURCE_DIR:-/workspace/source}"
RESULTS_DIR="${RESULTS_DIR:-/workspace/results}"
WORK_DIR="${WORK_DIR:-/workspace/work}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERIFY_MODE="${VERIFY_MODE:-verify}"
STARTED_AT="$(date --utc +%Y-%m-%dT%H:%M:%SZ)"
STAGE_FILE="${WORK_DIR}/stage-results.json"
CURRENT_STAGE="initialization"
FINAL_STATUS="incomplete"

mkdir -p "${RESULTS_DIR}" "${RESULTS_DIR}/logs" "${WORK_DIR}"
rm -f \
  "${RESULTS_DIR}/interface-test-results.json" \
  "${RESULTS_DIR}/interface-test-results.json.tmp" \
  "${RESULTS_DIR}/environment.json" \
  "${RESULTS_DIR}/environment.json.tmp"
printf '{}\n' > "${STAGE_FILE}"

finish() {
  exit_code=$?
  trap - EXIT
  if [[ ${exit_code} -eq 0 ]]; then
    FINAL_STATUS="passed"
    CURRENT_STAGE=""
  elif [[ "${FINAL_STATUS}" != "incomplete" ]]; then
    FINAL_STATUS="failed"
  fi
  python3 "${SOURCE_DIR}/tools/write_test_summary.py" \
    --results-dir "${RESULTS_DIR}" \
    --source-dir "${SOURCE_DIR}" \
    --status "${FINAL_STATUS}" \
    --failed-stage "${CURRENT_STAGE}" \
    --started-at "${STARTED_AT}" \
    --stage-file "${STAGE_FILE}" || true
  if [[ -f "${RESULTS_DIR}/interface-test-results.json" ]]; then
    (
      cd "${RESULTS_DIR}"
      sha256sum interface-test-results.json > interface-test-results.sha256
    ) || true
  fi
  exit "${exit_code}"
}
trap finish EXIT
trap 'FINAL_STATUS=incomplete; exit 130' INT TERM

record_stage() {
  python3 "${SOURCE_DIR}/tools/update_stage_result.py" \
    "${STAGE_FILE}" "$1" "$2"
}

run_stage() {
  stage="$1"
  shift
  CURRENT_STAGE="${stage}"
  if "$@" > >(tee "${RESULTS_DIR}/logs/${stage}.log") 2>&1; then
    record_stage "${stage}" passed
  else
    record_stage "${stage}" failed
    FINAL_STATUS="failed"
    return 1
  fi
}

check_environment() {
  [[ "${ROS_DISTRO:-}" == "jazzy" ]] || return 1
  [[ "${RMW_IMPLEMENTATION:-}" == "rmw_cyclonedds_cpp" ]] || return 1
  active_rmw="$(
    python3 -c \
      'from rclpy.impl.implementation_singleton import rclpy_implementation as r; print(r.rclpy_get_rmw_implementation_identifier())'
  )" || return 1
  [[ "${active_rmw}" == "rmw_cyclonedds_cpp" ]] || return 1
  {
    uname -a
    g++ --version | head -n 1
    python3 --version
    ros2 --version 2>/dev/null || true
    printf 'active_rmw=%s\n' "${active_rmw}"
  }
}

validate_repository() {
  python3 "${SOURCE_DIR}/tools/check_contract_catalog.py" &&
  python3 -m unittest discover -s "${SOURCE_DIR}/tests/unit" -v &&
  python3 "${SOURCE_DIR}/tools/render_interface_docs.py" \
    --output "${RESULTS_DIR}/contract-catalog.md"
}

acceptance() {
  set +u
  source "${WORK_DIR}/ros_ws/install/setup.bash"
  set -u
  python3 - "${SOURCE_DIR}/docs/contracts/catalog.json" <<'PY'
import json
import subprocess
import sys

for entry in json.load(open(sys.argv[1], encoding="utf-8"))["contracts"]:
    subprocess.run(["ros2", "interface", "show", entry["type"]], check=True,
                   stdout=subprocess.DEVNULL)
PY
  python3 "${SOURCE_DIR}/tools/generate_type_hashes.py" \
    --require-ros \
    --install-prefix "${WORK_DIR}/ros_ws/install" \
    --descriptions-output "${RESULTS_DIR}/type-descriptions.json" \
    --output "${RESULTS_DIR}/type-hashes.json"
}

compatibility() {
  baseline="${SOURCE_DIR}/tests/type_hash_baseline/v0.1.0.json"
  arguments=(
    --current "${RESULTS_DIR}/type-hashes.json"
    --output "${RESULTS_DIR}/compatibility-report.json"
    --fail-on-breaking
  )
  if [[ -f "${baseline}" ]]; then
    arguments+=(--baseline "${baseline}")
  fi
  python3 "${SOURCE_DIR}/tools/compare_type_hashes.py" "${arguments[@]}"
}

evidence() {
  python3 "${SOURCE_DIR}/tools/generate_release_evidence.py" \
    --output-dir "${RESULTS_DIR}"
}

run_stage environment check_environment
run_stage validation validate_repository

if [[ "${VERIFY_MODE}" == "validate" ]]; then
  record_stage build not_run
  record_stage tests not_run
  record_stage acceptance not_run
  record_stage compatibility not_run
  exit 0
fi

run_stage build bash "${SCRIPT_DIR}/container-build.sh"
if [[ "${VERIFY_MODE}" == "build" ]]; then
  record_stage tests not_run
  record_stage acceptance not_run
  record_stage compatibility not_run
  exit 0
fi

run_stage tests bash "${SCRIPT_DIR}/container-test.sh"
run_stage acceptance acceptance
run_stage compatibility compatibility
run_stage evidence evidence
