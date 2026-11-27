"""Render a restricted Compose plan and explicitly operate it from the host."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

from .model import validate


class PlanError(ValueError):
    pass


# Runs inside the existing camera image, which provides OpenCV and ROS Python.
MOCK_CAMERA = """import cv2
import numpy as np
import rclpy
from sensor_msgs.msg import CompressedImage

rclpy.init()
node = rclpy.create_node("mock_camera")
publisher = node.create_publisher(CompressedImage, __import__("os").environ["CAMERA_TOPIC"], 10)
frame = 0
def publish():
    global frame
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    image[:] = (45, 35, 25)
    cv2.putText(image, "Simulated camera", (35, 65), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    cv2.putText(image, node.get_name(), (35, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
    cv2.circle(image, (40 + frame % 560, 250), 30, (30, 180, 255), -1)
    ok, encoded = cv2.imencode(".jpg", image)
    if ok:
        msg = CompressedImage()
        msg.header.stamp = node.get_clock().now().to_msg()
        msg.header.frame_id = node.get_name()
        msg.format = "jpeg"
        msg.data = encoded.tobytes()
        publisher.publish(msg)
    frame += 8
node.create_timer(0.1, publish)
try:
    rclpy.spin(node)
finally:
    node.destroy_node()
    rclpy.shutdown()
"""


def render(doc):
    validate(doc)
    services = {}
    namespaces = set()
    topics = set()
    for robot in doc["robots"]:
        if robot["driver"] != "robot_so101":
            raise PlanError(f"{robot['id']}: unsupported robot driver")
        connection = robot["connection"]
        if connection["type"] not in ("serial", "simulated"):
            raise PlanError(
                f"{robot['id']}: SO-101 requires serial or simulated connection"
            )
        namespace = robot["namespace"].strip("/")
        if namespace in namespaces:
            raise PlanError("robot namespaces must be unique")
        namespaces.add(namespace)
        env = {
            "ROLE": robot["role"],
            "NAMESPACE": namespace,
            "BACKEND": "real" if connection["type"] == "serial" else "mock",
            "RMW": "fastdds",
            "RMW_IMPLEMENTATION": "rmw_fastrtps_cpp",
        }
        service = {
            "image": "mrp-robot-so101",
            "network_mode": "host",
            "ipc": "host",
            "restart": "no",
            "command": ["arm"],
            "environment": env,
        }
        if connection["type"] == "serial":
            env["USB_PORT"] = connection["path"]
            service["volumes"] = ["/dev:/dev"]
            service["device_cgroup_rules"] = ["c 166:* rmw", "c 188:* rmw"]
        services["robot_" + robot["id"].replace("-", "_")] = service
    for camera in doc["cameras"]:
        if camera["driver"] != "camera_opencv" or camera["connection"]["type"] not in (
            "usb",
            "simulated",
        ):
            raise PlanError(
                f"{camera['id']}: camera_opencv requires a USB or simulated connection"
            )
        if camera["topic"] in topics:
            raise PlanError("camera topics must be unique")
        topics.add(camera["topic"])
        service_name = "camera_" + camera["id"].replace("-", "_")
        if camera["connection"]["type"] == "simulated":
            services[service_name] = {
                "image": "mrp-camera-opencv",
                "network_mode": "host",
                "restart": "no",
                "entrypoint": ["/bin/bash", "-c"],
                "command": [
                    'source /opt/platform/install/setup.bash && exec python3 -c "$1" --ros-args -r __node:="$2"',
                    "--",
                    MOCK_CAMERA,
                    service_name,
                ],
                "environment": {
                    "RMW_IMPLEMENTATION": "rmw_fastrtps_cpp",
                    "CAMERA_TOPIC": camera["topic"],
                },
                "healthcheck": {"disable": True},
            }
            continue
        services[service_name] = {
            "image": "mrp-camera-opencv",
            "network_mode": "host",
            "restart": "no",
            "devices": ["/dev:/dev"],
            "privileged": True,
            "environment": {"RMW_IMPLEMENTATION": "rmw_fastrtps_cpp"},
            "command": [
                "--ros-args",
                "-p",
                "video_device:=" + camera["connection"]["path"],
                "-r",
                "image/compressed:=" + camera["topic"],
                "-r",
                "__node:=camera_" + camera["id"].replace("-", "_"),
            ],
        }

    # Compose interprets dollar signs even inside JSON string values.
    def escape(value):
        if isinstance(value, str):
            return value.replace("$", "$$")
        if isinstance(value, list):
            return [escape(v) for v in value]
        if isinstance(value, dict):
            return {k: escape(v) for k, v in value.items()}
        return value

    if len(services) != len(doc["robots"]) + len(doc["cameras"]):
        raise PlanError("device IDs collide after conversion to Compose service names")
    if not services:
        raise PlanError("cell has no runnable devices")
    return escape({"services": services})


class Deployment:
    """Run one Compose project at a time, using a snapshot of the cell."""

    def __init__(self, project="mrp-cell"):
        self.project = project
        self.lock = threading.Lock()

    def run(self, action, doc=None):
        with self.lock:
            plan = (
                render(doc)
                if action == "up"
                else {"services": {"placeholder": {"image": "hello-world"}}}
            )
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", encoding="utf-8"
            ) as f:
                json.dump(plan, f)
                f.flush()
                command = [
                    "docker",
                    "compose",
                    "--project-name",
                    self.project,
                    "--file",
                    f.name,
                ]
                command += {
                    "up": [
                        "up",
                        "-d",
                        "--remove-orphans",
                        "--no-build",
                        "--pull",
                        "never",
                    ],
                    "down": ["down", "--remove-orphans"],
                    "status": ["ps", "--all"],
                }[action]
                return subprocess.run(
                    command, capture_output=True, text=True, timeout=120, check=False
                )


def main():
    parser = argparse.ArgumentParser(
        description="Render or run the cell deployment on the Docker host"
    )
    parser.add_argument("action", choices=["plan", "up", "down", "status"])
    parser.add_argument("--config", default="/data/cell.json")
    parser.add_argument("--project", default="mrp-cell", help="Compose project name")
    args = parser.parse_args()
    try:
        if args.action in ("down", "status"):
            # Compose needs a file even when the original configuration changed.
            plan = {"services": {"placeholder": {"image": "hello-world"}}}
        else:
            plan = render(json.loads(Path(args.config).read_text(encoding="utf-8")))
        if args.action == "plan":
            print(json.dumps(plan, indent=2))
            return
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", encoding="utf-8"
        ) as f:
            json.dump(plan, f)
            f.flush()
            command = [
                "docker",
                "compose",
                "--project-name",
                args.project,
                "--file",
                f.name,
            ]
            command += {
                "up": ["up", "-d", "--remove-orphans", "--no-build", "--pull", "never"],
                "down": ["down", "--remove-orphans"],
                "status": ["ps", "--all"],
            }[args.action]
            result = subprocess.run(command, check=False)
            sys.exit(result.returncode)
    except (ValueError, OSError) as exc:
        print(f"cell deployment: {exc}", file=sys.stderr)
        sys.exit(1)
