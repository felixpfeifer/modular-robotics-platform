import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3] if len(Path(__file__).resolve().parents) > 3 else None
if ROOT is None or not (ROOT / "driver/robot_so101/profile.json").is_file():
    raise unittest.SkipTest("MRP workspace not available")
spec = importlib.util.spec_from_file_location(
    "render_cell_config", ROOT / "application/backend/deployment/cell-templates/render_cell_config.py"
)
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)


PROFILE = json.loads((ROOT / "driver/robot_so101/profile.json").read_text())


def strict_read(text):
    """The renderer's reader with PyYAML hidden, as on a host without it."""
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def hide_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("hidden")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", hide_yaml):
        return render.read_robot_config(text)


def params(**changes):
    base = {
        "robot": "sim", "robot_profile": PROFILE, "task_id": "pipeline_check", "instruction": "",
        "recording": {"minimum_duration_seconds": 5.0, "preflight_min_free_gib": 10.0},
        "cameras": [{"name": "webcam", "topic": "/webcam/image/compressed", "width": 640, "height": 480, "fps": 30}],
    }  # fmt: skip
    return {**base, **changes}


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.out = Path(self.temp.name) / "out"

    def tearDown(self):
        self.temp.cleanup()

    def test_control_limits_come_from_robot_config(self):
        robots = ROOT / "core/recorder/config/robots"
        render.render(self.out, params(), render.MOCK_CALIBRATION, robots)
        text = (self.out / "control/teleop.yaml").read_text()
        self.assertIn("joint_limits:", text)
        self.assertIn("gripper_joint:\n        lower: 0", text)

    def test_mock_handover_is_only_rendered_for_simulated_followers(self):
        render.render(self.out, params(mock_handover=True), render.MOCK_CALIBRATION)
        self.assertIn("mock_handover_rate: 0.5", (self.out / "control/arbiter.yaml").read_text())
        with self.assertRaises(SystemExit):
            render.render(self.out, params(robot="real", mock_handover=True), render.MOCK_CALIBRATION)

    def test_default_mock_render_matches_the_checked_in_mock_config(self):
        render.render(self.out, params(), render.MOCK_CALIBRATION)
        mock = ROOT / "application/backend/deployment/mock-cell/seed"
        for name in ("webcam.yaml", "recording_profiles.yaml"):
            self.assertEqual((self.out / name).read_text().split(), (mock / name).read_text().split(), name)
        workspace = (self.out / "workspace.yaml").read_text()
        self.assertIn("recording_profile_id: mock_so101_webcam_v1", workspace)
        self.assertIn(render.MOCK_CALIBRATION["hash"], workspace)

    def test_camera_settings_flow_into_the_recording_contract(self):
        cameras = [
            {"name": "webcam", "topic": "/webcam/image/compressed", "width": 1280, "height": 720, "fps": 25},
            {"name": "side", "topic": "/side/image/compressed", "width": 640, "height": 480, "fps": 15},
        ]
        render.render(self.out, params(cameras=cameras), render.MOCK_CALIBRATION)
        main = (self.out / "webcam.yaml").read_text()
        self.assertIn("width: 1280", main)
        self.assertIn("fps: 25.0", main)
        self.assertIn("maximum_gap_ms: 90.0", main)  # 2.25 frame periods
        self.assertIn(
            "camera_configs: [webcam.yaml, side.yaml]", (self.out / "recording_profiles.yaml").read_text()
        )
        self.assertIn("topic: /side/image/compressed", (self.out / "side.yaml").read_text())

    def test_camera_gap_can_be_set_explicitly_and_is_validated(self):
        recording = {
            "minimum_duration_seconds": 5.0,
            "preflight_min_free_gib": 10.0,
            "maximum_camera_gap_ms": 150,
        }
        render.render(self.out, params(recording=recording), render.MOCK_CALIBRATION)
        self.assertIn("maximum_gap_ms: 150.0", (self.out / "webcam.yaml").read_text())
        for bad in (10, 5000):
            with self.subTest(gap=bad), self.assertRaises(SystemExit):
                render.render(
                    self.out,
                    params(recording={**recording, "maximum_camera_gap_ms": bad}),
                    render.MOCK_CALIBRATION,
                )
        render.render(
            self.out, params(recording={**recording, "maximum_camera_gap_ms": 0}), render.MOCK_CALIBRATION
        )
        self.assertIn("maximum_gap_ms: 75.0", (self.out / "webcam.yaml").read_text())  # 0 = automatic

    def test_real_robot_uses_the_real_contract_and_the_calibration_digest(self):
        calibration = Path(self.temp.name) / "cal"
        calibration.mkdir()
        (calibration / "leader.yaml").write_text("a")
        (calibration / "follower.yaml").write_text("b")
        found = render.calibration_provenance("real", calibration, "leader.yaml", "follower.yaml")
        render.render(self.out, params(robot="real", task_id="free_teleop"), found)
        self.assertIn("robots/so101.yaml", (self.out / "recording_profiles.yaml").read_text())
        self.assertIn(found["hash"], (self.out / "workspace.yaml").read_text())
        (calibration / "follower.yaml").write_text("changed")
        self.assertNotEqual(
            found["hash"],
            render.calibration_provenance("real", calibration, "leader.yaml", "follower.yaml")["hash"],
        )
        with self.assertRaises(SystemExit):
            render.calibration_provenance("real", calibration, "../x.yaml", "follower.yaml")

    def test_instruction_is_quoted_and_inputs_are_validated(self):
        render.render(self.out, params(instruction='Pick: "red" cube\nnow'), render.MOCK_CALIBRATION)
        line = [x for x in (self.out / "tasks.yaml").read_text().splitlines() if "instruction" in x][0]
        self.assertEqual(json.loads(line.split("instruction: ", 1)[1]), 'Pick: "red" cube now')
        for bad in (
            params(robot="x"),
            params(cameras=[{"name": "../x", "topic": "/t", "width": 640, "height": 480, "fps": 30}]),
            params(cameras=[{"name": "webcam", "topic": "/w", "width": 640, "height": 480, "fps": 500}]),
            params(recording={"minimum_duration_seconds": 0}),
        ):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                render.render(self.out, bad, render.MOCK_CALIBRATION)

    def test_default_control_render_matches_the_packaged_arbiter_config(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML unavailable")
        render.render(self.out, params(), render.MOCK_CALIBRATION)
        packaged = ROOT / "core/control_arbiter/config"
        for name in ("arbiter.yaml", "teleop.yaml"):
            with self.subTest(name=name):
                self.assertEqual(
                    yaml.safe_load((self.out / "control" / name).read_text()),
                    yaml.safe_load((packaged / name).read_text()),
                )

    def test_teleop_settings_and_joint_mapping_flow_into_the_control_config(self):
        teleop = {
            "validity_ms": 100, "source_timeout_ms": 400, "max_handover_jump_rad": 0.1,
            "joint_mapping": {"shoulder_pan_joint": {"scale": -1, "leader_reference_rad": 0.2}},
        }  # fmt: skip
        render.render(self.out, params(teleop=teleop), render.MOCK_CALIBRATION)
        nodes = render.control_params(PROFILE, render.teleop_settings(teleop, PROFILE["joint_names"]))
        source, arbiter = nodes["teleop_source"], nodes["control_arbiter"]
        text = (self.out / "control/teleop.yaml").read_text()
        self.assertIn(
            "      shoulder_pan_joint:\n        scale: -1.0\n        leader_reference_rad: 0.2\n", text
        )
        self.assertIn("    validity_ms: 100\n", text)
        self.assertEqual(source["validity_ms"], 100)
        self.assertEqual(source["max_leader_age_ms"], 200)  # default
        self.assertEqual(
            source["joint_mapping"], {"shoulder_pan_joint": {"scale": -1.0, "leader_reference_rad": 0.2}}
        )
        self.assertEqual((arbiter["source_timeout_ms"], arbiter["max_handover_jump_rad"]), (400, 0.1))

    def test_another_robot_profile_changes_joints_topics_and_names(self):
        other = {
            "id": "ur5e", "joint_names": ["shoulder_pan_joint", "wrist_3_joint"],
            "topics": {"joint_states": "/ur/joint_states", "leader_joint_states": "/leader/joint_states"},
            "recorder_robot_config": {"sim": "ur5e_sim.yaml", "real": "ur5e.yaml"},
        }  # fmt: skip
        render.render(self.out, params(robot_profile=other), render.MOCK_CALIBRATION)
        arbiter = (self.out / "control/arbiter.yaml").read_text()
        self.assertIn("joint_names: [shoulder_pan_joint, wrist_3_joint]", arbiter)
        self.assertIn("joint_states_topic: /ur/joint_states", arbiter)
        self.assertIn("target_id: ur5e", (self.out / "control/teleop.yaml").read_text())
        self.assertIn("robots/ur5e_sim.yaml", (self.out / "recording_profiles.yaml").read_text())
        self.assertIn("mock_ur5e_webcam_v1", (self.out / "workspace.yaml").read_text())

    def test_invalid_profiles_and_teleop_settings_are_rejected(self):
        for bad in (
            params(robot_profile=None),
            params(robot_profile={**PROFILE, "joint_names": ["ok", "bad joint"]}),
            params(robot_profile={**PROFILE, "topics": {"joint_states": "x"}}),
            params(teleop={"validity_ms": 5}),
            params(teleop={"validity_ms": 120}),  # teleop_source accepts 1-100 ms
            params(teleop={"unknown": 1}),
            params(teleop={"joint_mapping": {"elbow": {"scale": 1}}}),  # not a joint of this robot
            params(teleop={"joint_mapping": {"gripper_joint": {"scale": 0}}}),
        ):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                render.render(self.out, bad, render.MOCK_CALIBRATION)

    def test_up_to_six_cameras_are_recorded(self):
        cameras = [
            {"name": f"cam{i}", "topic": f"/cam{i}/image/compressed", "width": 640, "height": 480, "fps": 30}
            for i in range(6)
        ]
        render.render(self.out, params(cameras=cameras), render.MOCK_CALIBRATION)
        profiles = (self.out / "recording_profiles.yaml").read_text()
        self.assertIn("camera_configs: [" + ", ".join(f"cam{i}.yaml" for i in range(6)) + "]", profiles)
        with self.assertRaises(SystemExit):
            render.render(
                self.out, params(cameras=[*cameras, {**cameras[0], "name": "x"}]), render.MOCK_CALIBRATION
            )

    def test_strict_reader_matches_pyyaml_on_the_recorder_robot_configs(self):
        robots = ROOT / "core/recorder/config/robots"
        for name in ("so101.yaml", "so101_sim.yaml"):
            with self.subTest(name=name):
                strict = strict_read((robots / name).read_text())
                self.assertEqual(strict["robot"]["joints"][2]["lower"], -1.69)
                self.assertEqual(strict["robot"]["command_adapter"]["groups"][1]["joints"], ["gripper_joint"])
                try:
                    import yaml
                except ImportError:
                    continue
                self.assertEqual(strict, yaml.safe_load((robots / name).read_text()))
        for bad in ("robot:\n  id: [a, {b}]\n", "robot:\n  - x\n y: 1\n", "robot: a b\n"):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                strict_read(bad)

    ARMS = [
        {"id": "ll", "role": "leader", "robot": "sim"},
        {"id": "lr", "role": "leader", "robot": "sim"},
        {"id": "left", "role": "follower", "robot": "sim", "leader": "ll"},
        {"id": "right", "role": "follower", "robot": "sim", "leader": "lr",
         "joint_mapping": {"gripper_joint": {"scale": -1.0, "leader_joint": "wrist_roll_joint"}}},
    ]  # fmt: skip

    def render_multi(self, **changes):
        robots = ROOT / "core/recorder/config/robots"
        render.render(self.out, params(arms=self.ARMS, **changes), render.MOCK_CALIBRATION, robots)

    def test_two_followers_become_one_combined_robot(self):
        self.render_multi()
        combined = json.loads((self.out / "robots/cell.yaml").read_text())["robot"]
        names = [joint["name"] for joint in combined["joints"]]
        self.assertEqual(names[:2], ["left_shoulder_pan_joint", "left_shoulder_lift_joint"])
        self.assertEqual(len(names), 12)
        self.assertEqual((combined["state"]["topic"], combined["action"]["topic"]),
                         ("/joint_states", "/platform/control/joint_intent"))  # fmt: skip
        self.assertEqual(combined["target_id"], "so101_cell")
        own = json.loads((self.out / "robots/right.yaml").read_text())["robot"]
        self.assertEqual(own["target_id"], "so101_right")
        self.assertEqual(own["state"]["topic"], "/arm_right/joint_states")
        self.assertEqual(own["action"]["topic"], "/platform/control/arms/right/joint_intent")
        self.assertEqual(own["command_adapter"]["groups"][0]["endpoint"],
                         "/arm_right/joint_trajectory_controller/joint_trajectory")  # fmt: skip
        self.assertEqual(
            [j["name"] for j in own["joints"]], PROFILE["joint_names"]
        )  # unprefixed for the bridge
        adapter = json.loads((self.out / "arms.json").read_text())
        self.assertEqual([f["id"] for f in adapter["followers"]], ["left", "right"])
        self.assertEqual(adapter["leaders"][1]["state_topic"], "/arm_lr/joint_states")
        self.assertIn("robot_config: robots/cell.yaml", (self.out / "recording_profiles.yaml").read_text())
        self.assertIn("recording_profile_id: mock_so101_cell_v1", (self.out / "workspace.yaml").read_text())
        teleop = (self.out / "control/teleop.yaml").read_text()
        self.assertIn("    target_id: so101_cell\n", teleop)
        self.assertIn("      left_elbow_flex_joint:\n        leader_joint: ll_elbow_flex_joint\n", teleop)
        self.assertIn(
            "      right_gripper_joint:\n        leader_joint: lr_wrist_roll_joint\n        scale: -1.0\n",
            teleop,
        )
        arbiter = (self.out / "control/arbiter.yaml").read_text()
        self.assertIn("joint_states_topic: /joint_states", arbiter)
        self.assertIn("right_gripper_joint]", arbiter)

    def test_multi_arm_inputs_are_validated(self):
        leader, follower = self.ARMS[0], self.ARMS[2]
        for bad in (
            params(arms=[leader]),
            params(arms=[leader, {**follower, "leader": "nobody"}]),
            params(arms=[leader, follower, {**follower}]),  # repeated id
            params(arms=[leader, {**follower, "id": "x" * 17}]),
            params(arms=[leader, {**follower, "robot": "real"}]),  # robot must say real
            params(arms=self.ARMS, teleop={"joint_mapping": {"gripper_joint": {"scale": -1}}}),
        ):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                render.render(self.out, bad, render.MOCK_CALIBRATION, ROOT / "core/recorder/config/robots")
        with self.assertRaises(SystemExit):  # robot configs not mounted
            render.render(self.out, params(arms=self.ARMS), render.MOCK_CALIBRATION, Path(self.temp.name))

    def test_calibration_provenance_covers_every_real_arm(self):
        calibration = Path(self.temp.name) / "cal"
        calibration.mkdir()
        for name in ("a.yaml", "b.yaml", "c.yaml"):
            (calibration / name).write_text(name)
        three = render.calibration_provenance("real", calibration, "a.yaml", "b.yaml", "c.yaml")
        two = render.calibration_provenance("real", calibration, "a.yaml", "b.yaml")
        self.assertNotEqual(three["hash"], two["hash"])
        for bad in (("a.yaml",), ("a.yaml", "a.yaml")):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                render.calibration_provenance("real", calibration, *bad)

    def test_rendered_workspace_loads_with_the_recorders_own_loader(self):
        sys.path[:0] = [str(ROOT / "core/recorder")]
        try:
            from episode_recorder_py.configuration import load_workspace_config
        except Exception as exc:  # recorder dependencies (yaml, ROS) may be missing
            self.skipTest(f"recorder loader unavailable: {exc}")
        # The loader resolves ../../core/recorder/config relative to the workspace folder.
        folder = Path(self.temp.name) / "config/cell"
        (Path(self.temp.name) / "core/recorder").mkdir(parents=True)
        (Path(self.temp.name) / "core/recorder/config").symlink_to(ROOT / "core/recorder/config")
        render.render(folder, params(), render.MOCK_CALIBRATION)
        loaded = load_workspace_config(folder / "workspace.yaml")
        self.assertEqual(loaded["profile"]["cameras"][0]["fps"], 30.0)


if __name__ == "__main__":
    unittest.main()
