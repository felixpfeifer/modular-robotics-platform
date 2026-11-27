"""ROS adapter, imported only in ROS mode after sourcing the workspace."""

import copy
import json
import math
import os
import re
import socket
import threading
import time
import uuid
from collections import Counter, deque
from contextlib import contextmanager, nullcontext
from pathlib import Path

import rclpy
from control_msgs.action import GripperCommand, ParallelGripperCommand
from episode_recorder_py.configuration import load_workspace_config
from platform_common_interfaces.msg import ProvenanceReference
from platform_control_interfaces.msg import JointIntent
from platform_episode_interfaces.action import RecordEpisode
from platform_episode_interfaces.msg import EpisodeState
from platform_episode_interfaces.srv import MarkEpisode
from rclpy.action import ActionClient
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.parameter_client import AsyncParameterClient
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, JointState
from std_msgs.msg import String

from .runtime import RuntimeErrorDetail


def await_future(future, seconds=5):
    done = threading.Event()
    future.add_done_callback(lambda _: done.set())
    if not done.wait(seconds):
        raise TimeoutError("ROS request timed out; inspect recorder state before retrying.")
    return future.result()


def set_uuid(field, value):
    field.uuid = list(uuid.UUID(value).bytes)


class DeferredRosRuntime:
    """Serve the application while a client-mode ROS connection waits for its cell."""

    mode = "ros"

    def __init__(self, workspace_path):
        self.workspace_path = workspace_path
        self.workspace = load_workspace_config(Path(workspace_path))
        self.runtime = None
        self.error = "Waiting for the cell's Zenoh router. Start the cell from the application."
        self.stop = threading.Event()
        config = os.environ.get("ZENOH_CONFIG_OVERRIDE", "")
        match = re.search(r"tcp/([^\"/:;]+):(\d+)", config)
        self.endpoint = (match[1], int(match[2])) if match else ("127.0.0.1", 7447)
        self.worker = threading.Thread(target=self.connect, daemon=True)
        self.worker.start()

    def snapshot(self):
        result = copy.deepcopy(self.workspace)
        result["instruction"] = result["task"]["instruction"]
        result["minimum_duration_seconds"] = result["profile"].get("minimum_duration_seconds", 5)
        return result

    def connect(self):
        while not self.stop.is_set():
            try:
                with socket.create_connection(self.endpoint, timeout=0.5):
                    pass
            except OSError:
                self.stop.wait(1)
                continue
            try:
                runtime = RosRuntime(self.workspace_path)
                if self.stop.is_set():
                    runtime.close()
                else:
                    self.runtime = runtime
                return
            except Exception as exc:
                self.error = f"ROS connection failed: {exc}. Check the cell router and interface versions."
                try:
                    rclpy.try_shutdown()
                except Exception:
                    pass
                self.stop.wait(3)

    def status(self):
        if self.runtime:
            return self.runtime.status()
        return {
            "checks": [{"name": "Zenoh connection", "ready": False, "detail": self.error}],
            "ready": False,
            "active_source": "unknown",
            "active_episode_id": None,
            "cell_running": False,
            "message": self.error,
        }

    def telemetry(self):
        return self.runtime.telemetry() if self.runtime else {"robot_data": {}}

    def select_source(self, source):
        if not self.runtime:
            raise RuntimeErrorDetail(self.error)
        return self.runtime.select_source(source)

    def start(self, *args):
        if not self.runtime:
            raise RuntimeErrorDetail(self.error)
        return self.runtime.start(*args)

    def mark(self, *args):
        if not self.runtime:
            raise RuntimeErrorDetail(self.error)
        return self.runtime.mark(*args)

    def watch_camera(self, name):
        return self.runtime.watch_camera(name) if self.runtime else nullcontext(False)

    def preview(self, name=None):
        return self.runtime.preview(name) if self.runtime else None

    def close(self):
        self.stop.set()
        self.worker.join(timeout=5)
        if self.runtime:
            self.runtime.close()


class RosRuntime:
    mode = "ros"

    def __init__(self, workspace_path):
        self.workspace = load_workspace_config(Path(workspace_path))
        # Each cell start regenerates the recorder configuration from the project's settings;
        # pick up changes (e.g. the camera frame rate) without restarting the application.
        self.generated_path = os.environ.get(
            "MRP_CELL_WORKSPACE_CONFIG", "/workspace/config/cell-rendered/workspace.yaml"
        )
        self.generated_mtime = None
        self.lock = threading.RLock()
        self.samples = {}
        self.robot_data = {}
        self.camera_times = deque(maxlen=120)
        self.source = "unknown"
        self.active_id = None
        self.handle = None
        self.preview_frames = {}
        self.camera_viewers = Counter()
        self.camera_subscriptions = {}
        self.metrics = {}
        self.metrics_at = 0
        self.external_state = None
        self._closed = False
        rclpy.init()
        self.node = Node("mrp_recording_application")
        self.record = ActionClient(self.node, RecordEpisode, "/platform/episode/record")
        self.marker = self.node.create_client(MarkEpisode, "/platform/episode/mark")
        self.parameters = AsyncParameterClient(self.node, "/control_arbiter")
        latched = QoSProfile(
            depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL
        )
        profile = self.workspace["profile"]
        self.controller_groups = profile["command_adapter"]["groups"]
        self.controller_clients = {
            group["name"]: ActionClient(
                self.node,
                ParallelGripperCommand if group["transport"] == "parallel_gripper_action" else GripperCommand,
                group["endpoint"],
            )
            for group in self.controller_groups
            if group["transport"] in ("gripper_action", "parallel_gripper_action")
        }
        self.sync_camera_subscriptions()
        self.subscriptions = [
            self.node.create_subscription(
                JointState,
                "/leader/joint_states",
                lambda msg: self.sample("Leader", msg),
                qos_profile_sensor_data,
            ),
            self.node.create_subscription(
                JointState,
                profile["state"]["topic"],
                lambda msg: self.sample("Follower", msg),
                qos_profile_sensor_data,
            ),
            self.node.create_subscription(
                JointIntent, profile["action"]["topic"], lambda msg: self.sample_action(msg), 10
            ),
            self.node.create_subscription(String, "/platform/control/active_source", self.on_source, latched),
            self.node.create_subscription(String, "/platform/episode/metrics", self.on_metrics, 10),
            self.node.create_subscription(EpisodeState, "/platform/episode/state", self.on_state, 10),
        ]
        self.executor = SingleThreadedExecutor()
        self.executor.add_node(self.node)
        self.thread = threading.Thread(target=self.executor.spin, daemon=True)
        self.thread.start()

    def refresh_workspace(self):
        try:
            mtime = Path(self.generated_path).stat().st_mtime
        except OSError:
            return
        if mtime == self.generated_mtime:
            return
        try:
            workspace = load_workspace_config(Path(self.generated_path))
        except (OSError, ValueError, KeyError):
            return  # keep the last good configuration
        if workspace["profile"]["cameras"][0] != self.workspace["profile"]["cameras"][0]:
            self.samples.pop("Webcam", None)
            self.camera_times.clear()
        self.workspace = workspace
        self.sync_camera_subscriptions()
        self.generated_mtime = mtime

    def sync_camera_subscriptions(self):
        cameras = self.workspace["profile"]["cameras"]
        primary = cameras[0]["name"]
        topics = {
            camera["name"]: camera["topic"]
            for camera in cameras
            if camera["name"] == primary or self.camera_viewers[camera["name"]]
        }
        for name, (topic, is_primary, subscription) in list(self.camera_subscriptions.items()):
            if topics.get(name) != topic or is_primary != (name == primary):
                self.node.destroy_subscription(subscription)
                del self.camera_subscriptions[name]
                self.preview_frames.pop(name, None)
        for name, topic in topics.items():
            if name not in self.camera_subscriptions:
                self.subscribe_camera(name, topic, name == primary)

    def subscribe_camera(self, name, topic, primary):
        def receive(message):
            with self.lock:
                if self.camera_subscriptions.get(name) == (topic, primary, subscription):
                    self.on_camera(name, message)

        qos = (
            qos_profile_sensor_data
            if primary
            else QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        )
        subscription = self.node.create_subscription(CompressedImage, topic, receive, qos)
        self.camera_subscriptions[name] = (topic, primary, subscription)

    @contextmanager
    def watch_camera(self, name):
        configured = False
        try:
            with self.lock:
                configured = not self._closed and any(
                    camera["name"] == name for camera in self.workspace["profile"]["cameras"]
                )
                if configured:
                    self.camera_viewers[name] += 1
                    self.sync_camera_subscriptions()
            yield configured
        finally:
            if configured:
                with self.lock:
                    self.camera_viewers[name] -= 1
                    if not self.camera_viewers[name]:
                        del self.camera_viewers[name]
                    if not self._closed:
                        self.sync_camera_subscriptions()

    def snapshot(self):
        result = copy.deepcopy(self.workspace)
        result["instruction"] = result["task"]["instruction"]
        result["minimum_duration_seconds"] = result["profile"].get("minimum_duration_seconds", 5)
        return result

    def sample(self, name, message):
        stamp = message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nanosec
        age = (self.node.get_clock().now().nanoseconds - stamp) / 1e9
        with self.lock:
            self.samples[name] = (time.monotonic(), -0.05 <= age <= 2)
            if name in ("Leader", "Follower"):
                self.store_robot_data(name, stamp, message.name, message.position, message.velocity)

    def store_robot_data(self, name, stamp, names, positions, velocities):
        def finite_values(values):
            return [float(value) if math.isfinite(value) else None for value in values]

        self.robot_data[name] = {
            "stamp_ns": stamp,
            "joint_names": list(names),
            "positions": finite_values(positions),
            "velocities": finite_values(velocities),
        }

    def on_camera(self, name, message):
        now = time.monotonic()
        if name == self.workspace["profile"]["cameras"][0]["name"]:
            self.sample("Webcam", message)
            self.camera_times.append(now)
        payload = message.data
        if len(payload) <= 2 * 1024 * 1024:
            # Keep the received JPEG buffer and defer copying it until a viewer reads it.
            self.preview_frames[name] = (now, payload)

    def sample_action(self, message):
        stamp = message.issued_at.sec * 1_000_000_000 + message.issued_at.nanosec
        age = (self.node.get_clock().now().nanoseconds - stamp) / 1e9
        with self.lock:
            self.samples["Action"] = (time.monotonic(), -0.05 <= age <= 2)
            self.store_robot_data("Action", stamp, message.joint_names, message.positions, message.velocities)
            self.robot_data["Action"]["source"] = message.source_id

    def on_source(self, message):
        with self.lock:
            self.source = message.data

    def on_metrics(self, message):
        try:
            payload = json.loads(message.data)
            if isinstance(payload, dict):
                with self.lock:
                    self.metrics = payload
                    self.metrics_at = time.monotonic()
        except ValueError:
            pass

    def on_state(self, message):
        ident = str(uuid.UUID(bytes=bytes(message.episode_id.uuid)))
        with self.lock:
            self.external_state = {"id": ident, "state": message.state, "summary": message.summary}

    def telemetry(self):
        with self.lock:
            now = time.monotonic()
            return {
                "robot_data": {
                    name: {
                        **data,
                        "fresh": name in self.samples
                        and now - self.samples[name][0] < 2
                        and self.samples[name][1],
                    }
                    for name, data in self.robot_data.items()
                }
            }

    def status(self):
        with self.lock:
            self.refresh_workspace()
            now = time.monotonic()
            checks = [
                {
                    "name": name,
                    "ready": name in self.samples
                    and now - self.samples[name][0] < 2
                    and self.samples[name][1],
                    "detail": (
                        "No fresh action; check teleoperation and leader/follower alignment"
                        if name == "Action"
                        else "Requires fresh receipt and source timestamp"
                    ),
                }
                for name in ("Leader", "Follower", "Webcam", "Action")
            ]
            rate = (
                (len(self.camera_times) - 1) / (self.camera_times[-1] - self.camera_times[0])
                if len(self.camera_times) > 1 and self.camera_times[-1] > self.camera_times[0]
                else 0
            )
            camera = self.workspace["profile"]["cameras"][0]
            rate_ready = len(self.camera_times) >= 30 and abs(rate - camera["fps"]) <= camera.get(
                "fps_tolerance", 0.6
            )
            checks.append(
                {
                    "name": "Camera rate",
                    "ready": rate_ready,
                    "detail": f"{rate:.1f} / {camera['fps']:.0f} FPS",
                }
            )
            names = {name for name, _ in self.node.get_node_names_and_namespaces()}
            recorder_ready = self.record.server_is_ready() and self.marker.service_is_ready()
            checks.extend(
                [
                    {
                        "name": "Recorder",
                        "ready": recorder_ready,
                        "detail": "Recording action and mark service",
                    },
                    {
                        "name": "Command bridge",
                        "ready": "joint_intent_bridge" in names,
                        "detail": "ROS node discovered",
                    },
                    {
                        "name": "Validator",
                        "ready": "episode_validator" in names,
                        "detail": "ROS node discovered",
                    },
                    {
                        "name": "Controller endpoints",
                        "ready": all(
                            self.controller_clients[group["name"]].server_is_ready()
                            if group["name"] in self.controller_clients
                            else self.node.count_subscribers(group["endpoint"]) > 0
                            for group in self.controller_groups
                        ),
                        "detail": "Configured arm/gripper endpoints discovered",
                    },
                ]
            )
            observed = now - self.metrics_at < 3
            # This recorder publishes STATE_PENDING with summary 'ready' at startup.
            busy = observed and self.metrics.get("state") in (2, 3, 5)
            checks.append(
                {
                    "name": "Recorder state",
                    "ready": observed and not busy,
                    "detail": "Busy" if busy else ("Observed idle" if observed else "Waiting for metrics"),
                }
            )
            external = self.external_state
            active = self.active_id
            if not active and busy:
                active = external["id"] if external else "external-recording"
            return {
                "checks": checks,
                "ready": all(item["ready"] for item in checks) and self.source == "teleop" and not active,
                "active_source": self.source,
                "active_episode_id": active,
                "cell_running": any(item["ready"] for item in checks[:3]),
                "message": "Recorder preflight is authoritative. Enable teleoperation explicitly.",
                "camera_previews": [camera["name"] for camera in self.workspace["profile"]["cameras"]],
                "external_state": external,
                "robot_data": {
                    name: {**data, "fresh": next(item["ready"] for item in checks if item["name"] == name)}
                    for name, data in self.robot_data.items()
                },
            }

    def select_source(self, source):
        if not self.parameters.services_are_ready():
            raise RuntimeErrorDetail("Control arbiter parameter service is unavailable.")
        result = await_future(self.parameters.set_parameters([Parameter("active_source", value=source)]))
        if not result.results or not result.results[0].successful:
            raise RuntimeErrorDetail(
                result.results[0].reason if result.results else "Source selection failed."
            )

    def start(self, episode_id, snapshot, completed):
        if not self.record.server_is_ready():
            raise RuntimeErrorDetail("Recording action is unavailable.")
        goal = RecordEpisode.Goal()
        set_uuid(goal.request_id, str(uuid.uuid4()))
        metadata = goal.metadata
        set_uuid(metadata.episode_id, episode_id)
        metadata.workcell_id = snapshot["id"]
        metadata.task_id = snapshot["task_id"]
        metadata.recording_profile_id = snapshot["recording_profile_id"]
        metadata.configuration.schema_id = "episode-recording"
        metadata.configuration.schema_version = "1.0.0"
        metadata.configuration.configuration_id = metadata.recording_profile_id
        metadata.configuration.content_hash = snapshot["configuration_hash"]
        producer = ProvenanceReference()
        producer.component.component_id = "episode_recorder"
        producer.component.name = "Episode Recorder"
        producer.component.semantic_version = "0.2.0"
        producer.component.source_revision = snapshot["producer"]["source_revision"]
        producer.component.build_id = producer.component.source_revision
        producer.configuration = metadata.configuration
        producer.calibration_id = snapshot["calibration"]["id"]
        producer.calibration_hash = snapshot["calibration"]["hash"]
        metadata.producers = [producer]
        metadata.calibration_ids = [producer.calibration_id]
        with self.lock:
            self.active_id = episode_id
        future = self.record.send_goal_async(goal)

        def accepted(done):
            try:
                handle = done.result()
                with self.lock:
                    self.handle = handle if handle.accepted else None
                    if not handle.accepted:
                        self.active_id = None
                if not handle.accepted:
                    return

                def finished(result_future):
                    try:
                        result = result_future.result().result
                        completed(episode_id, "recorded" if result.complete else "rejected", result.reason)
                    except Exception as exc:
                        completed(episode_id, "interrupted", str(exc))
                    finally:
                        with self.lock:
                            self.active_id = None
                            self.handle = None

                handle.get_result_async().add_done_callback(finished)
            except Exception as exc:
                completed(episode_id, "interrupted", str(exc))
                with self.lock:
                    self.active_id = None

        future.add_done_callback(accepted)
        handle = await_future(future)
        if not handle.accepted:
            raise RuntimeErrorDetail(
                "Recorder rejected the episode. Check recorder logs for its preflight reason "
                "(streams, camera rate, storage, or configuration)."
            )

    def mark(self, episode_id, kind, annotation=""):
        with self.lock:
            handle = self.handle
            active_id = self.active_id
        if active_id != episode_id or handle is None:
            raise RuntimeErrorDetail(
                "No controllable recording goal. Inspect the recorder after restart/timeouts."
            )
        if kind == "cancel":
            response = await_future(handle.cancel_goal_async())
            if not response.goals_canceling:
                raise RuntimeErrorDetail("Recorder did not accept cancellation.")
            return
        request = MarkEpisode.Request()
        set_uuid(request.request_id, str(uuid.uuid4()))
        set_uuid(request.episode_id, episode_id)
        request.source_id = "mrp_app"
        request.mark = {"success": 0, "failure": 1, "annotation": 2}[kind]
        request.annotation = annotation
        response = await_future(self.marker.call_async(request))
        if not response.accepted:
            raise RuntimeErrorDetail(response.reason)

    def preview(self, name=None):
        with self.lock:
            name = name if name is not None else self.workspace["profile"]["cameras"][0]["name"]
            frame = self.preview_frames.get(name)
            if frame is None:
                return None
            received_at, payload = frame
            if time.monotonic() - received_at >= 2:
                return None
            if not isinstance(payload, bytes):
                payload = bytes(payload)
                self.preview_frames[name] = (received_at, payload)
            return payload

    def close(self):
        with self.lock:
            if self._closed:
                return
            self._closed = True
        self.executor.shutdown(timeout_sec=3)
        self.thread.join(timeout=3)
        self.node.destroy_node()
        rclpy.shutdown()
