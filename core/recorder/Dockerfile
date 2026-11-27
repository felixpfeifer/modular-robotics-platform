FROM docker.io/felixpfeifer/mrp-ros-base:latest AS builder

SHELL ["/bin/bash", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends \
    nlohmann-json3-dev python3-opencv python3-yaml \
    ros-jazzy-control-msgs ros-jazzy-trajectory-msgs \
    ros-jazzy-rosbag2 ros-jazzy-rosbag2-cpp ros-jazzy-rosbag2-storage-mcap \
    ros-jazzy-rosbag2-transport \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /ws
COPY recorder src/episode_recorder
RUN /bin/bash -c 'source /opt/platform/install/setup.bash && \
    colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release && \
    source install/setup.bash && \
    colcon test --packages-select episode_recorder --event-handlers console_direct+ && \
    colcon test-result --verbose'

# rmw_zenoh_cpp and zenoh-cpp-vendor come from the base image as a matching pair. Do not install
# ros-jazzy-rmw-zenoh-cpp here: apt would upgrade it alone and it then rejects the older
# Zenoh library ("unknown field `region_name`" / "Error configuring Zenoh session").
FROM docker.io/felixpfeifer/mrp-ros-base:latest
SHELL ["/bin/bash", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-opencv python3-yaml \
    ros-jazzy-control-msgs ros-jazzy-trajectory-msgs \
    ros-jazzy-rosbag2 ros-jazzy-rosbag2-storage-mcap \
    ros-jazzy-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /ws/install /ws/install
COPY recorder/docker/entrypoint.sh /ws/entrypoint.sh
RUN for package in git git-man; do if dpkg -s "$package" >/dev/null 2>&1; then apt-get purge -y "$package" || exit 1; fi; done && ! command -v git
VOLUME /data/datasets
EXPOSE 9108
ENTRYPOINT ["/bin/bash", "/ws/entrypoint.sh"]
