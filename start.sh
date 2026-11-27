#!/usr/bin/env bash
# Start the MRP application (web UI + deployment agent) with one command.
# Idempotent: safe to re-run. Pulls images, or builds them if pulling fails.
#   ./start.sh            start (pull images, build if unavailable)
#   ./start.sh down       stop the application (keeps data)
#   WITH_USB_CAMERA=1 ./start.sh   also prepare the USB camera image
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
export MRP_WORKSPACE_ROOT="$PWD"
app=(docker compose -f application/backend/compose.dev.yaml)

if [ "${1:-}" = down ]; then
  "${app[@]}" down
  exit 0
fi

command -v docker >/dev/null || { echo "Docker is required." >&2; exit 1; }
[ -e driver/robot_so101/src/ros2_so_arm ] && [ -n "$(ls -A driver/robot_so101/src/ros2_so_arm 2>/dev/null)" ] ||
  echo "Warning: driver submodules look empty; run: git submodule update --init --recursive" >&2

# The training volume is declared external by the application stack.
docker volume inspect mrp-training_runs >/dev/null 2>&1 || docker volume create mrp-training_runs >/dev/null

# Pull each image independently so an unavailable image can be built from source.
pull_or_build() {
  local image=$1
  local remote="docker.io/felixpfeifer/${image%%:*}:latest"
  shift
  if docker pull "$remote"; then
    docker tag "$remote" "$image"
    echo "Using $remote as $image"
  else
    echo "Could not pull $remote; building $image from source." >&2
    "$@"
  fi
}

pull_or_build mrp-robot-so101 docker build -t mrp-robot-so101 driver/robot_so101
pull_or_build mrp-episode-recorder docker build -t mrp-episode-recorder -f core/recorder/Dockerfile core
pull_or_build mrp-episode-converter docker compose -f application/backend/deployment/mock-cell/compose.yaml \
  -f application/backend/deployment/cell.compose.yaml --profile tools build convert
pull_or_build mrp-ai-lerobot:dev docker build -t mrp-ai-lerobot:dev core/ai_lerobot
pull_or_build mrp-control-arbiter docker compose -f core/control_arbiter/docker-compose.yaml build
if [ "${WITH_USB_CAMERA:-0}" = 1 ]; then
  pull_or_build mrp-camera-opencv docker build -t mrp-camera-opencv driver/camera_opencv
fi

pull_or_build mrp-app:dev "${app[@]}" build app
pull_or_build mrp-frontend:dev "${app[@]}" build frontend
pull_or_build mrp-app-agent:dev "${app[@]}" build agent
"${app[@]}" up -d --no-build
echo
echo "MRP UI:  http://127.0.0.1:5173   (API/docs: http://127.0.0.1:8088/docs)"
echo "Stop with ./start.sh down"
