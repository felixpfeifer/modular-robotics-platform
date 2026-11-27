#!/bin/bash
set -euo pipefail

source /opt/platform/install/setup.bash
source /ws/install/setup.bash
ros2 node list | grep -Fxq /control_arbiter