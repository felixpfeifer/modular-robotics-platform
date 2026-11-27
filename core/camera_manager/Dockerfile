ARG BASE_IMAGE=docker.io/felixpfeifer/mrp-ros-base:latest
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       cmake \
       cppcheck \
       libopencv-dev \
       python3-colcon-common-extensions \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /ws
COPY . /ws/src/camera_manager

RUN /bin/bash -c 'source /opt/ros/jazzy/setup.bash \
    && colcon build --packages-select camera_manager \
       --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON'

RUN useradd --create-home --shell /bin/bash camera_manager \
    && chown -R camera_manager:camera_manager /ws

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh

RUN for package in git git-man; do if dpkg -s "$package" >/dev/null 2>&1; then apt-get purge -y "$package" || exit 1; fi; done && ! command -v git
USER camera_manager
ENTRYPOINT ["/entrypoint.sh"]
CMD ["ros2", "launch", "camera_manager", "cameras.launch.py"]
