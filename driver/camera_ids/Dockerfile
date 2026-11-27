# Build context: the directory that holds camera_ids/ and mrp_camera_common/
# (the driver workspace locally, .image-context in CI; see docker-compose.yaml).
# Single stage on purpose: the IDS SDK provides both the headers and the daemons
# the container runs, so a separate runtime stage would install it twice.
ARG BASE_IMAGE=docker.io/felixpfeifer/mrp-ros-base:latest
FROM ${BASE_IMAGE}

# libopencv-dev -> JPEG encoding; usbutils -> lsusb for troubleshooting.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopencv-dev \
    usbutils \
    && rm -rf /var/lib/apt/lists/*

# IDS Software Suite from sdk/ (downloaded by the user, see README.md). The bind
# mount keeps the proprietary archive itself out of every image layer.
COPY camera_ids/docker/install-ids-sdk.sh /usr/local/bin/install-ids-sdk.sh
ARG IDS_SDK_EXCLUDE=demo|cockpit|tools-qt|manual|halcon
RUN --mount=type=bind,source=camera_ids/sdk,target=/tmp/ids-sdk \
    IDS_SDK_EXCLUDE="${IDS_SDK_EXCLUDE}" /usr/local/bin/install-ids-sdk.sh /tmp/ids-sdk

WORKDIR /app
COPY mrp_camera_common /app/src/mrp_camera_common
COPY camera_ids/CMakeLists.txt camera_ids/package.xml /app/src/camera_ids/
COPY camera_ids/include /app/src/camera_ids/include
COPY camera_ids/src /app/src/camera_ids/src
COPY camera_ids/test /app/src/camera_ids/test
RUN ["/bin/bash", "-c", "source /opt/platform/install/setup.bash && colcon build --base-paths src --cmake-args -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release -DCAMERA_IDS_REQUIRE_SDK=ON"]

COPY camera_ids/docker/entrypoint.sh /usr/local/bin/camera-ids-entrypoint.sh
RUN for package in git git-man; do if dpkg -s "$package" >/dev/null 2>&1; then apt-get purge -y "$package" || exit 1; fi; done && ! command -v git
ENTRYPOINT ["/usr/local/bin/camera-ids-entrypoint.sh"]

# The node touches this file while frames flow; the healthcheck checks its age.
ENV MRP_CAMERA_HEARTBEAT_FILE=/tmp/mrp-camera-heartbeat
HEALTHCHECK --interval=10s --timeout=5s --start-period=45s --retries=3 \
    CMD ["/bin/sh", "-c", "f=$MRP_CAMERA_HEARTBEAT_FILE; [ -f \"$f\" ] && [ $(( $(date +%s) - $(stat -c %Y \"$f\") )) -lt 15 ]"]
