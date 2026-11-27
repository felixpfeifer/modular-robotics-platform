"""Connection test for SDK cameras (RealSense, IDS uEye), run inside the driver's own image.

Usage: sdk_camera_probe.py --topic T --width W --height H --fps F --seconds S [--startup S] -- DRIVER...

Starts the driver command (the same one the cell runs, with its image topic remapped to T),
subscribes to T, and waits for the first frame (the IDS daemon may first upload the firmware).
It then counts frames for S seconds, stops the driver and prints one JSON line:
{ok, width, height, resolution_ok, fps, frames, jpeg_base64, error, log}. Nothing is published
outside this container: the agent runs it with --network none and removes it afterwards.
"""

import argparse
import base64
import json
import os
import signal
import subprocess
import threading
import time

import rclpy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage


def jpeg_size(data):
    """(width, height) from a JPEG's start-of-frame marker, or None. The driver images have no cv2."""
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return None
        marker, length = data[i + 1], int.from_bytes(data[i + 2 : i + 4], "big")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return int.from_bytes(data[i + 7 : i + 9], "big"), int.from_bytes(data[i + 5 : i + 7], "big")
        i += 2 + length
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--fps", type=float, required=True)
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--startup", type=float, default=40.0)
    parser.add_argument("driver", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    driver = args.driver[1:] if args.driver[:1] == ["--"] else args.driver

    log = []
    process = subprocess.Popen(
        driver, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True
    )

    def collect():
        for line in process.stdout:
            log.append(line.rstrip())
            del log[:-40]  # the last lines are enough to explain a failure

    threading.Thread(target=collect, daemon=True).start()

    rclpy.init()
    node = rclpy.create_node("mrp_camera_probe")
    frames = []  # (arrival time, message)
    node.create_subscription(
        CompressedImage,
        args.topic,
        lambda msg: frames.append((time.monotonic(), msg)),
        qos_profile_sensor_data,
    )
    result = {"ok": False}
    try:
        deadline = time.monotonic() + args.startup
        while not frames and time.monotonic() < deadline and process.poll() is None:
            rclpy.spin_once(node, timeout_sec=0.2)
        if not frames:
            reason = (
                "the driver exited" if process.poll() is not None else f"no image within {args.startup:.0f} s"
            )
            result["error"] = f"Camera did not deliver images: {reason}."
            return result
        start = frames[0][0]
        while time.monotonic() - start < args.seconds and process.poll() is None:
            rclpy.spin_once(node, timeout_sec=0.1)
        first = frames[0][1]
        size = jpeg_size(bytes(first.data))
        if size is None:
            result["error"] = f"The first image ({first.format}) is not a valid JPEG."
            return result
        width, height = size
        span = frames[-1][0] - start
        result.update(
            ok=True,
            width=width,
            height=height,
            resolution_ok=(width, height) == (args.width, args.height),
            frames=len(frames),
            fps=round((len(frames) - 1) / span, 1) if span > 0 else 0.0,
            jpeg_base64=base64.b64encode(bytes(first.data)).decode() if first.format == "jpeg" else None,
        )
        return result
    finally:
        node.destroy_node()
        rclpy.shutdown()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)  # let the driver release the camera cleanly
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
        result["log"] = log[-15:]


if __name__ == "__main__":
    print(json.dumps(main()), flush=True)
