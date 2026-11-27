#!/bin/bash
# Usage: entrypoint.sh arm | rviz | zenoh-router | <command...>
set -eo pipefail
source /opt/platform/install/setup.bash
source /app/install/setup.bash

case "${RMW:-zenoh}" in
  zenoh)      export RMW_IMPLEMENTATION=rmw_zenoh_cpp ;;
  cyclonedds) export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ;;
  fastdds)    export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ;;
  *) echo "Unknown RMW '${RMW}' (use zenoh, cyclonedds or fastdds)" >&2; exit 2 ;;
esac

ns="${NAMESPACE:-}"; ns="${ns#/}"; ns="${ns%/}"

case "${1:-arm}" in
  arm)
    args=(role:="${ROLE:?ROLE is required}" backend:="${BACKEND:-mock}"
          usb_port:="${USB_PORT:-/dev/ttyACM0}" gazebo_gui:="${GAZEBO_GUI:-false}")
    # ros2 launch rejects empty values, so optional arguments are only added when set.
    [ -n "$ns" ] && args+=(namespace:="$ns")
    [ -n "${CALIBRATION_FILE:-}" ] && args+=(calibration_file:="$CALIBRATION_FILE")
    exec ros2 launch so101_bringup arm.launch.py "${args[@]}"
    ;;
  rviz)
    prefix="${ns:+$ns/}"
    config=/tmp/arm.rviz
    sed -e "s|@DESCRIPTION_TOPIC@|/${prefix}robot_description|" \
        -e "s|@TF_PREFIX@|${ns}|" \
        -e "s|@FIXED_FRAME@|${prefix}base_link|" \
        "$(ros2 pkg prefix --share so101_bringup)/rviz/arm.rviz.in" > "$config"
    sim=false; [ "${BACKEND:-mock}" = gazebo ] && sim=true
    exec rviz2 -d "$config" --ros-args -p use_sim_time:=$sim -r "/clock:=/${prefix}clock"
    ;;
  zenoh-router)
    exec ros2 run rmw_zenoh_cpp rmw_zenohd
    ;;
  *) exec "$@" ;;
esac
