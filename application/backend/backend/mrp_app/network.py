"""Resolve the Linux container's gateway for a router on the Docker host.

Docker Desktop's host.docker.internal may refer to the laptop host rather than
the VM network namespace where a host-networked ROS cell is running.
"""

import os
import socket
import struct
from pathlib import Path


def default_gateway(routes):
    for line in routes.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 4 and fields[1] == "00000000" and int(fields[3], 16) & 2:
            return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
    raise ValueError("No Docker IPv4 gateway found; configure an explicit Zenoh router endpoint.")


def configure_zenoh():
    config = os.environ.get("ZENOH_CONFIG_OVERRIDE", "")
    if "DOCKER_GATEWAY" in config:
        gateway = default_gateway(Path("/proc/net/route").read_text())
        os.environ["ZENOH_CONFIG_OVERRIDE"] = config.replace("DOCKER_GATEWAY", gateway)
