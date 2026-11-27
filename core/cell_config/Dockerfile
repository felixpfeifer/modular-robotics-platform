ARG BASE_IMAGE=docker.io/felixpfeifer/mrp-ros-base:latest
FROM ${BASE_IMAGE} AS builder
SHELL ["/bin/bash", "-c"]
WORKDIR /ws
COPY . src/cell_config
RUN ["/bin/bash", "-c", "source /opt/platform/install/setup.bash && colcon build --packages-select cell_config"]

ARG BASE_IMAGE=docker.io/felixpfeifer/mrp-ros-base:latest
FROM ${BASE_IMAGE}
SHELL ["/bin/bash", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends docker.io docker-compose-v2 && rm -rf /var/lib/apt/lists/*
COPY --from=builder /ws/install /ws/install
RUN for package in git git-man; do if dpkg -s "$package" >/dev/null 2>&1; then apt-get purge -y "$package" || exit 1; fi; done && ! command -v git
VOLUME /data
EXPOSE 8080
ENTRYPOINT ["/bin/bash", "-c", "source /opt/platform/install/setup.bash && source /ws/install/setup.bash && exec ros2 run cell_config cell_config --ros-args -p host:=0.0.0.0 \"$@\"", "--"]
