# Build context: the directory that holds camera_realsense/ and mrp_camera_common/
# (the driver workspace locally, .image-context in CI; see docker-compose.yaml).
ARG BASE_IMAGE=docker.io/felixpfeifer/mrp-ros-base:latest

FROM ${BASE_IMAGE} AS build
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
# ros-jazzy-librealsense2 -> RealSense SDK (RSUSB backend: no kernel patches,
#                            works on amd64 and arm64/Jetson)
# libopencv-dev           -> JPEG/PNG encoding
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopencv-dev \
    ros-jazzy-librealsense2 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY mrp_camera_common /app/src/mrp_camera_common
COPY camera_realsense/CMakeLists.txt camera_realsense/package.xml /app/src/camera_realsense/
COPY camera_realsense/include /app/src/camera_realsense/include
COPY camera_realsense/src /app/src/camera_realsense/src
RUN source /opt/platform/install/setup.bash \
    && colcon build --base-paths src --cmake-args -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release

FROM ${BASE_IMAGE}
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopencv-core406t64 \
    libopencv-imgcodecs406t64 \
    ros-jazzy-librealsense2 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /app/install /app/install
RUN for package in git git-man; do if dpkg -s "$package" >/dev/null 2>&1; then apt-get purge -y "$package" || exit 1; fi; done && ! command -v git

# The node touches this file while frames flow; the healthcheck checks its age.
ENV MRP_CAMERA_HEARTBEAT_FILE=/tmp/mrp-camera-heartbeat
# exec, no `ros2 run` wrapper: SIGTERM from `docker stop` reaches the node directly.
# "$@" forwards any compose `command:` (e.g. --ros-args -p enable_depth:=true) to the node.
ENTRYPOINT ["/bin/bash", "-c", "source /opt/platform/install/setup.bash && source /app/install/setup.bash && exec /app/install/camera_realsense/lib/camera_realsense/camera_node \"$@\"", "--"]
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD ["/bin/sh", "-c", "f=$MRP_CAMERA_HEARTBEAT_FILE; [ -f \"$f\" ] && [ $(( $(date +%s) - $(stat -c %Y \"$f\") )) -lt 15 ]"]
