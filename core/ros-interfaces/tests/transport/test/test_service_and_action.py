import threading
import time

import rclpy
from platform_control_interfaces.srv import AcquireCommandLease
from platform_episode_interfaces.action import RecordEpisode
from rclpy.action import ActionClient, ActionServer, CancelResponse
from rclpy.executors import MultiThreadedExecutor


def uuid_values(seed):
    return [(seed + index) % 256 for index in range(16)]


def spin_in_thread(executor):
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()
    return thread


def test_acquire_lease_request_and_denied_response():
    rclpy.init()
    node = rclpy.create_node("lease_round_trip")
    observed = {}

    def callback(request, response):
        observed["source_id"] = request.source_id
        observed["target_id"] = request.target_id
        observed["duration"] = request.requested_duration.sec
        observed["request_id"] = list(request.request_id.uuid)
        response.request_id = request.request_id
        response.granted = False
        response.reason_code = 17
        response.reason = "target already leased"
        return response

    service = node.create_service(
        AcquireCommandLease, "/platform_interface_tests/acquire_lease", callback
    )
    client = node.create_client(
        AcquireCommandLease, "/platform_interface_tests/acquire_lease"
    )
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    thread = spin_in_thread(executor)
    try:
        assert client.wait_for_service(timeout_sec=2)
        request = AcquireCommandLease.Request()
        request.request_id.uuid = uuid_values(10)
        request.source_id = "retargeter"
        request.target_id = "left_arm"
        request.requested_duration.sec = 5
        future = client.call_async(request)
        deadline = time.monotonic() + 2
        while not future.done() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert future.done()
        response = future.result()
        assert observed == {
            "source_id": "retargeter",
            "target_id": "left_arm",
            "duration": 5,
            "request_id": uuid_values(10),
        }
        assert not response.granted
        assert response.reason_code == 17
        assert response.reason == "target already leased"
        assert list(response.request_id.uuid) == uuid_values(10)
    finally:
        executor.shutdown()
        thread.join(timeout=2)
        service.destroy()
        node.destroy_node()
        rclpy.shutdown()


def test_record_episode_feedback_cancel_and_partial_result():
    rclpy.init()
    server_node = rclpy.create_node("record_episode_server")
    client_node = rclpy.create_node("record_episode_client")
    cancellation_seen = threading.Event()

    def cancel_callback(_goal):
        return CancelResponse.ACCEPT

    def execute_callback(goal_handle):
        for index in range(2):
            feedback = RecordEpisode.Feedback()
            feedback.episode_id = goal_handle.request.metadata.episode_id
            feedback.state = 2
            feedback.bytes_recorded = (index + 1) * 1024
            feedback.summary = "recording"
            goal_handle.publish_feedback(feedback)
            time.sleep(0.05)
        deadline = time.monotonic() + 2
        while not goal_handle.is_cancel_requested and time.monotonic() < deadline:
            time.sleep(0.01)
        if goal_handle.is_cancel_requested:
            cancellation_seen.set()
            goal_handle.canceled()
        result = RecordEpisode.Result()
        result.request_id = goal_handle.request.request_id
        result.episode_id = goal_handle.request.metadata.episode_id
        result.complete = False
        result.artifact_disposition = RecordEpisode.Result.ARTIFACT_PARTIAL_RETAINED
        result.artifact_id = "partial-episode"
        result.artifact_uri = "artifact://partial-episode"
        result.content_hash = "sha256:partial"
        result.reason_code = 1
        result.reason = "canceled by client"
        return result

    server = ActionServer(
        server_node,
        RecordEpisode,
        "/platform_interface_tests/record_episode",
        execute_callback=execute_callback,
        cancel_callback=cancel_callback,
    )
    client = ActionClient(
        client_node, RecordEpisode, "/platform_interface_tests/record_episode"
    )
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(server_node)
    executor.add_node(client_node)
    thread = spin_in_thread(executor)
    feedback = []
    try:
        assert client.wait_for_server(timeout_sec=2)
        goal = RecordEpisode.Goal()
        goal.request_id.uuid = uuid_values(20)
        goal.metadata.episode_id.uuid = uuid_values(40)
        goal.metadata.workcell_id = "lab-1"
        goal.metadata.task_id = "pick-cube"
        goal.metadata.recording_profile_id = "default"
        sent = client.send_goal_async(
            goal, feedback_callback=lambda event: feedback.append(event.feedback)
        )
        deadline = time.monotonic() + 2
        while not sent.done() and time.monotonic() < deadline:
            time.sleep(0.01)
        handle = sent.result()
        assert handle.accepted
        deadline = time.monotonic() + 2
        while len(feedback) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(feedback) >= 2
        canceled = handle.cancel_goal_async()
        deadline = time.monotonic() + 2
        while not canceled.done() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert canceled.done()
        result_future = handle.get_result_async()
        deadline = time.monotonic() + 2
        while not result_future.done() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert result_future.done()
        result = result_future.result().result
        assert cancellation_seen.is_set()
        assert not result.complete
        assert (
            result.artifact_disposition
            == RecordEpisode.Result.ARTIFACT_PARTIAL_RETAINED
        )
        assert result.artifact_id == "partial-episode"
        assert list(result.request_id.uuid) == uuid_values(20)
        assert list(result.episode_id.uuid) == uuid_values(40)
    finally:
        server.destroy()
        executor.shutdown()
        thread.join(timeout=2)
        client_node.destroy_node()
        server_node.destroy_node()
        rclpy.shutdown()
