#!/bin/bash
set -e

source /opt/platform/install/setup.bash
source /ws/install/setup.bash

case "${RMW:-zenoh}" in
  cyclonedds) export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ;;
  fastdds) export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ;;
  zenoh) export RMW_IMPLEMENTATION=rmw_zenoh_cpp ;;
  *) echo "Unsupported RMW '${RMW}'; use cyclonedds, fastdds, or zenoh" >&2; exit 2 ;;
esac

exec "$@"