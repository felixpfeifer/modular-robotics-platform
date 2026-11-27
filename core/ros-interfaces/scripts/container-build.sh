#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_DIR="${SOURCE_DIR:-/workspace/source}"
WORK_DIR="${WORK_DIR:-/workspace/work}"
ROS_WORKSPACE="${WORK_DIR}/ros_ws"

rm -rf "${ROS_WORKSPACE}"
mkdir -p "${ROS_WORKSPACE}/src/platform_ros_interfaces"
cp -a "${SOURCE_DIR}/." "${ROS_WORKSPACE}/src/platform_ros_interfaces/"
rm -rf "${ROS_WORKSPACE}/src/platform_ros_interfaces/artifacts"

cd "${ROS_WORKSPACE}"
colcon build \
  --merge-install \
  --event-handlers console_direct+ \
  --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo
