#!/usr/bin/env bash
# Checks one MRP camera driver, or mrp_camera_common itself, inside the MRP ROS base
# image. Run it from the repository root of the package under test:
#
#   <path to mrp_camera_common>/ci/driver-check.sh PACKAGE [extra apt packages...]
#
# Steps: shared lint configs are identical, clang-format, build with warnings as
# errors, unit tests, clang-tidy on everything that was compiled, then the tests
# again under AddressSanitizer + UndefinedBehaviorSanitizer.
# Generated directories: build/ install/ log/ test-log/ build-asan/ install-asan/.
set -Eeuo pipefail

package=${1:?usage: driver-check.sh PACKAGE [apt packages...]}
shift
common=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
repo=$(pwd)

step() { printf '\n==> %s\n' "$*"; }
# ROS setup scripts read unset variables.
ros_source() {
  set +u
  # shellcheck disable=SC1090
  source "$1"
  set -u
}

step "Installing tools and dependencies"
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  clang-format clang-tidy libopencv-dev python3-colcon-common-extensions \
  ros-jazzy-ament-cmake-gtest ros-jazzy-rmw-fastrtps-cpp "$@" >/dev/null

if [[ $repo != "$common" ]]; then
  step "Lint configs match mrp_camera_common"
  for config in .clang-format .clang-tidy test/.clang-tidy; do
    cmp "$config" "$common/$config" ||
      { echo "$config differs from mrp_camera_common/$config; copy it over." >&2; exit 1; }
  done
fi

step "clang-format"
dirs=()
for dir in src include test; do [[ -d $dir ]] && dirs+=("$dir"); done
find "${dirs[@]}" -type f \( -name '*.cpp' -o -name '*.hpp' \) -print0 |
  xargs -0 -r clang-format --dry-run --Werror

ros_source /opt/platform/install/setup.bash
paths=("$repo")
[[ $repo != "$common" ]] && paths+=("$common")
build() { # build BASE INSTALL BUILD_TYPE [cmake args...]
  local base=$1 install=$2 type=$3
  shift 3
  colcon --log-base log build --base-paths "${paths[@]}" --build-base "$base" \
    --install-base "$install" --packages-up-to "$package" --event-handlers console_cohesion+ \
    --cmake-args "-DCMAKE_BUILD_TYPE=$type" -DMRP_WARNINGS_AS_ERRORS=ON "$@"
}
run_tests() { # run_tests BASE INSTALL
  colcon --log-base test-log test --base-paths "${paths[@]}" --build-base "$1" \
    --install-base "$2" --packages-select "$package" --event-handlers console_cohesion+
  colcon test-result --test-result-base "$1/$package" --verbose
}

step "Build (warnings are errors)"
build build install RelWithDebInfo -DCMAKE_EXPORT_COMPILE_COMMANDS=ON

step "Unit tests"
(
  ros_source install/setup.bash
  run_tests build install
)

step "clang-tidy"
mapfile -t sources < <(python3 - "build/$package/compile_commands.json" "$repo" <<'PY'
import json, os, sys
entries = json.load(open(sys.argv[1]))
repo = os.path.realpath(sys.argv[2])
files = {os.path.realpath(e["file"]) for e in entries}
print("\n".join(sorted(f for f in files if f.startswith(repo + os.sep))))
PY
)
if ((${#sources[@]})); then
  clang-tidy -p "build/$package" --quiet "${sources[@]}"
fi

step "Unit tests under AddressSanitizer + UndefinedBehaviorSanitizer"
build build-asan install-asan Debug \
  "-DCMAKE_CXX_FLAGS=-fsanitize=address,undefined -fno-sanitize-recover=undefined -fno-omit-frame-pointer"
(
  ros_source install-asan/setup.bash
  # Leak checking is off: rclcpp and the RMW keep process-lifetime singletons.
  export ASAN_OPTIONS=detect_leaks=0:abort_on_error=1 UBSAN_OPTIONS=print_stacktrace=1
  run_tests build-asan install-asan
)

step "$package: all checks passed"
