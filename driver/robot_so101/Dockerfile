# One image for every role: leader/follower, mock/Gazebo/real, RViz and the Zenoh router.
FROM docker.io/felixpfeifer/mrp-ros-base:latest

SHELL ["/bin/bash", "-c"]

WORKDIR /app
COPY . /app

RUN test -n "$(ls -A src/feetech_ros2_driver 2>/dev/null)" && \
    test -f src/ros2_so_arm/so_arm_utils/package.xml || \
    { echo 'Missing submodules. Run: git submodule update --init --recursive' >&2; exit 1; }

RUN apt-get update && \
    rosdep update --rosdistro jazzy && \
    rosdep install -y --ignore-src \
      --from-paths \
        src/feetech_ros2_driver \
        src/ros2_so_arm/so_arm_utils \
        src/ros2_so_arm/so_arm101_description \
        src/so101_bringup \
    && rm -rf /var/lib/apt/lists/*

RUN /bin/bash -c 'source /opt/platform/install/setup.bash && \
    colcon build --symlink-install \
      --packages-up-to so101_bringup \
      --cmake-args -DCMAKE_BUILD_TYPE=Release'

    RUN for package in git git-man; do if dpkg -s "$package" >/dev/null 2>&1; then apt-get purge -y "$package" || exit 1; fi; done && ! command -v git
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["arm"]

HEALTHCHECK --interval=30s --timeout=20s --start-period=60s CMD /app/docker/healthcheck.sh
