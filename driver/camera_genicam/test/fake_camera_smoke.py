#!/usr/bin/env python3
"""End-to-end check against Aravis' built-in simulated GigE camera (transport:=fake).

Starts the built camera_node, subscribes to image/compressed and checks what the MRP
recorder validates: format "jpeg" and every frame at the configured size. No camera,
network or display is needed. Usage: fake_camera_smoke.py --node <camera_node binary>
"""

import argparse
import os
import struct
import subprocess
import sys
import time
from xml.sax.saxutils import escape

import rclpy
from rclpy.parameter import Parameter
from rclpy.parameter_client import AsyncParameterClient
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage


def jpeg_size(data):
    """(width, height) from the first SOF marker of a JPEG, or None."""
    data = bytes(data)
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width, height
        i += 2 + length
    return None


def write_junit(path, seconds, failure):
    """JUnit result for ament_add_test (it fails a test that writes none)."""
    if not path:
        return
    body = f'<failure message="{escape(failure, {chr(34): "&quot;"})}"/>' if failure else ""
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<testsuite name="camera_genicam" tests="1" failures="{int(bool(failure))}" errors="0" '
            f'time="{seconds:.3f}"><testcase classname="camera_genicam" name="fake_camera_smoke" '
            f'time="{seconds:.3f}">{body}</testcase></testsuite>\n'
        )


def main():
    args = parse_args()
    started = time.monotonic()
    failure = run(args)
    write_junit(args.junit, time.monotonic() - started, failure)
    if failure:
        print(failure, file=sys.stderr)
        return 1
    return 0


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", required=True)
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=240)
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--junit", help="write a JUnit result file here")
    return parser.parse_args()


def run(args):
    """Returns an empty string on success, otherwise the failure."""
    # Private namespace: parallel test runs cannot see each other's frames.
    namespace = f"/genicam_smoke_{os.getpid()}"
    command = [
        args.node, "--ros-args", "-r", f"__ns:={namespace}",
        "-p", "transport:=fake", "-p", f"image_width:={args.width}", "-p", f"image_height:={args.height}",
        "-p", "fps:=20.0", "-p", "startup_timeout_s:=5.0",
        "-p", "pixel_format:=Mono8", "-p", "features:=['PixelFormat=Mono16']",
    ]  # fmt: skip
    rclpy.init()
    listener = rclpy.create_node("genicam_smoke_listener")
    frames = []
    listener.create_subscription(
        CompressedImage, f"{namespace}/image/compressed", frames.append, qos_profile_sensor_data
    )
    node_process = subprocess.Popen(command)
    deadline = time.monotonic() + args.timeout
    try:
        while len(frames) < args.frames and time.monotonic() < deadline:
            if node_process.poll() is not None:
                return f"camera_node exited early with status {node_process.returncode}"
            rclpy.spin_once(listener, timeout_sec=0.2)
        if len(frames) < args.frames:
            return f"received {len(frames)} of {args.frames} frames"

        client = AsyncParameterClient(listener, f"{namespace}/camera_node")
        if not client.wait_for_services(timeout_sec=5.0):
            return "camera parameter services did not appear"
        update = client.set_parameters([Parameter("image_width", value=args.width + 1)])
        rclpy.spin_until_future_complete(listener, update, timeout_sec=5.0)
        if not update.done() or update.result() is None:
            return "camera parameter service did not respond"
        result = update.result().results[0]
        if result.successful or "read-only" not in result.reason:
            return f"expected a read-only parameter error, got: {result}"
    finally:
        listener.destroy_node()
        rclpy.shutdown()
        node_process.terminate()
        try:
            node_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            node_process.kill()
            node_process.wait()

    if node_process.returncode != 0:
        return f"camera_node failed to shut down cleanly (status {node_process.returncode})"

    for msg in frames:
        size = jpeg_size(msg.data)
        if msg.format != "jpeg" or size != (args.width, args.height):
            return f"bad frame: format={msg.format!r} size={size}"
    print(f"OK: {len(frames)} JPEG frames at {args.width}x{args.height} from the fake GigE camera")
    return ""


if __name__ == "__main__":
    sys.exit(main())
