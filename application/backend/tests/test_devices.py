import json
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parent.parent
sys.path[:0] = [str(BASE / "deployment"), str(ROOT / "core/cell_config")]
try:
    import agent
    import devices
except ModuleNotFoundError as exc:  # workspace dependency (cell_config) not on the path
    raise unittest.SkipTest(f"MRP workspace dependency not available: {exc.name}") from exc


def fake_sysfs(root, serial="ABC123"):
    """One CH340-style serial bridge, an external USB camera and an integrated camera."""
    usb = root / "devices/usb1/1-1"
    usb.mkdir(parents=True)
    for name, value in {
        "idVendor": "1a86",
        "idProduct": "55d3",
        "serial": serial,
        "removable": "removable",
    }.items():
        (usb / name).write_text(value)
    arm = usb / "1-1:1.0"
    arm.mkdir()
    second = root / "devices/usb1/1-2"
    second.mkdir()
    for name, value in {
        "idVendor": "1a86",
        "idProduct": "55d3",
        "serial": "XYZ789",
        "removable": "removable",
    }.items():
        (second / name).write_text(value)
    arm2 = second / "1-2:1.0"
    arm2.mkdir()
    for node, target in (("ttyACM0", arm), ("ttyACM1", arm2)):
        (root / "class/tty" / node).mkdir(parents=True)
        (root / "class/tty" / node / "device").symlink_to(target)
    fixed = root / "devices/usb1/1-5"
    fixed.mkdir()
    (fixed / "idVendor").write_text("04f2")
    (fixed / "removable").write_text("fixed")
    integrated = fixed / "1-5:1.0"
    integrated.mkdir()
    external = root / "devices/usb1/1-3"
    external.mkdir()
    (external / "idVendor").write_text("0c45")
    (external / "removable").write_text("removable")
    cam = external / "1-3:1.0"
    cam.mkdir()
    for node, target, name, index in (
        ("video0", integrated, "Integrated Camera", "0"),
        ("video2", cam, "USB2.0 Camera", "0"),
        ("video3", cam, "USB2.0 Camera", "1"),
    ):
        folder = root / "class/video4linux" / node
        folder.mkdir(parents=True)
        (folder / "name").write_text(name)
        (folder / "index").write_text(index)
        (folder / "device").symlink_to(target)


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.sys = Path(self.temp.name)
        fake_sysfs(self.sys)

    def tearDown(self):
        self.temp.cleanup()

    def test_scan_lists_arms_and_sorts_external_cameras_first(self):
        report = devices.scan(str(self.sys))
        self.assertEqual([p["port"] for p in report["serial"]], ["/dev/ttyACM0", "/dev/ttyACM1"])
        self.assertTrue(all(p["likely_so101"] for p in report["serial"]))
        cameras = report["video"]
        self.assertEqual(
            [c["device"] for c in cameras], ["/dev/video2", "/dev/video0"]
        )  # metadata node dropped
        self.assertFalse(cameras[0]["integrated"])
        self.assertTrue(cameras[1]["integrated"])

    def test_empty_scan_explains_how_to_attach_usb(self):
        with tempfile.TemporaryDirectory() as empty:
            hints = " ".join(devices.scan(empty)["hints"])
        self.assertIn("serial", hints)
        self.assertIn("camera", hints)

    def test_selection_is_resolved_by_serial_when_numbering_changes(self):
        saved = {"port": "/dev/ttyACM7", "serial": "XYZ789"}
        self.assertEqual(devices.resolve(saved, "leader", str(self.sys)), "/dev/ttyACM1")
        with self.assertRaises(ValueError):
            devices.resolve({"port": "/dev/ttyACM9"}, "leader", str(self.sys))
        with self.assertRaises(ValueError):  # a path that is not in the scan is never accepted
            devices.resolve({"port": "/dev/sda"}, "leader", str(self.sys))

    def test_identify_suggests_the_arm_that_moved(self):
        def run(command, **_):
            port = command[command.index("--device") + 1].split(":")[0]
            travel = 900 if port.endswith("0") else 10
            return subprocess.CompletedProcess(command, 0, json.dumps({"total_travel": travel}), "")

        report = devices.identify_leader(["/dev/ttyACM0", "/dev/ttyACM1"], ROOT / "driver", 2, run)
        self.assertEqual(report["suggested_leader"], "/dev/ttyACM0")
        self.assertEqual(report["suggested_follower"], "/dev/ttyACM1")

        def still(command, **_):
            return subprocess.CompletedProcess(command, 0, json.dumps({"total_travel": 20}), "")

        self.assertIsNone(
            devices.identify_leader(["/dev/ttyACM0", "/dev/ttyACM1"], ROOT / "driver", 2, still)[
                "suggested_leader"
            ]
        )

    def test_probe_container_gets_only_the_one_device_and_no_network(self):
        seen = {}

        def run(command, **_):
            seen["command"] = command
            return subprocess.CompletedProcess(command, 0, json.dumps({"ok": True, "servos": []}), "")

        devices.probe_arm("/dev/ttyACM0", ROOT / "driver", run=run)
        command = seen["command"]
        self.assertEqual(command[command.index("--network") + 1], "none")
        self.assertEqual(command.count("--device"), 1)
        self.assertNotIn("--privileged", command)
        self.assertNotIn("/dev:/dev", " ".join(command))


class FakeCompose:
    """Stands in for ComposePreset so gating tests never reach Docker.

    It renders the plan Compose would: the approved services, with real backends and device
    mappings depending on which overlay files the agent put on the command line.
    """

    calls = []

    def __init__(self, project, files=()):
        self.project, self.files, self.lock = project, list(files), threading.Lock()

    def has(self, overlay):
        return any(overlay in str(f) for f in self.files)

    def run(self, action, doc=None, env=None):
        FakeCompose.calls.append((action, env))
        if action != "plan":
            return subprocess.CompletedProcess([], 0, "", "")
        from mrp_app.deployment import PRESET_SERVICES

        env = env or {}
        services = {name: {} for name in PRESET_SERVICES["mock-so101"]}
        for role, overlay, variable in (
            ("leader", "real_leader", "LEADER_PORT"),
            ("follower", "real_follower", "FOLLOWER_PORT"),
        ):
            real = self.has(overlay)
            services[role] = {"environment": {"BACKEND": "real" if real else "mock"}}
            if real:
                services[role]["devices"] = [{"source": env[variable], "target": env[variable]}]
        if self.has("usb_camera"):
            services["camera"] = {
                "devices": [{"source": env["CAMERA_DEVICE"], "target": env["CAMERA_DEVICE"]}]
            }
        for role, variable in agent.IMAGE_ENV.items():
            if variable in env:
                services[agent.SERVICE_FOR_ROLE[role]]["image"] = env[variable]
        # The agent's generated overlay for extra arms and cameras merges like Compose merges files.
        for overlay in (f for f in self.files if str(f).endswith(".cell.json")):
            for name, service in json.loads(Path(overlay).read_text())["services"].items():
                merged = services.setdefault(name, {})
                environment = {**merged.get("environment", {}), **service.get("environment", {})}
                merged.update(service)
                if environment:
                    merged["environment"] = environment
                merged["volumes"] = [  # Compose reports volumes in their long form
                    {"type": "bind" if v.startswith((".", "/")) else "volume", "source": v.split(":")[0],
                     "target": v.split(":")[1] if ":" in v else ""}
                    if isinstance(v, str) else v
                    for v in merged.get("volumes", [])
                ]  # fmt: skip
        return subprocess.CompletedProcess([], 0, json.dumps({"services": services}), "")


class AgentGateTests(unittest.TestCase):
    PROBE = {
        "ok": True, "problems": [], "voltage_v": 7.0, "torque_enabled": False,
        "servos": [{"id": i, "present": True, "position": 2048, "is_sts3215": True} for i in range(1, 7)],
    }  # fmt: skip

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sys = Path(self.temp.name) / "sys"
        fake_sysfs(self.sys)

        def runner(command, **_):
            if command[:2] == ["docker", "pull"]:
                self.pulls.append(command[-1])
                return subprocess.CompletedProcess(command, int(self.pull_fails), "", "pull failed")
            if "ls" in command:
                return subprocess.CompletedProcess(command, 0, "leader.yaml\nfollower.yaml\n", "")
            if "render_cell_config.py" in " ".join(command):
                self.renders.append(json.loads(command[command.index("/src/render_cell_config.py") + 2]))
                return subprocess.CompletedProcess(command, 0, "sha256:abc", "")
            if "camera_probe.py" in " ".join(command):
                device = command[command.index("--device") + 1].split(":")[0]
                width, height = (
                    int(command[command.index("--width") + 1]),
                    int(command[command.index("--height") + 1]),
                )
                fps = self.measured_fps.get(device, 30.0)
                return subprocess.CompletedProcess(
                    command,
                    0,
                    json.dumps(
                        {"ok": True, "width": width, "height": height, "fps": fps, "resolution_ok": True}
                    ),
                    "",
                )
            return subprocess.CompletedProcess(command, 0, json.dumps(self.PROBE), "")

        self.renders = []
        self.pulls = []
        self.pull_fails = False
        self.measured_fps = {}
        FakeCompose.calls = self.calls = []
        self.fake = FakeCompose  # `.calls` is shared by the base presets and the device variants
        self.addCleanup(setattr, agent, "ComposePreset", agent.ComposePreset)
        agent.ComposePreset = lambda files, project: FakeCompose(project, files)
        presets = {
            "mock-so101": FakeCompose("mrp-mock-so101"),
            "hwleader-so101": FakeCompose("mrp-mock-so101"),
            "real-so101": FakeCompose("mrp-mock-so101"),
        }
        self.server = agent.make_server(
            presets,
            Path(self.temp.name) / "exports",
            port=0,
            workspace_root=ROOT,
            sys_root=str(self.sys),
            runner=runner,
        )
        self.server.allowed_hosts = {"127.0.0.1"}
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)

        def stop():
            if thread.is_alive():
                self.server.shutdown()
                thread.join(timeout=5)

        self.addCleanup(stop)
        thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def post(self, path, body):
        request = Request(self.url + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.load(exc)

    DEVICES = {
        "leader": {"port": "/dev/ttyACM0", "serial": "ABC123"},
        "follower": {"port": "/dev/ttyACM1", "serial": "XYZ789"},
    }

    def test_export_passes_frame_stride_to_converter(self):
        job = str(uuid.uuid4())
        folder = Path(self.temp.name) / "exports" / job
        folder.mkdir(parents=True)
        (folder / "accepted.json").write_text("{}")
        with (
            patch.object(FakeCompose, "command", create=True, side_effect=lambda *args: list(args)),
            patch("agent.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run,
        ):
            status, body = self.post(
                "/api/v1/exports", {"job_id": job, "repo_id": "local/test", "downsample_hz_ratio": 2}
            )
        self.assertEqual(status, 200, body)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--downsample-hz-ratio") + 1], "2")
        status, _ = self.post(
            "/api/v1/exports", {"job_id": job, "repo_id": "local/test", "downsample_hz_ratio": True}
        )
        self.assertEqual(status, 400)

    def test_custom_images_are_pulled_and_applied_to_the_plan(self):
        status, body = self.post(
            "/api/v1/deployment/up",
            {"preset": "mock-so101", "images": {"leader": "acme/robot:v1"}},
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(self.pulls, ["acme/robot:v1"])
        self.assertEqual(self.calls[-1][1]["MRP_LEADER_IMAGE"], "acme/robot:v1")
        status, _ = self.post(
            "/api/v1/deployment/up", {"preset": "mock-so101", "images": {"leader": "bad;image"}}
        )
        self.assertEqual(status, 400)
        self.pull_fails = True
        self.calls.clear()
        status, body = self.post(
            "/api/v1/deployment/up", {"preset": "mock-so101", "images": {"camera": "acme/camera:v1"}}
        )
        self.assertEqual(status, 400)
        self.assertIn("Could not pull", body["error"])
        self.assertNotIn("up", [call[0] for call in self.calls])

    def test_real_hardware_needs_confirmation_and_a_fresh_passing_test(self):
        up = {
            "preset": "hwleader-so101",
            "task_id": "pipeline_check",
            "devices": {"leader": self.DEVICES["leader"]},
        }
        status, body = self.post("/api/v1/deployment/up", up)
        self.assertEqual(status, 400)
        self.assertIn("confirmation", body["error"])
        status, body = self.post("/api/v1/deployment/up", {**up, "operator_confirmed": True})
        self.assertEqual(status, 400)
        self.assertIn("connection test", body["error"])
        status, body = self.post(
            "/api/v1/devices/test", {"preset": "hwleader-so101", "devices": up["devices"]}
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["passed"], body["checks"])
        status, body = self.post("/api/v1/deployment/up", {**up, "operator_confirmed": True})
        self.assertEqual(status, 200, body)
        action, env = self.fake.calls[-1]
        self.assertEqual(action, "up")
        self.assertEqual(env["LEADER_PORT"], "/dev/ttyACM0")

    def test_a_different_device_selection_invalidates_the_test(self):
        base = {"preset": "hwleader-so101", "task_id": "pipeline_check"}
        self.post("/api/v1/devices/test", {**base, "devices": {"leader": self.DEVICES["leader"]}})
        other = {"leader": {"port": "/dev/ttyACM1", "serial": "XYZ789"}}
        status, body = self.post(
            "/api/v1/deployment/up", {**base, "devices": other, "operator_confirmed": True}
        )
        self.assertEqual(status, 400)
        self.assertIn("connection test", body["error"])

    def test_unknown_or_unscanned_devices_and_extra_fields_are_rejected(self):
        base = {"preset": "hwleader-so101", "task_id": "pipeline_check", "operator_confirmed": True}
        for devices_body in (
            {"leader": {"port": "/dev/ttyACM9"}},  # not connected
            {"leader": {"port": "/etc/passwd"}},  # not a device path
            {},  # nothing selected
        ):
            status, _ = self.post("/api/v1/deployment/up", {**base, "devices": devices_body})
            self.assertEqual(status, 400, devices_body)
        status, _ = self.post("/api/v1/deployment/up", {**base, "devices": self.DEVICES, "extra": 1})
        self.assertEqual(status, 400)

    def test_mock_cells_never_need_devices_or_confirmation(self):
        status, _ = self.post("/api/v1/deployment/up", {"preset": "mock-so101", "task_id": "pipeline_check"})
        self.assertEqual(status, 200)
        status, _ = self.post(
            "/api/v1/deployment/up",
            {"preset": "mock-so101", "task_id": "pipeline_check", "devices": self.DEVICES},
        )
        self.assertEqual(status, 400)

    def test_mock_motion_enables_the_compose_profile_but_not_with_a_real_leader(self):
        ok, _ = self.post(
            "/api/v1/deployment/up",
            {"preset": "mock-so101", "task_id": "pipeline_check", "mock_motion": True},
        )
        self.assertEqual(ok, 200)
        self.assertEqual(self.fake.calls[-1][1]["COMPOSE_PROFILES"], "motion")
        bad, _ = self.post(
            "/api/v1/deployment/up",
            {"preset": "hwleader-so101", "task_id": "pipeline_check", "mock_motion": True},
        )
        self.assertEqual(bad, 400)

    def test_every_mock_start_generates_the_recording_config_from_settings(self):
        settings = {
            "camera": {"fps": 25, "width": 1280, "height": 720},
            "side_camera": {"enabled": True, "source": "synthetic", "fps": 15},
            "recording": {
                "minimum_duration_seconds": 8,
                "instruction": "Stack the blocks",
                "maximum_camera_gap_ms": 150,
            },
            "mock_motion": {"seed": 7, "speed": 2, "mode": "sine"},  # a whole number, as the UI can send
        }
        status, body = self.post(
            "/api/v1/deployment/up",
            {"preset": "mock-so101", "task_id": "pipeline_check", "mock_motion": True, "settings": settings},
        )
        self.assertEqual(status, 200, body)
        params = self.renders[-1]
        self.assertEqual([c["name"] for c in params["cameras"]], ["webcam", "side"])
        self.assertEqual((params["cameras"][0]["width"], params["cameras"][0]["fps"]), (1280, 25))
        self.assertEqual(params["recording"]["minimum_duration_seconds"], 8)
        self.assertEqual(params["recording"]["maximum_camera_gap_ms"], 150)
        self.assertEqual(params["instruction"], "Stack the blocks")
        self.assertEqual(params["robot"], "sim")
        self.assertEqual(params["robot_profile"]["id"], "so101")
        self.assertEqual(params["teleop"]["validity_ms"], 80)  # defaults when the UI sends none
        env = self.fake.calls[-1][1]
        self.assertEqual((env["CAMERA_FPS"], env["CAMERA2_FPS"]), ("25", "15"))
        self.assertEqual(env["COMPOSE_PROFILES"], "motion,side")
        self.assertEqual((env["MOCK_MOTION_SEED"], env["MOCK_MOTION_MODE"]), ("7", "sine"))
        # ROS types `-p speed:=2` as an integer and rejects it for a float parameter.
        self.assertEqual(env["MOCK_MOTION_SPEED"], "2.0")

    def test_teleop_settings_reach_the_renderer(self):
        teleop = {"source_timeout_ms": 500, "joint_mapping": {"gripper_joint": {"scale": -1.0}}}
        status, body = self.post(
            "/api/v1/deployment/up",
            {"preset": "mock-so101", "task_id": "pipeline_check", "settings": {"teleop": teleop}},
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(self.renders[-1]["teleop"]["source_timeout_ms"], 500)
        self.assertEqual(self.renders[-1]["teleop"]["joint_mapping"], {"gripper_joint": {"scale": -1.0}})

    def test_robot_profiles_are_served(self):
        with urlopen(self.url + "/api/v1/robots", timeout=10) as response:
            profiles = json.load(response)
        self.assertEqual(profiles["so101"]["joint_names"][0], "shoulder_pan_joint")

    def test_invalid_settings_are_rejected(self):
        for bad in (
            {"camera": {"fps": 500}}, {"unknown": {}}, {"camera": {"width": "wide"}},
            {"teleop": {"validity_ms": 1}}, {"teleop": {"joint_mapping": {"j": {"scale": 0}}}},
            {"teleop": {"joint_mapping": {"j": {"offset": 1}}}},
        ):  # fmt: skip
            status, _ = self.post(
                "/api/v1/deployment/up",
                {"preset": "mock-so101", "task_id": "pipeline_check", "settings": bad},
            )
            self.assertEqual(status, 400, bad)

    def test_camera_fps_test_follows_the_configured_rate_and_changing_it_needs_a_new_test(self):
        base = {
            "preset": "mock-so101",
            "task_id": "pipeline_check",
            "camera": "opencv_usb",
            "devices": {"camera": {"device": "/dev/video2"}},
        }
        self.measured_fps["/dev/video2"] = 25.0
        status, body = self.post("/api/v1/devices/test", {**base, "settings": {"camera": {"fps": 30}}})
        rate = [c for c in body["checks"] if c["name"] == "Camera frame rate"][0]
        self.assertFalse(rate["ok"])
        self.assertEqual((rate["measured_fps"], rate["target_fps"]), (25.0, 30))
        status, body = self.post("/api/v1/devices/test", {**base, "settings": {"camera": {"fps": 25}}})
        self.assertTrue(body["passed"], body["checks"])

    def test_two_usb_cameras_and_calibration_import(self):
        base = {
            "preset": "mock-so101", "task_id": "pipeline_check", "camera": "opencv_usb",
            "settings": {"side_camera": {"enabled": True, "source": "opencv_usb"}},
            "devices": {"camera": {"device": "/dev/video2"}, "side_camera": {"device": "/dev/video2"}},
        }  # fmt: skip
        self.assertEqual(self.post("/api/v1/deployment/up", base)[0], 400)  # same node twice
        sysfs_extra = self.sys / "class/video4linux/video4"
        sysfs_extra.mkdir(parents=True)
        (sysfs_extra / "name").write_text("Second")
        (sysfs_extra / "index").write_text("0")
        (sysfs_extra / "device").symlink_to(self.sys / "devices/usb1/1-3/1-3:1.0")
        base["devices"]["side_camera"] = {"device": "/dev/video4"}
        status, body = self.post("/api/v1/deployment/up", base)
        self.assertEqual(status, 200, body)
        self.assertEqual(self.fake.calls[-1][1]["CAMERA2_DEVICE"], "/dev/video4")
        good = (
            "joints:\n"
            + "\n".join(f"  {n}: {{id: {i}, homing_offset: 0}}" for i, n in enumerate(devices.JOINT_IDS, 1))
            + "\n"
        )
        self.assertEqual(
            self.post("/api/v1/devices/import-calibration", {"name": "leader.yaml", "content": good})[0], 200
        )
        for bad in ({"name": "../x.yaml", "content": good}, {"name": "x.yaml", "content": "evil: true"}):
            self.assertEqual(self.post("/api/v1/devices/import-calibration", bad)[0], 400)

    def test_usb_camera_selection_resolves_the_external_camera(self):
        body = {
            "preset": "mock-so101",
            "task_id": "pipeline_check",
            "camera": "opencv_usb",
            "devices": {"camera": {"device": "/dev/video2"}},
        }
        status, _ = self.post("/api/v1/deployment/up", body)
        self.assertEqual(status, 200)
        self.assertEqual(self.fake.calls[-1][1]["CAMERA_DEVICE"], "/dev/video2")
        body["devices"] = {"camera": {"device": "/dev/video3"}}  # metadata node, not in the scan
        self.assertEqual(self.post("/api/v1/deployment/up", body)[0], 400)


if __name__ == "__main__":
    unittest.main()
