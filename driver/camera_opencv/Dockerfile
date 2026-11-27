# Build context: the directory that holds camera_opencv/ and mrp_camera_common/
# (the driver workspace locally, .image-context in CI; see docker-compose.yaml).
ARG BASE_IMAGE=docker.io/felixpfeifer/mrp-ros-base:latest

FROM ${BASE_IMAGE} AS build
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
# libopencv-dev -> OpenCV headers/libs for find_package(OpenCV)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopencv-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY mrp_camera_common /app/src/mrp_camera_common
COPY camera_opencv/CMakeLists.txt camera_opencv/package.xml /app/src/camera_opencv/
COPY camera_opencv/include /app/src/camera_opencv/include
COPY camera_opencv/src /app/src/camera_opencv/src
COPY camera_opencv/tools /app/src/camera_opencv/tools
RUN source /opt/platform/install/setup.bash \
    && colcon build --base-paths src --cmake-args -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release

FROM ${BASE_IMAGE}
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
# Runtime only: the OpenCV libraries the node links, and python3-opencv for
# tools/camera_probe.py (the MRP backend runs it to test a device).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopencv-core406t64 \
    libopencv-imgcodecs406t64 \
    libopencv-videoio406t64 \
    python3-opencv \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /app/install /app/install
COPY camera_opencv/tools /tools
RUN for package in git git-man; do if dpkg -s "$package" >/dev/null 2>&1; then apt-get purge -y "$package" || exit 1; fi; done && ! command -v git

# The node touches this file while frames flow; the healthcheck checks its age.
ENV MRP_CAMERA_HEARTBEAT_FILE=/tmp/mrp-camera-heartbeat
# exec, no `ros2 run` wrapper: SIGTERM from `docker stop` reaches the node directly.
# "$@" forwards any compose `command:` (e.g. --ros-args -p video_device:=...) to the node.
ENTRYPOINT ["/bin/bash", "-c", "source /opt/platform/install/setup.bash && source /app/install/setup.bash && exec /app/install/camera_opencv/lib/camera_opencv/camera_node \"$@\"", "--"]
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD ["/bin/sh", "-c", "f=$MRP_CAMERA_HEARTBEAT_FILE; [ -f \"$f\" ] && [ $(( $(date +%s) - $(stat -c %Y \"$f\") )) -lt 15 ]"]
