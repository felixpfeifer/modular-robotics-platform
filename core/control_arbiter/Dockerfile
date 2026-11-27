FROM docker.io/felixpfeifer/mrp-ros-base:latest AS builder

SHELL ["/bin/bash", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-jazzy-rmw-cyclonedds-cpp ros-jazzy-rmw-fastrtps-cpp \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /ws
COPY control_arbiter src/control_arbiter
RUN /bin/bash -c 'source /opt/platform/install/setup.bash && \
    rosdep install --from-paths src --ignore-src --skip-keys "platform_common_interfaces platform_control_interfaces" -r -y && \
    colcon build --packages-up-to control_arbiter && \
    source install/setup.bash && \
    colcon test --packages-select control_arbiter --event-handlers console_direct+ && \
    colcon test-result --verbose'

# rmw_zenoh_cpp comes from the base image together with its matching zenoh-cpp-vendor.
FROM docker.io/felixpfeifer/mrp-ros-base:latest
SHELL ["/bin/bash", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-jazzy-rmw-cyclonedds-cpp ros-jazzy-rmw-fastrtps-cpp \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /ws/install /ws/install
COPY control_arbiter/docker /ws/control_arbiter/docker
RUN for package in git git-man; do if dpkg -s "$package" >/dev/null 2>&1; then apt-get purge -y "$package" || exit 1; fi; done && ! command -v git
ENTRYPOINT ["/bin/bash", "/ws/control_arbiter/docker/entrypoint.sh"]
CMD ["ros2", "launch", "control_arbiter", "control.launch.py", "mode:=none"]