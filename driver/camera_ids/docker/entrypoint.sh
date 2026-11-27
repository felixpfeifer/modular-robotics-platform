#!/usr/bin/env bash
# Start the uEye daemons inside the container, then the ROS node.
# The daemons upload the camera firmware (USB) and discover GigE uEye cameras;
# the uEye API talks to them, so they must run next to the node. Do not also run
# them on the host for the same cameras.
#   IDS_USB=1 (default)  start ueyeusbd for USB cameras
#   IDS_ETH=1            start ueyeethd for GigE uEye cameras (needs network_mode: host)
set -eo pipefail

find_daemon() {
  command -v "$1" 2>/dev/null || find /usr /opt -type f -name "$1" -perm -u+x -print -quit 2>/dev/null
}

start_daemon() {
  local bin
  bin=$(find_daemon "$1")
  if [[ -z $bin ]]; then
    echo "camera_ids: $1 not found in the image; $2 cameras will not be detected" >&2
    return
  fi
  echo "camera_ids: starting $bin"
  # The daemons fork into the background; `&` also covers a foreground variant.
  "$bin" &
}

[[ ${IDS_USB:-1} == 1 ]] && start_daemon ueyeusbd USB
[[ ${IDS_ETH:-0} == 1 ]] && start_daemon ueyeethd GigE

source /opt/platform/install/setup.bash
source /app/install/setup.bash
# "$@" forwards the compose `command:` (e.g. --ros-args -p serial_number:=...) to the node.
exec /app/install/camera_ids/lib/camera_ids/camera_node "$@"
