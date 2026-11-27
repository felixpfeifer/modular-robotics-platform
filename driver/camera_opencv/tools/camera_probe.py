#!/usr/bin/env python3
"""Open a V4L2 camera, measure its real frame rate and optionally return a JPEG snapshot.

One JSON document on stdout. Needs OpenCV (python3-opencv), which the camera and recorder
images have. It never writes anything except stdout.

  camera_probe.py DEVICE [--width 640] [--height 480] [--fps 30] [--seconds 3] [--snapshot]
                         [--pixel-format MJPG]

It opens the device exactly like camera_node does (same default pixel format), so the
measured rate is the rate the driver will deliver.
"""

import argparse
import base64
import json
import sys
import time


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("device")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--snapshot", action="store_true")
    parser.add_argument(
        "--pixel-format",
        default="",
        help="V4L2 FOURCC (e.g. MJPG); empty = OpenCV's choice, like camera_node",
    )
    args = parser.parse_args(argv)
    import cv2

    if args.pixel_format and len(args.pixel_format) != 4:
        print(json.dumps({"ok": False, "error": "--pixel-format must have 4 characters"}))
        return 2
    capture = cv2.VideoCapture(args.device, cv2.CAP_V4L2)
    if not capture.isOpened():
        print(json.dumps({"ok": False, "error": f"Cannot open {args.device}"}))
        return 1
    if args.pixel_format:
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*args.pixel_format))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    capture.set(cv2.CAP_PROP_FPS, args.fps)
    frames, last, started = 0, None, time.monotonic()
    deadline = started + max(0.5, min(args.seconds, 20.0))
    first = None
    while time.monotonic() < deadline:
        ok, frame = capture.read()
        if ok:
            if first is None:
                first = time.monotonic()
                started = first  # do not count camera warm-up in the rate
            frames += 1
            last = frame
    capture.release()
    if last is None:
        print(
            json.dumps(
                {"ok": False, "error": "The camera opened but delivered no frames."}
            )
        )
        return 1
    elapsed = max(1e-6, time.monotonic() - started)
    height, width = last.shape[:2]
    result = {
        "ok": True,
        "width": width,
        "height": height,
        "fps": round(max(0, frames - 1) / elapsed, 1),
        "resolution_ok": (width, height) == (args.width, args.height),
        "mean_brightness": round(float(last.mean()), 1),
    }
    if args.snapshot:
        encoded_ok, encoded = cv2.imencode(".jpg", last, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if encoded_ok:
            result["jpeg_base64"] = base64.b64encode(encoded.tobytes()).decode()
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
