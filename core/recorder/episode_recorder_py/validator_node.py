#!/usr/bin/env python3
from __future__ import annotations

import json
import threading
import uuid
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import rclpy
from ament_index_python.packages import get_package_share_directory
from platform_episode_interfaces.action import ValidateEpisode
from platform_episode_interfaces.msg import ValidationFinding
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.node import Node
from std_msgs.msg import String

from episode_recorder_py.validation import validate_episode


class Metrics:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.validation_totals: Counter[tuple[str, str]] = Counter()
        self.rule_totals: Counter[tuple[str, str, str]] = Counter()
        self.last: dict[str, float] = {}
        self.recorder: dict[str, int | float | str] = {}

    def render(self) -> bytes:
        with self.lock:
            lines = [
                "# TYPE episode_validation_total counter",
                "# TYPE episode_validation_rule_total counter",
            ]
            for (profile, result), value in sorted(self.validation_totals.items()):
                lines.append(
                    f'episode_validation_total{{profile="{profile}",result="{result}"}} {value}'
                )
            for (profile, result, rule), value in sorted(self.rule_totals.items()):
                lines.append(
                    f'episode_validation_rule_total{{profile="{profile}",result="{result}",rule="{rule}"}} {value}'
                )
            recorder_names = {
                "state": "episode_recorder_state",
                "writer_queue_bytes": "episode_recorder_writer_queue_bytes",
                "writer_drops": "episode_recorder_writer_drops_total",
                "writer_errors": "episode_recorder_writer_errors_total",
            }
            for key, metric_name in recorder_names.items():
                value = self.recorder.get(key)
                if isinstance(value, (int, float)):
                    lines.append(f"{metric_name} {value}")
            profile = str(self.recorder.get("profile", "unknown")).replace('"', "")
            recording_results = {
                "recordings_started": "started",
                "recordings_completed": "completed",
                "recordings_rejected": "rejected",
            }
            for key, recording_result in recording_results.items():
                value = self.recorder.get(key)
                if isinstance(value, (int, float)):
                    lines.append(
                        f'episode_recording_total{{profile="{profile}",result="{recording_result}"}} {value}'
                    )
            latest_names = {
                "duration_seconds": "episode_latest_duration_seconds",
                "camera_fps": "episode_latest_camera_fps",
                "state_skew_p99_ms": "episode_latest_state_skew_p99_ms",
                "state_skew_max_ms": "episode_latest_state_skew_max_ms",
            }
            for key, metric_name in latest_names.items():
                value = self.last.get(key)
                if isinstance(value, (int, float)):
                    lines.append(f"{metric_name} {value}")
            return ("\n".join(lines) + "\n").encode()


class ValidatorNode(Node):
    def __init__(self) -> None:
        super().__init__("episode_validator")
        share = Path(get_package_share_directory("episode_recorder"))
        self.declare_parameter("dataset_dir", "/data/datasets/teleop")
        self.declare_parameter(
            "recording_profiles", str(share / "config/recording_profiles.yaml")
        )
        self.declare_parameter("task_catalog", str(share / "config/task_catalog.yaml"))
        self.declare_parameter("metrics_address", "127.0.0.1")
        self.declare_parameter("metrics_port", 9108)
        self.dataset_dir = Path(self.get_parameter("dataset_dir").value)
        self.profile_path = Path(self.get_parameter("recording_profiles").value)
        self.task_path = Path(self.get_parameter("task_catalog").value)
        self.metrics = Metrics()
        self._reservation_lock = threading.Lock()
        self._reserved = False
        self.runtime_sub = self.create_subscription(
            String, "/platform/episode/metrics", self._runtime_metrics, 10
        )
        self.server = ActionServer(
            self,
            ValidateEpisode,
            "/platform/episode/validate",
            execute_callback=self.execute,
            goal_callback=self.goal,
            cancel_callback=lambda _: CancelResponse.ACCEPT,
        )
        self._http = self._start_metrics()

    def _start_metrics(self) -> ThreadingHTTPServer:
        metrics = self.metrics

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path != "/metrics":
                    self.send_error(404)
                    return
                payload = metrics.render()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_: object) -> None:
                return

        server = ThreadingHTTPServer(
            (
                str(self.get_parameter("metrics_address").value),
                int(self.get_parameter("metrics_port").value),
            ),
            Handler,
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server

    def goal(self, request: ValidateEpisode.Goal) -> GoalResponse:
        episode_id = str(uuid.UUID(bytes=bytes(request.episode_id.uuid)))
        path = self.dataset_dir / "episodes" / episode_id
        with self._reservation_lock:
            if not path.is_dir() or self._reserved:
                return GoalResponse.REJECT
            self._reserved = True
        return GoalResponse.ACCEPT

    def _runtime_metrics(self, message: String) -> None:
        try:
            payload = json.loads(message.data)
        except (TypeError, ValueError):
            return
        if isinstance(payload, dict):
            with self.metrics.lock:
                self.metrics.recorder = payload

    async def execute(self, goal_handle):
        try:
            request = goal_handle.request
            episode_id = str(uuid.UUID(bytes=bytes(request.episode_id.uuid)))
            feedback = ValidateEpisode.Feedback()
            feedback.episode_id = request.episode_id
            feedback.progress = 0.05
            feedback.current_rule_id = "storage.single_mcap"
            goal_handle.publish_feedback(feedback)
            outcome = validate_episode(
                self.dataset_dir / "episodes" / episode_id,
                self.profile_path,
                self.task_path,
                request.content_hash,
            )
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
            else:
                goal_handle.succeed()
            result = ValidateEpisode.Result()
            result.request_id = request.request_id
            result.episode_id = request.episode_id
            result.valid = outcome.valid
            result.report_reference = "validation/validation.json"
            result.reason = "accepted" if outcome.valid else "episode failed validation"
            for item in outcome.findings[:256]:
                finding = ValidationFinding()
                finding.finding_id.uuid = list(uuid.uuid4().bytes)
                finding.episode_id = request.episode_id
                finding.rule_id = item.rule_id
                finding.severity = {"info": 0, "warning": 1, "error": 2, "fatal": 3}[
                    item.severity
                ]
                finding.disposition = 1 if not item.failing else 2
                finding.summary = item.summary[:256]
                result.findings.append(finding)
            manifest = json.loads(
                (
                    self.dataset_dir / "episodes" / episode_id / "manifest.json"
                ).read_text(encoding="utf-8")
            )
            profile = str(manifest.get("recording_profile_id", "unknown"))
            validation_result = "accepted" if outcome.valid else "rejected"
            with self.metrics.lock:
                self.metrics.validation_totals[(profile, validation_result)] += 1
                for item in outcome.findings:
                    rule_result = "failed" if item.failing else item.severity
                    self.metrics.rule_totals[(profile, rule_result, item.rule_id)] += 1
                self.metrics.last = outcome.metrics
            return result
        finally:
            with self._reservation_lock:
                self._reserved = False

    def destroy_node(self) -> None:
        self._http.shutdown()
        self.server.destroy()
        super().destroy_node()


def main() -> None:
    rclpy.init()
    node = ValidatorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
