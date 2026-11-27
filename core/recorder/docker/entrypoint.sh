#!/bin/bash
# Usage: entrypoint.sh [launch-arg:=value ...] | <command...>
# Launch arguments start the recorder; any other command runs unchanged in the
# same ROS environment (for example the standalone command bridge).
set -eo pipefail
source /opt/platform/install/setup.bash
source /ws/install/setup.bash

case "${RMW:-zenoh}" in
  zenoh)      export RMW_IMPLEMENTATION=rmw_zenoh_cpp ;;
  cyclonedds) export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ;;
  *) echo "Unsupported RMW '${RMW}'; use zenoh or cyclonedds" >&2; exit 2 ;;
esac

if [ $# -eq 0 ] || [[ "$1" == *:=* ]]; then
  exec ros2 launch episode_recorder recorder.launch.py "$@"
fi
exec "$@"
