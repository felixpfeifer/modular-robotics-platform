#!/bin/bash
source /opt/platform/install/setup.bash
source /app/install/setup.bash
case "${RMW:-zenoh}" in
  zenoh) export RMW_IMPLEMENTATION=rmw_zenoh_cpp ;;
  cyclonedds) export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ;;
  fastdds) export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ;;
esac
ros2 node list --no-daemon | grep -q controller_manager
