"""Cells with several leaders/followers and any number of cameras."""

import copy
import json
import subprocess
import sys
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mrp_app import components
from mrp_app.catalog import CellSpecError, validate_settings, validate_spec
from mrp_app.deployment import PRESET_SERVICES, check_plan

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parent.parent
sys.path[:0] = [str(BASE / "deployment/mock-cell")]
import arm_merge  # noqa: E402 - pure module next to the adapter node


def arm(ident, role, backend="mock", **extra):
    return {"id": ident, "role": role, "backend": backend, **extra}


TWO_FOLLOWERS = [
    arm("leader_l", "leader"),
    arm("leader_r", "leader"),
    arm("left", "follower", leader="leader_l"),
    arm("right", "follower", leader="leader_r"),
]
THREE_CAMERAS = [
    {"id": "top", "source": "synthetic"},
    {"id": "front", "source": "synthetic", "fps": 15},
    {"id": "wrist", "source": "synthetic", "width": 320, "height": 240},
]


def cell(**extra):
    return {"task_id": "pipeline_check", "arms": TWO_FOLLOWERS, "cameras": THREE_CAMERAS, **extra}


class SpecTests(unittest.TestCase):
    def test_lists_stand_for_the_single_pair_keys_and_pick_the_preset(self):
        spec, preset = validate_spec(cell())
        self.assertEqual(preset, "mock-so101")
        self.assertEqual((spec["leader"], spec["follower"], spec["camera"]), ("mock", "mock", "synthetic"))
        self.assertEqual(
            spec["cameras"][1],
            {
                "id": "front",
                "source": "synthetic",
                "model": "opencv_usb",
                "width": 640,
                "height": 480,
                "fps": 15,
            },
        )
        real = copy.deepcopy(TWO_FOLLOWERS)
        real[0]["backend"] = real[2]["backend"] = "real"
        _, preset = validate_spec(cell(arms=real, task_id="free_teleop"))
        self.assertEqual(preset, "real-so101")  # one real pair, one mock pair
        real[2]["backend"] = "mock"
        _, preset = validate_spec(cell(arms=real))
        self.assertEqual(preset, "hwleader-so101")

    def test_one_list_can_be_combined_with_the_original_keys(self):
        _, preset = validate_spec(
            {"leader": "mock", "follower": "mock", "task_id": "pipeline_check", "cameras": THREE_CAMERAS}
        )
        self.assertEqual(preset, "mock-so101")
        spec, _ = validate_spec({"camera": "synthetic", "task_id": "pipeline_check", "arms": TWO_FOLLOWERS})
        self.assertEqual(spec["leader"], "mock")

    def test_invalid_lists_are_rejected_with_a_reason(self):
        follower = TWO_FOLLOWERS[2]
        cases = [
            (cell(arms=[TWO_FOLLOWERS[0]]), "2 to 8"),
            (cell(arms=[TWO_FOLLOWERS[0], TWO_FOLLOWERS[1]]), "1 to 4 followers"),
            (cell(arms=[*TWO_FOLLOWERS[:3], {**follower, "id": "right"}, {**follower, "id": "right"}]), "used twice"),
            (cell(arms=[*TWO_FOLLOWERS[:2], {**follower, "leader": "nobody"}]), "not a leader"),
            (cell(arms=[*TWO_FOLLOWERS[:2], {k: v for k, v in follower.items() if k != "leader"}]), "choose which leader"),
            (cell(arms=[*TWO_FOLLOWERS[:3]]), "drives no follower"),
            (cell(arms=[TWO_FOLLOWERS[0], arm("f", "follower", "real")]), "real leader"),
            (cell(arms=[TWO_FOLLOWERS[0], arm("f", "follower", device={"port": "/dev/ttyACM0"})]), "only used by a real arm"),
            (cell(arms=[TWO_FOLLOWERS[0], arm("f", "follower", model="ur")]), "planned"),
            (cell(arms=[TWO_FOLLOWERS[0], arm("Bad-Id", "follower")]), "lowercase"),
            (cell(arms=[TWO_FOLLOWERS[0], arm("adapter", "follower")]), "lowercase"),
            (cell(arms=[*TWO_FOLLOWERS[:3], arm("g", "follower", "gazebo", leader="leader_r")]), "Gazebo"),
            (cell(cameras=[]), "at least one"),
            (cell(cameras=[{"id": f"c{i}", "source": "synthetic"} for i in range(7)]), "1 to 6"),
            (cell(cameras=[THREE_CAMERAS[0], THREE_CAMERAS[0]]), "used twice"),
            (cell(cameras=[{"id": "top", "source": "synthetic", "fps": 500}]), "fps"),
            (cell(cameras=[{"id": "top", "source": "synthetic", "device": {"device": "/dev/video2"}}]), "real camera"),
            (cell(cameras=[{"id": "a", "source": "opencv_usb", "device": {"device": "/dev/video2"}},
                           {"id": "b", "source": "opencv_usb", "device": {"device": "/dev/video2"}}]), "different video"),
            (cell(leader="real"), "leader must be 'mock'"),
            (cell(leader_model="so101"), "own model"),
            (cell(devices={"leader": {"port": "/dev/ttyACM0"}}), "own model and device"),
            (cell(devices={"camera": {"device": "/dev/video2"}}), "own device"),
            (cell(settings={"side_camera": {"enabled": True}}), "side camera"),
            (cell(settings={"teleop": {"joint_mapping": {"gripper_joint": {"scale": -1}}}}), "joint_mapping"),
        ]  # fmt: skip
        for spec, message in cases:
            with self.subTest(message=message), self.assertRaises(CellSpecError) as error:
                validate_spec(spec)
            self.assertIn(message, str(error.exception))
        ports = [
            arm("l", "leader", "real", device={"port": "/dev/ttyACM0"}),
            arm("f", "follower", "real", device={"port": "/dev/ttyACM0"}),
        ]
        with self.assertRaises(CellSpecError):
            validate_spec(cell(arms=ports, task_id="free_teleop"))

    def test_legacy_and_listed_single_pairs_keep_the_original_topology(self):
        legacy = {"leader": "mock", "follower": "mock", "camera": "synthetic", "task_id": "pipeline_check"}
        spec, _ = validate_spec(legacy)
        topo = components.topology(components.expand(spec, validate_settings(None)))
        self.assertFalse(topo["multi_arm"])
        self.assertEqual(
            [(a["service"], a["namespace"]) for a in topo["arms"]], [("leader", "leader"), ("follower", "")]
        )
        self.assertEqual(topo["arms"][1]["intent_topic"], "/platform/control/joint_intent")
        self.assertEqual([c["topic"] for c in topo["cameras"]], ["/webcam/image/compressed"])
        spec, _ = validate_spec(
            cell(arms=[arm("a", "leader"), arm("b", "follower")], cameras=THREE_CAMERAS[:1])
        )
        topo = components.topology(components.expand(spec, validate_settings(spec.get("settings"))))
        self.assertEqual(topo["arms"][1]["joint_states_topic"], "/joint_states")

    def test_multi_arm_topology_namespaces_every_arm(self):
        spec, _ = validate_spec(cell())
        topo = components.topology(components.expand(spec, validate_settings(spec.get("settings"))))
        self.assertTrue(topo["multi_arm"])
        services = {a["id"]: (a["service"], a["namespace"], a.get("bridge")) for a in topo["arms"]}
        self.assertEqual(services["leader_l"], ("leader", "arm_leader_l", None))
        self.assertEqual(services["leader_r"], ("arm_leader_r", "arm_leader_r", None))
        self.assertEqual(services["left"], ("follower", "arm_left", "bridge"))
        self.assertEqual(services["right"], ("arm_right", "arm_right", "bridge_right"))
        self.assertEqual(
            [(c["service"], c["env_prefix"], c["topic"]) for c in topo["cameras"]],
            [("camera", "CAMERA", "/top/image/compressed"), ("camera2", "CAMERA2", "/front/image/compressed"),
             ("camera_wrist", None, "/wrist/image/compressed")],
        )  # fmt: skip

    def test_real_arms_get_one_calibration_file_each(self):
        arms = [
            arm("l", "leader", "real", device={"port": "/dev/ttyACM0"}),
            arm("a", "follower", "real", device={"port": "/dev/ttyACM1"}),
            arm("b", "follower", "real", device={"port": "/dev/ttyACM2", "calibration": "mine.yaml"}),
        ]
        spec, _ = validate_spec(cell(arms=arms, task_id="free_teleop"))
        expanded = components.expand(spec, validate_settings(spec.get("settings")))
        self.assertEqual(
            [a["device"]["calibration"] for a in expanded["arms"]], ["leader.yaml", "a.yaml", "mine.yaml"]
        )


class PlanBoundaryTests(unittest.TestCase):
    def plan(self, preset, extra_services=(), **services):
        names = PRESET_SERVICES[preset] | set(extra_services)
        plan = {"services": {name: {} for name in names}}
        for name in ("leader", "follower"):
            plan["services"][name] = {"environment": {"BACKEND": "mock"}}
        for name, service in services.items():
            plan["services"][name] = service
        return plan

    def test_extra_services_must_be_announced_and_named_like_cell_components(self):
        arms = {"leader": ("leader", "mock"), "follower": ("follower", "mock"), "arm_b": ("follower", "mock")}
        extra = {"services": {"arm_b", "bridge_b", "arm_adapter", "camera_top"}, "arms": arms}
        plan = self.plan("mock-so101", extra["services"], arm_b={"environment": {"BACKEND": "mock"}})
        self.assertEqual(check_plan(plan, "mock-so101", None, extra), plan)
        with self.assertRaises(ValueError):  # not announced by the agent
            check_plan(plan, "mock-so101")
        with self.assertRaises(ValueError):
            check_plan(self.plan("mock-so101", {"evil"}), "mock-so101", None, {"services": {"evil"}})
        with self.assertRaises(ValueError):  # extra arm service without the expected backend
            check_plan(self.plan("mock-so101", extra["services"]), "mock-so101", None, extra)

    def test_presets_bound_what_each_arm_service_may_run(self):
        arms = {"leader": ("leader", "real"), "follower": ("follower", "mock"), "arm_b": ("follower", "real")}
        extra = {"services": {"arm_b"}, "arms": arms}
        plan = self.plan(
            "real-so101", {"arm_b"},
            leader={"environment": {"BACKEND": "real"}, "devices": ["/dev/ttyACM0:/dev/ttyACM0"]},
            arm_b={"environment": {"BACKEND": "real"}, "devices": ["/dev/ttyACM1:/dev/ttyACM1"]},
        )  # fmt: skip
        devices = {"leader": "/dev/ttyACM0", "arm_b": "/dev/ttyACM1"}
        self.assertEqual(check_plan(plan, "real-so101", devices, extra), plan)
        with self.assertRaises(ValueError):  # a real follower is never allowed in the leader-only preset
            check_plan(plan, "hwleader-so101", devices, extra)
        with self.assertRaises(ValueError):  # device on the wrong service
            check_plan(plan, "real-so101", {"leader": "/dev/ttyACM0", "arm_b": "/dev/ttyACM9"}, extra)

    def test_only_announced_sdk_cameras_with_their_image_reach_the_usb_bus(self):
        usb = {"image": "mrp-camera-ids", "device_cgroup_rules": ["c 189:* rmw"],
               "volumes": [{"type": "bind", "source": "/dev/bus/usb", "target": "/dev/bus/usb"}]}  # fmt: skip
        extra = {"usb_bus": {"camera": "mrp-camera-ids"}}
        plan = self.plan("mock-so101", camera=usb)
        self.assertEqual(check_plan(plan, "mock-so101", None, extra), plan)
        for bad_plan, bad_extra in (
            (plan, None),  # not announced by the agent
            (self.plan("mock-so101", camera={**usb, "image": "evil/mrp-camera-ids"}), extra),
            (self.plan("mock-so101", camera={**usb, "privileged": True}), extra),
            (self.plan("mock-so101", camera={**usb, "device_cgroup_rules": ["a *:* rwm"]}), extra),
            (self.plan("mock-so101", camera={**usb, "volumes": [{"type": "bind", "source": "/dev", "target": "/dev"}]}),
             extra),
            (self.plan("mock-so101", camera2=usb), extra),  # another service
        ):  # fmt: skip
            with self.subTest(plan=bad_plan["services"]), self.assertRaises(ValueError):
                check_plan(bad_plan, "mock-so101", None, bad_extra)


class ArmMergeTests(unittest.TestCase):
    ARMS = [
        {"id": "left", "joints": ["a", "b"], "prefixed": ["left_a", "left_b"]},
        {"id": "right", "joints": ["a", "b"], "prefixed": ["right_a", "right_b"]},
    ]

    def test_states_merge_on_the_first_arm_and_stop_when_an_arm_goes_silent(self):
        merger = arm_merge.StateMerger(self.ARMS, stale_after_ns=100)
        self.assertIsNone(merger.update("left", ["a", "b"], [1, 2], [], [], 0))  # right still missing
        self.assertIsNone(merger.update("right", ["b", "a"], [4, 3], [0.1, 0.2], [], 5))
        names, positions, velocities, efforts = merger.update("left", ["a", "b"], [1.5, 2], [0, 0], [], 10)
        self.assertEqual(names, ["left_a", "left_b", "right_a", "right_b"])
        self.assertEqual(positions, [1.5, 2.0, 3.0, 4.0])
        self.assertEqual(velocities, [0.0, 0.0, 0.2, 0.1])
        self.assertEqual(efforts, [])  # not every arm reports effort
        self.assertIsNone(merger.update("left", ["a", "b"], [1, 2], [], [], 500))  # right is stale
        self.assertIsNone(merger.update("left", ["a"], [1], [], [], 501))  # incomplete sample

    def test_combined_intents_split_per_follower_or_are_rejected_whole(self):
        names = ["right_b", "left_a", "left_b", "right_a"]
        parts = arm_merge.split_intent(names, [4, 1, 2, 3], [], self.ARMS)
        self.assertEqual([(p[0]["id"], p[1], p[2], p[3]) for p in parts],
                         [("left", ["a", "b"], [1.0, 2.0], []), ("right", ["a", "b"], [3.0, 4.0], [])])  # fmt: skip
        for bad in (
            (names[:3], [1, 2, 3], []),
            (names, [1, 2, 3], []),
            (names, [1, 2, 3, 4], [1]),
            ([*names[:3], "left_a"], [1, 2, 3, 4], []),
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                arm_merge.split_intent(*bad, self.ARMS)

    def test_config_is_checked(self):
        good = {"schema_version": "mrp-arm-adapter/v1", "followers": self.ARMS, "leaders": self.ARMS}
        self.assertIs(arm_merge.load(good), good)
        for bad in ({**good, "schema_version": "x"}, {**good, "leaders": []},
                    {**good, "followers": [{"id": "x", "joints": ["a"], "prefixed": []}]}):  # fmt: skip
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                arm_merge.load(bad)


sys.path[:0] = [str(BASE / "deployment"), str(ROOT / "core/cell_config")]
try:
    import agent
    from test_devices import FakeCompose, fake_sysfs
except ModuleNotFoundError as exc:  # pragma: no cover - workspace dependency missing
    agent = None
    SKIP = f"MRP workspace dependency not available: {exc.name}"


def more_ports(root, count=4):
    """fake_sysfs has ttyACM0/1; add ttyACM2.. with their own serial numbers."""
    for index in range(2, count):
        usb = root / f"devices/usb1/1-{index + 6}"
        usb.mkdir(parents=True)
        for name, value in {
            "idVendor": "1a86",
            "idProduct": "55d3",
            "serial": f"SER{index}",
            "removable": "removable",
        }.items():
            (usb / name).write_text(value)
        (usb / f"1-{index + 6}:1.0").mkdir()
        (root / f"class/tty/ttyACM{index}").mkdir(parents=True)
        (root / f"class/tty/ttyACM{index}/device").symlink_to(usb / f"1-{index + 6}:1.0")


@unittest.skipIf(agent is None, "MRP workspace dependency not available")
class AgentMultiCellTests(unittest.TestCase):
    PROBE = {
        "ok": True, "problems": [], "voltage_v": 7.0, "torque_enabled": False,
        "servos": [{"id": i, "present": True, "position": 2048, "is_sts3215": True} for i in range(1, 7)],
    }  # fmt: skip

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sys = Path(self.temp.name) / "sys"
        fake_sysfs(self.sys)
        more_ports(self.sys)
        self.renders, self.calibrations = [], "leader.yaml\nfollower.yaml\nleader_r.yaml\nright.yaml\n"

        self.camera_probes, self.camera_report = [], {
            "ok": True, "width": 640, "height": 480, "resolution_ok": True, "fps": 29.5, "frames": 90,
            "jpeg_base64": "/9j/AA==", "log": [],
        }  # fmt: skip

        def runner(command, **_):
            joined = " ".join(command)
            if "ls" in command:
                return subprocess.CompletedProcess(command, 0, self.calibrations, "")
            if "sdk_camera_probe.py" in joined:
                self.camera_probes.append(command)
                return subprocess.CompletedProcess(command, 0, json.dumps(self.camera_report), "")
            if "render_cell_config.py" in joined:
                at = command.index("/src/render_cell_config.py")
                self.renders.append((json.loads(command[at + 2]), command[at + 3 :]))
                return subprocess.CompletedProcess(command, 0, "sha256:abc", "")
            return subprocess.CompletedProcess(command, 0, json.dumps(self.PROBE), "")

        FakeCompose.calls = self.calls = []
        self.original = agent.ComposePreset
        self.addCleanup(setattr, agent, "ComposePreset", self.original)
        agent.ComposePreset = lambda files, project: FakeCompose(project, files)
        presets = {
            name: FakeCompose("mrp-mock-so101") for name in ("mock-so101", "hwleader-so101", "real-so101")
        }
        self.state = Path(self.temp.name) / "state"
        self.server = agent.make_server(
            presets, Path(self.temp.name) / "exports", port=0, workspace_root=ROOT,
            sys_root=str(self.sys), runner=runner, state_dir=self.state,
        )  # fmt: skip
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

    def overlay(self):
        return json.loads((self.state / "mrp-mock-so101.cell.json").read_text())["services"]

    def test_mock_two_follower_three_camera_cell_starts_every_component(self):
        body = {"preset": "mock-so101", "task_id": "pipeline_check", "arms": TWO_FOLLOWERS,
                "cameras": THREE_CAMERAS, "mock_motion": True}  # fmt: skip
        status, reply = self.post("/api/v1/deployment/up", body)
        self.assertEqual(status, 200, reply)
        services = self.overlay()
        self.assertEqual(services["leader"]["environment"], {"NAMESPACE": "arm_leader_l"})
        self.assertEqual(services["follower"]["environment"], {"NAMESPACE": "arm_left"})
        self.assertEqual(services["arm_right"]["environment"]["NAMESPACE"], "arm_right")
        self.assertEqual(services["arm_leader_r"]["environment"]["ROLE"], "leader")
        self.assertIn(
            "robot_config:=/workspace/config/mock-so101/robots/right.yaml",
            services["bridge_right"]["command"],
        )
        self.assertIn(
            "robot_config:=/workspace/config/mock-so101/robots/left.yaml", services["bridge"]["command"]
        )
        self.assertIn("arm_adapter", services)
        self.assertEqual(
            services["leader_motion_leader_r"]["environment"]["MOCK_MOTION_STATE_TOPIC"],
            "/arm_right/joint_states",
        )
        self.assertEqual(services["camera_wrist"]["environment"]["CAMERA_TOPIC"], "/wrist/image/compressed")
        self.assertNotIn("devices", services["arm_right"])
        env = self.calls[-1][1]
        self.assertEqual((env["CAMERA_TOPIC"], env["CAMERA2_TOPIC"], env["CAMERA2_FPS"]),
                         ("/top/image/compressed", "/front/image/compressed", "15"))  # fmt: skip
        self.assertEqual(env["COMPOSE_PROFILES"], "motion,side")
        params, extra = self.renders[-1]
        self.assertEqual([c["name"] for c in params["cameras"]], ["top", "front", "wrist"])
        self.assertEqual([(a["id"], a.get("leader")) for a in params["arms"]],
                         [("leader_l", None), ("leader_r", None), ("left", "leader_l"), ("right", "leader_r")])  # fmt: skip
        self.assertEqual(extra, ["--robots", "/robots"])  # mock: no calibration provenance

    def test_three_cameras_with_one_arm_pair_only_add_the_camera(self):
        status, reply = self.post("/api/v1/deployment/up", {"preset": "mock-so101", "cameras": THREE_CAMERAS})
        self.assertEqual(status, 200, reply)
        self.assertEqual(set(self.overlay()), {"camera_wrist"})
        self.assertNotIn("arms", self.renders[-1][0])

    def plug_usb(self, name, vendor, product, serial=""):
        device = self.sys / "bus/usb/devices" / name
        device.mkdir(parents=True)
        for key, value in {
            "idVendor": vendor,
            "idProduct": "0001",
            "product": product,
            "serial": serial,
        }.items():
            (device / key).write_text(value)

    def test_sdk_cameras_run_their_driver_with_usb_bus_access(self):
        self.plug_usb("1-4", "1409", "")  # IDS before the firmware upload: no product, no serial
        self.plug_usb("2-1", "8086", "Intel(R) RealSense(TM) Depth Camera 405", "123456789012")
        cameras = [
            {"id": "top", "source": "ids_ueye", "device": {"serial": "4102123456"}},
            {"id": "front", "source": "synthetic", "model": "realsense"},
            {"id": "wrist", "source": "realsense", "variant": "d405", "fps": 15},
        ]
        body = {"preset": "mock-so101", "cameras": cameras}
        status, report = self.post("/api/v1/devices/test", body)
        self.assertEqual(status, 200, report)
        self.assertTrue(report["passed"], report)
        names = {c["name"]: c for c in report["checks"]}
        self.assertTrue(names["Camera 'top' connected"]["ok"])
        self.assertEqual(names["Camera 'wrist' frame rate"]["measured_fps"], 29.5)
        self.assertIn("Camera 'wrist' snapshot", names)
        probe = self.camera_probes[0]  # throwaway container: removed, no network, USB bus only
        self.assertEqual(probe[:2], ["docker", "run"])
        self.assertIn("--rm", probe)
        self.assertEqual(probe[probe.index("--network") + 1], "none")
        self.assertIn("/usr/local/bin/camera-ids-entrypoint.sh", probe)
        self.assertNotIn("--privileged", probe)
        self.assertIn("NET_ADMIN", probe)
        self.assertIn("SYS_NICE", probe)
        status, reply = self.post("/api/v1/deployment/up", body)
        self.assertEqual(status, 200, reply)
        services = self.overlay()
        top = services["camera"]  # replaces the base mock camera service
        self.assertEqual(top["image"], "mrp-camera-ids")
        self.assertIsNone(top["entrypoint"])
        self.assertEqual(top["device_cgroup_rules"], ["c 189:* rmw"])
        self.assertEqual(top["cap_add"], ["NET_ADMIN", "SYS_NICE"])
        self.assertEqual(top["volumes"], ["/dev/bus/usb:/dev/bus/usb"])
        self.assertIn("serial_number:='4102123456'", top["command"])
        self.assertIn("fps:=30.0", top["command"])  # the IDS node declares fps as a double
        self.assertNotIn("privileged", top)
        self.assertNotIn("camera2", services)  # the mock camera stays the base mock service
        wrist = services["camera_wrist"]
        self.assertEqual(wrist["image"], "mrp-camera-realsense")
        self.assertIn("fps:=15", wrist["command"])
        self.assertIn("ZENOH_CONFIG_OVERRIDE", wrist["environment"])
        self.assertNotIn("CAMERA_DEVICE", self.calls[-1][1])  # no V4L2 overlay for SDK cameras

    def test_sdk_camera_test_fails_when_unplugged_or_silent(self):
        body = {"preset": "mock-so101", "cameras": [{"id": "top", "source": "ids_ueye"}]}
        status, report = self.post("/api/v1/devices/test", body)
        self.assertFalse(report["passed"])
        self.assertIn(
            "No IDS uEye",
            next(c for c in report["checks"] if c["name"] == "Camera 'top' connected")["detail"],
        )
        self.assertEqual(self.camera_probes, [])  # nothing to open
        self.plug_usb("1-4", "1409", "")
        self.camera_report = {"ok": False, "error": "Camera did not deliver images: the driver exited.",
                              "log": ["[FATAL] no IDS uEye camera found"]}  # fmt: skip
        status, report = self.post("/api/v1/devices/test", body)
        self.assertFalse(report["passed"])
        opens = next(c for c in report["checks"] if c["name"] == "Camera 'top' opens")
        self.assertIn("no IDS uEye camera found", opens["detail"])

    def test_two_sdk_cameras_of_one_model_need_serial_numbers(self):
        cameras = [
            {"id": "a", "source": "ids_ueye"},
            {"id": "b", "source": "ids_ueye", "device": {"serial": "1"}},
        ]
        status, reply = self.post("/api/v1/deployment/up", {"preset": "mock-so101", "cameras": cameras})
        self.assertEqual(status, 400)
        self.assertIn("serial number", reply["error"])

    def test_extra_real_arms_get_exactly_their_device_and_need_a_fresh_test(self):
        arms = [
            arm("leader", "leader", "real", device={"port": "/dev/ttyACM0", "serial": "ABC123"}),
            arm("leader_r", "leader", "real", device={"port": "/dev/ttyACM2"}),
            arm("follower", "follower", "real", leader="leader", device={"port": "/dev/ttyACM1"}),
            arm("right", "follower", "real", leader="leader_r", device={"port": "/dev/ttyACM3"}),
        ]
        body = {"preset": "real-so101", "task_id": "free_teleop", "arms": arms, "cameras": THREE_CAMERAS[:1]}
        status, reply = self.post("/api/v1/deployment/up", {**body, "operator_confirmed": True})
        self.assertEqual(status, 400)
        self.assertIn("connection test", reply["error"])
        status, report = self.post("/api/v1/devices/test", body)
        self.assertEqual(status, 200, report)
        self.assertTrue(report["passed"], report)
        names = [check["name"] for check in report["checks"]]
        self.assertIn("Follower 'right' calibration", names)
        self.assertIn("leader_r/right pose", names)
        status, reply = self.post("/api/v1/deployment/up", body)
        self.assertEqual(status, 400)  # no operator confirmation
        status, reply = self.post("/api/v1/deployment/up", {**body, "operator_confirmed": True})
        self.assertEqual(status, 200, reply)
        services = self.overlay()
        self.assertEqual(services["arm_right"]["devices"], ["/dev/ttyACM3:/dev/ttyACM3"])
        self.assertEqual(services["arm_right"]["environment"]["CALIBRATION_FILE"], "/calibration/right.yaml")
        self.assertEqual(services["arm_leader_r"]["environment"]["BACKEND"], "real")
        env = self.calls[-1][1]
        self.assertEqual((env["LEADER_PORT"], env["FOLLOWER_PORT"]), ("/dev/ttyACM0", "/dev/ttyACM1"))
        params, extra = self.renders[-1]
        self.assertEqual(params["robot"], "real")
        self.assertEqual(extra, ["/calibration", "leader.yaml", "leader_r.yaml", "follower.yaml", "right.yaml",
                                 "--robots", "/robots"])  # fmt: skip
        self.calibrations = "leader.yaml\nfollower.yaml\n"
        status, report = self.post("/api/v1/devices/test", body)
        self.assertFalse(report["passed"])  # right.yaml is missing

    def test_mismatching_components_and_presets_are_rejected(self):
        real_pair = [arm("l", "leader", "real", device={"port": "/dev/ttyACM0"}), arm("f", "follower")]
        for body in (
            {"preset": "mock-so101", "arms": real_pair},  # a real arm is never started by the mock preset
            {"preset": "mock-so101", "arms": TWO_FOLLOWERS, "devices": {"leader": {"port": "/dev/ttyACM0"}}},
            {"preset": "mock-so101", "arms": [*TWO_FOLLOWERS[:3]]},
        ):
            with self.subTest(body=body):
                status, _ = self.post("/api/v1/deployment/up", body)
                self.assertEqual(status, 400)

    def test_cell_starts_and_stops_remove_orphaned_services(self):
        real = self.original([ROOT / "application/backend/deployment/mock-cell/compose.yaml"], "mrp-x")
        captured = []
        with unittest.mock.patch("agent.subprocess.run", side_effect=lambda c, **_: captured.append(c)):
            real.run("up")
            real.run("down")
        self.assertTrue(all(command[-1] == "--remove-orphans" for command in captured))
        self.assertEqual([c[c.index("--file") + 2] for c in captured], ["up", "down"])


class ComposeMergeTests(unittest.TestCase):
    """The generated overlay merges with the real Compose files (needs Docker Compose)."""

    def test_overlay_renders_with_docker_compose(self):
        import shutil

        if agent is None or not shutil.which("docker"):
            self.skipTest("Docker Compose is not installed")
        if subprocess.run(["docker", "compose", "version"], capture_output=True, check=False).returncode:
            self.skipTest("Docker Compose is not installed")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        deployment = BASE / "deployment"
        sys_root = Path(temp.name) / "sys"
        fake_sysfs(sys_root)
        state = Path(temp.name) / "state"

        base_class = agent.ComposePreset

        class PlanOnly(base_class):
            def run(self, action, doc=None, env=None):
                if action == "plan":
                    return super().run(action, doc, env)
                return subprocess.CompletedProcess([], 0, "", "")

        files = [deployment / "mock-cell/compose.yaml", deployment / "cell.compose.yaml"]
        preset = PlanOnly(files, "mrp-mock-so101-test")
        original, agent.ComposePreset = agent.ComposePreset, PlanOnly
        self.addCleanup(setattr, agent, "ComposePreset", original)
        renders = []

        def runner(command, **_):
            if "render_cell_config.py" in " ".join(command):
                renders.append(command)
            return subprocess.CompletedProcess(command, 0, "sha256:abc", "")

        server = agent.make_server(
            {"mock-so101": preset}, Path(temp.name) / "exports", port=0, workspace_root=ROOT,
            sys_root=str(sys_root), runner=runner, state_dir=state,
        )  # fmt: skip
        server.allowed_hosts = {"127.0.0.1"}
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        body = {"preset": "mock-so101", "arms": TWO_FOLLOWERS, "cameras": THREE_CAMERAS, "mock_motion": True}
        request = Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/v1/deployment/up",
            json.dumps(body).encode(), {"Content-Type": "application/json"},
        )  # fmt: skip
        try:
            with urlopen(request, timeout=60) as response:
                self.assertEqual(response.status, 200)
        except HTTPError as exc:
            self.fail(json.load(exc))
        overlay = state / "mrp-mock-so101-test.cell.json"
        command = ["docker", "compose", "-p", "x"]
        for file in [*files, overlay]:
            command += ["-f", str(file)]
        result = subprocess.run([*command, "--profile", "*", "config", "--format", "json"],
                                capture_output=True, text=True, check=False)  # fmt: skip
        self.assertEqual(result.returncode, 0, result.stderr)
        services = json.loads(result.stdout)["services"]
        self.assertEqual(services["follower"]["environment"]["NAMESPACE"], "arm_left")
        self.assertEqual(services["follower"]["environment"]["BACKEND"], "mock")  # merged, not replaced
        source = services["arm_right"]["volumes"][0]["source"]
        self.assertEqual(source, str(ROOT / "driver/robot_so101/src"))  # relative to the base file
        self.assertEqual(
            services["arm_adapter"]["volumes"][0]["source"], str(deployment / "mock-cell/arm_adapter.py")
        )


if __name__ == "__main__":
    unittest.main()
