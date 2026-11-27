"""Runtime boundary: UI demonstration mode has no ROS or dataset side effects."""

import math
import threading
import time
from contextlib import nullcontext


class RuntimeErrorDetail(Exception):
    pass


class DemoRuntime:
    mode = "demo"

    def __init__(self):
        self.cell_running = False
        self.source = "none"
        self.active_id = None
        self.started = None
        self.lock = threading.RLock()
        self.motion_elapsed = 0.0
        self.motion_started = None

    def robot_data(self):
        if not self.cell_running:
            return {}
        moving = self.motion_started is not None
        elapsed = self.motion_elapsed + (time.monotonic() - self.motion_started if moving else 0)
        names = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
        amplitudes = [0.65, 0.4, 0.55, 0.3, 0.45, 0.2]
        rates = [0.6, 0.5, 0.7, 0.8, 0.4, 0.9]
        stamp = time.time_ns()

        def sample(delay):
            phase = max(0, elapsed - delay)
            return {
                "stamp_ns": stamp,
                "joint_names": names,
                "positions": [
                    amplitude * math.sin(phase * rate) for amplitude, rate in zip(amplitudes, rates)
                ],
                "velocities": [
                    amplitude * rate * math.cos(phase * rate) if moving and elapsed >= delay else 0.0
                    for amplitude, rate in zip(amplitudes, rates)
                ],
                "fresh": True,
            }

        data = {"Leader": sample(0), "Follower": sample(0.25)}
        if moving:
            data["Action"] = {**sample(0), "source": "demo_teleop"}
        return data

    def status(self):
        with self.lock:
            checks = [
                {"name": name, "ready": self.cell_running, "detail": "Simulated UI state"}
                for name in ("Leader", "Follower", "Webcam", "Recorder", "Command bridge")
            ]
            return {
                "checks": checks,
                "ready": self.cell_running and self.source == "teleop",
                "active_source": self.source,
                "active_episode_id": self.active_id,
                "cell_running": self.cell_running,
                "message": "UI demo only. No ROS, MCAP recording or dataset export.",
                "robot_data_simulated": True,
                "robot_data": self.robot_data(),
            }

    def telemetry(self):
        with self.lock:
            return {"robot_data": self.robot_data(), "robot_data_simulated": True}

    def cell(self, action):
        with self.lock:
            if action == "down" and self.active_id:
                raise RuntimeErrorDetail("Finish or cancel the demo recording before stopping the cell.")
            self.cell_running = action == "up"
            self.source = "none"
            self.motion_elapsed = 0.0
            self.motion_started = None
        return {"message": "Demo cell " + ("started" if self.cell_running else "stopped")}

    def select_source(self, source):
        with self.lock:
            if not self.cell_running:
                raise RuntimeErrorDetail("Start the demo cell first.")
            if self.motion_started is not None:
                self.motion_elapsed += time.monotonic() - self.motion_started
            self.motion_started = time.monotonic() if source == "teleop" else None
            self.source = source

    def start(self, episode_id, snapshot, completed):
        if not self.status()["ready"]:
            raise RuntimeErrorDetail("Start the demo cell and enable teleoperation first.")
        self.active_id = episode_id
        self.started = time.time()

    def mark(self, episode_id, kind, annotation=""):
        if self.active_id != episode_id:
            raise RuntimeErrorDetail("This episode is not active.")
        if kind == "annotation":
            return
        self.active_id = None

    def watch_camera(self, name):
        return nullcontext(False)

    def preview(self, name=None):
        return None

    def close(self):
        pass
