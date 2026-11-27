# Build context: the directory that holds camera_genicam/ and mrp_camera_common/
# (the driver workspace locally, .image-context in CI; see docker-compose.yaml).
ARG BASE_IMAGE=docker.io/felixpfeifer/mrp-ros-base:latest

FROM ${BASE_IMAGE} AS build
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
# libaravis-dev    -> GenICam (GigE Vision + USB3 Vision) library, LGPL-2.1+, no vendor SDK
# libusb-1.0-0-dev -> aravis-0.8.pc requires it, but libaravis-dev does not depend on it
# libopencv-dev    -> Bayer/YUV conversion, resize and JPEG encoding
RUN apt-get update && apt-get install -y --no-install-recommends \
    libaravis-dev \
    libopencv-dev \
    libusb-1.0-0-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY mrp_camera_common /app/src/mrp_camera_common
COPY camera_genicam/CMakeLists.txt camera_genicam/package.xml /app/src/camera_genicam/
COPY camera_genicam/include /app/src/camera_genicam/include
COPY camera_genicam/src /app/src/camera_genicam/src
COPY camera_genicam/test /app/src/camera_genicam/test
RUN source /opt/platform/install/setup.bash \
    && colcon build --base-paths src --cmake-args -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release

FROM ${BASE_IMAGE}
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
# aravis-tools-cli -> arv-tool-0.8 to list cameras and features from inside the container
RUN apt-get update && apt-get install -y --no-install-recommends \
    aravis-tools-cli \
    libaravis-0.8-0 \
    libopencv-core406t64 \
    libopencv-imgcodecs406t64 \
    libopencv-imgproc406t64 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /app/install /app/install
RUN for package in git git-man; do if dpkg -s "$package" >/dev/null 2>&1; then apt-get purge -y "$package" || exit 1; fi; done && ! command -v git

# The node touches this file while frames flow; the healthcheck checks its age.
ENV MRP_CAMERA_HEARTBEAT_FILE=/tmp/mrp-camera-heartbeat
# "$@" forwards the compose `command:` (e.g. --ros-args -p serial_number:=...) to the node.
ENTRYPOINT ["/bin/bash", "-c", "source /opt/platform/install/setup.bash && source /app/install/setup.bash && exec /app/install/camera_genicam/lib/camera_genicam/camera_node \"$@\"", "--"]

# MRP finds camera drivers by these labels and offers them as a camera type in cells.
# The manifest is checked by mrp_app.cameras.parse_manifest (application/backend).
LABEL io.mrp.driver.kind="camera" \
      io.mrp.driver.manifest='{"id": "genicam", "label": "GenICam (USB3 Vision, Aravis)", "access": "usb_bus", "fps_type": "float", "probe_command": ["ros2", "run", "camera_genicam", "camera_node"], "note": "USB3 Vision cameras of any vendor. GigE Vision needs host networking, which cell services do not have yet."}'

HEALTHCHECK --interval=10s --timeout=5s --start-period=45s --retries=3 \
    CMD ["/bin/sh", "-c", "f=$MRP_CAMERA_HEARTBEAT_FILE; [ -f \"$f\" ] && [ $(( $(date +%s) - $(stat -c %Y \"$f\") )) -lt 15 ]"]
