#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import time
import uuid
from pathlib import Path

import rclpy
from ament_index_python.packages import get_package_share_directory
from platform_common_interfaces.msg import ProvenanceReference
from platform_control_interfaces.msg import JointIntent
from platform_episode_interfaces.action import RecordEpisode
from platform_episode_interfaces.srv import MarkEpisode
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.node import Node

from episode_recorder_py.configuration import load_workspace_config


JOINTS = [
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_flex_joint",
    "wrist_flex_joint",
    "wrist_roll_joint",
    "gripper_joint",
]


def _uuid(target) -> None:
    target.uuid = list(uuid.uuid4().bytes)


class HilQualification(Node):
    def __init__(
        self, dataset_dir: Path, artifact_dir: Path, workspace_config: Path
    ) -> None:
        super().__init__("episode_hil_qualification")
        self.dataset_dir = dataset_dir
        self.artifact_dir = artifact_dir
        self.workspace = load_workspace_config(workspace_config)
        self.intent_pub = self.create_publisher(
            JointIntent, "/platform/control/joint_intent", 50
        )
        self.record_client = ActionClient(
            self, RecordEpisode, "/platform/episode/record"
        )
        self.mark_client = self.create_client(MarkEpisode, "/platform/episode/mark")
        self.phase = 0

    def publish_safe_intent(self) -> None:
        now = self.get_clock().now()
        message = JointIntent()
        _uuid(message.command_id)
        _uuid(message.lease_id)
        message.source_id = "episode_hil_qualification"
        message.target_id = "so101"
        message.issued_at = now.to_msg()
        message.valid_until = (now + Duration(seconds=0.1)).to_msg()
        message.joint_names = list(JOINTS)
        delta = 0.04 * math.sin(self.phase / 30.0)
        message.positions = [delta, -delta, delta, -delta, delta, 0.8 + delta]
        self.phase += 1
        self.intent_pub.publish(message)

    def pump(self, seconds: float, future=None) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.publish_safe_intent()
            rclpy.spin_once(self, timeout_sec=0.02)
            if future is not None and future.done():
                return True
        return future is None or future.done()

    def goal(self, episode_id: uuid.UUID) -> RecordEpisode.Goal:
        goal = RecordEpisode.Goal()
        _uuid(goal.request_id)
        goal.metadata.episode_id.uuid = list(episode_id.bytes)
        goal.metadata.workcell_id = self.workspace["id"]
        goal.metadata.task_id = self.workspace["task_id"]
        goal.metadata.recording_profile_id = self.workspace["recording_profile_id"]
        goal.metadata.configuration.schema_id = "episode-recording"
        goal.metadata.configuration.schema_version = "1.0.0"
        goal.metadata.configuration.configuration_id = self.workspace["id"]
        goal.metadata.configuration.content_hash = self.workspace["configuration_hash"]
        producer = ProvenanceReference()
        producer.component.component_id = "episode_hil_qualification"
        producer.component.name = "SO-101 HIL qualification"
        producer.component.semantic_version = "0.2.0"
        producer.component.source_revision = os.environ.get(
            "CI_COMMIT_SHA", "local-hil"
        )
        producer.component.build_id = producer.component.source_revision
        producer.configuration = goal.metadata.configuration
        producer.calibration_id = os.environ.get("HIL_CALIBRATION_ID", "so101-hil")
        producer.calibration_hash = os.environ["HIL_CALIBRATION_HASH"]
        goal.metadata.producers.append(producer)
        goal.metadata.calibration_ids.append(producer.calibration_id)
        return goal

    def record(self, success: bool, duration: float) -> Path:
        episode_id = uuid.uuid4()
        send_future = self.record_client.send_goal_async(self.goal(episode_id))
        if not self.pump(10.0, send_future) or not send_future.result().accepted:
            raise RuntimeError("recorder rejected HIL goal; inspect preflight logs")
        goal_handle = send_future.result()
        self.pump(duration)
        request = MarkEpisode.Request()
        _uuid(request.request_id)
        request.episode_id.uuid = list(episode_id.bytes)
        request.source_id = "episode_hil_qualification"
        request.mark = (
            MarkEpisode.Request.MARK_SUCCESS
            if success
            else MarkEpisode.Request.MARK_FAILURE
        )
        request.annotation = "bounded HIL trajectory"
        mark_future = self.mark_client.call_async(request)
        if not self.pump(5.0, mark_future) or not mark_future.result().accepted:
            raise RuntimeError("HIL terminal mark was rejected")
        result_future = goal_handle.get_result_async()
        if not self.pump(30.0, result_future):
            raise TimeoutError("HIL recording action did not finalize")
        result = result_future.result().result
        if not result.complete or result.artifact_id != str(episode_id):
            raise RuntimeError(f"HIL artifact finalization failed: {result.reason}")
        episode = self.dataset_dir / "episodes" / str(episode_id)
        expected_status = "accepted" if success else "rejected"
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            self.pump(0.1)
            status_path = episode / "status.json"
            if status_path.is_file():
                status = json.loads(status_path.read_text(encoding="utf-8"))
                if status.get("status") == expected_status:
                    break
        else:
            raise RuntimeError(f"HIL episode did not reach {expected_status}")
        evidence = self.artifact_dir / str(episode_id)
        evidence.mkdir(parents=True, exist_ok=True)
        for relative in (
            "manifest.json",
            "status.json",
            "validation/validation.json",
            "validation/validation.junit.xml",
        ):
            source = episode / relative
            if source.is_file():
                shutil.copy2(source, evidence / Path(relative).name)
        return episode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bounded SO-101/RealSense HIL acceptance and rejection qualification"
    )
    parser.add_argument("--dataset-dir", required=True, type=Path)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument(
        "--workspace-config",
        type=Path,
        default=Path(get_package_share_directory("episode_recorder"))
        / "config/workspaces/local_so101.yaml",
    )
    args = parser.parse_args()
    calibration_hash = os.environ.get("HIL_CALIBRATION_HASH", "")
    if (
        os.environ.get("MRP_HIL") != "1"
        or os.environ.get("HIL_ESTOP_CONFIRMED") != "1"
        or len(calibration_hash) != 71
        or not calibration_hash.startswith("sha256:")
        or calibration_hash[7:] == "0" * 64
        or any(
            character not in "0123456789abcdefABCDEF"
            for character in calibration_hash[7:]
        )
    ):
        raise RuntimeError(
            "MRP_HIL=1, HIL_ESTOP_CONFIRMED=1, and a SHA-256 HIL_CALIBRATION_HASH are mandatory"
        )
    rclpy.init()
    node = HilQualification(args.dataset_dir, args.artifact_dir, args.workspace_config)
    try:
        if not node.record_client.wait_for_server(timeout_sec=15.0):
            raise RuntimeError("record action server unavailable")
        if not node.mark_client.wait_for_service(timeout_sec=15.0):
            raise RuntimeError("mark service unavailable")
        node.pump(3.0)
        accepted = node.record(True, 3.0)
        rejected = node.record(False, 0.5)
        print(
            f"HIL qualified accepted={accepted.name} deliberate_rejection={rejected.name}"
        )
        return 0
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
