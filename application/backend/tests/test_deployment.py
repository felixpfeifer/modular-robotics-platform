import copy
import unittest

from mrp_app.deployment import check_mock_plan
from mrp_app.network import default_gateway


class MockPresetTests(unittest.TestCase):
    def setUp(self):
        self.plan = {
            "services": {
                name: {}
                for name in (
                    "zenoh_router",
                    "leader",
                    "leader_motion",
                    "follower",
                    "control",
                    "camera",
                    "camera2",
                    "bridge",
                    "recorder",
                    "convert",
                    "upload",
                )
            }
        }
        for name in ("leader", "follower"):
            self.plan["services"][name] = {"environment": {"BACKEND": "mock"}}

    def test_real_backend_and_device_access_are_rejected(self):
        self.assertEqual(check_mock_plan(self.plan), self.plan)
        variants = [
            ("follower", {"environment": {"BACKEND": "real"}}),
            ("camera", {"devices": ["/dev/video0"]}),
            ("camera", {"privileged": True}),
            ("control", {"volumes": [{"type": "bind", "source": "/var/run/docker.sock"}]}),
            ("leader", {"environment": {"BACKEND": "mock"}, "volumes": [{"type": "bind", "source": "/dev"}]}),
        ]
        for name, service in variants:
            plan = copy.deepcopy(self.plan)
            plan["services"][name] = service
            with self.subTest(service=name, config=service), self.assertRaises(ValueError):
                check_mock_plan(plan)

    def test_real_presets_allow_only_the_selected_devices(self):
        from mrp_app.deployment import PRESET_SERVICES, check_plan

        plan = {"services": {name: {} for name in PRESET_SERVICES["real-so101"]}}
        plan["services"]["leader"] = {
            "environment": {"BACKEND": "real"},
            "devices": [{"source": "/dev/ttyACM0", "target": "/dev/ttyACM0"}],
        }
        plan["services"]["follower"] = {
            "environment": {"BACKEND": "real"},
            "devices": ["/dev/ttyACM1:/dev/ttyACM1:rwm"],
        }
        plan["services"]["camera"] = {"devices": ["/dev/video2:/dev/video2"]}
        allowed = {"leader": "/dev/ttyACM0", "follower": "/dev/ttyACM1", "camera": "/dev/video2"}
        self.assertEqual(check_plan(plan, "real-so101", allowed), plan)
        with self.assertRaises(ValueError):  # nothing selected -> no device access
            check_plan(plan, "real-so101")
        swapped = copy.deepcopy(plan)
        swapped["services"]["follower"]["devices"] = ["/dev/ttyACM0:/dev/ttyACM0"]
        with self.assertRaises(ValueError):  # wrong port for the service
            check_plan(swapped, "real-so101", allowed)
        for name, extra in (
            ("control", {"devices": ["/dev/ttyACM0:/dev/ttyACM0"]}),  # not a device consumer
            ("leader", {"privileged": True}),
            ("camera", {"device_cgroup_rules": ["c 81:* rmw"]}),
        ):
            bad = copy.deepcopy(plan)
            bad["services"][name].update(extra)
            with self.subTest(service=name), self.assertRaises(ValueError):
                check_plan(bad, "real-so101", allowed)
        mock = {"services": {name: {} for name in PRESET_SERVICES["hwleader-so101"]}}
        mock["services"]["leader"] = {"environment": {"BACKEND": "real"}}
        mock["services"]["follower"] = {"environment": {"BACKEND": "real"}}
        with self.assertRaises(ValueError):  # real follower is not allowed in the leader-only preset
            check_plan(mock, "hwleader-so101")

    def test_unapproved_services_are_rejected(self):
        self.plan["services"]["arbitrary"] = {"image": "unapproved"}
        with self.assertRaises(ValueError):
            check_mock_plan(self.plan)

    def test_docker_gateway_uses_container_route_instead_of_laptop_dns(self):
        routes = "Iface Destination Gateway Flags\neth0 00000000 010012AC 0003\n"
        self.assertEqual(default_gateway(routes), "172.18.0.1")
        with self.assertRaises(ValueError):
            default_gateway("Iface Destination Gateway Flags\neth0 000012AC 00000000 0001\n")


class PresetAndModelTests(unittest.TestCase):
    def test_compose_renders_custom_robot_and_camera_images(self):
        import json
        import os
        import shutil
        import subprocess
        from pathlib import Path

        if not shutil.which("docker"):
            self.skipTest("Docker Compose is not installed")
        version = subprocess.run(["docker", "compose", "version"], capture_output=True, check=False)
        if version.returncode:
            self.skipTest("Docker Compose is not installed")
        deployment = Path(__file__).resolve().parents[1] / "deployment"
        command = ["docker", "compose"]
        for name in (
            "mock-cell/compose.yaml",
            "cell.compose.yaml",
            "usb_camera.compose.yaml",
            "usb_side_camera.compose.yaml",
        ):
            command.extend(["-f", str(deployment / name)])
        command.extend(["--profile", "*", "config", "--format", "json"])
        env = {
            **os.environ,
            "MRP_LEADER_IMAGE": "acme/robot:v1",
            "MRP_CAMERA_IMAGE": "acme/camera:v1",
            "MRP_CAMERA2_IMAGE": "acme/side:v1",
        }
        result = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        services = json.loads(result.stdout)["services"]
        self.assertEqual(services["leader"]["image"], "acme/robot:v1")
        self.assertEqual(services["camera"]["image"], "acme/camera:v1")
        self.assertEqual(services["camera2"]["image"], "acme/side:v1")
        self.assertIsNone(services["camera"].get("entrypoint"))
        self.assertIsNone(services["camera2"].get("entrypoint"))

    def test_custom_images_accept_only_docker_hub_references_and_known_roles(self):
        from mrp_app.catalog import CellSpecError, validate_images

        images = {"leader": "docker.io/acme/robot--driver:v1", "camera": "camera@sha256:" + "a" * 64}
        self.assertEqual(validate_images(images), images)
        for invalid in (
            {"sensor": "acme/sensor"},
            {"camera": "example.com/acme/camera"},
            {"camera": "example.com/camera"},
            {"camera": "localhost/camera"},
            {"camera": "-invalid"},
            {"camera": "acme/camera;echo hi"},
            {"camera": ""},
        ):
            with self.subTest(images=invalid), self.assertRaises(CellSpecError):
                validate_images(invalid)

    def test_sim_plan_needs_exact_services_and_gazebo_follower(self):
        from mrp_app.deployment import PRESET_SERVICES, check_plan

        plan = {"services": {name: {} for name in PRESET_SERVICES["sim-so101"]}}
        plan["services"]["leader"] = {"environment": {"BACKEND": "mock"}}
        plan["services"]["follower"] = {"environment": {"BACKEND": "gazebo"}}
        self.assertEqual(check_plan(plan, "sim-so101"), plan)
        plan["services"]["follower"]["environment"]["BACKEND"] = "hardware"
        with self.assertRaises(ValueError):
            check_plan(plan, "sim-so101")
        with self.assertRaises(ValueError):
            check_plan({"services": {}}, "mock-so101")

    def test_policy_and_training_plans_reject_devices_and_open_networks(self):
        from mrp_app.deployment import check_policy_plan, check_training_plan

        with self.assertRaises(ValueError):
            check_training_plan({"services": {"train": {"network_mode": "host"}, "hub_import": {}}})
        ok = {
            "services": {
                "act_server": {"volumes": [{"type": "volume", "read_only": True}]},
                "policy_source": {},
            }
        }
        self.assertEqual(check_policy_plan(ok), ok)
        ok["services"]["policy_source"]["devices"] = ["/dev/ttyUSB0"]
        with self.assertRaises(ValueError):
            check_policy_plan(ok)

    def test_plans_accept_only_read_only_workspace_source_binds(self):
        from mrp_app.deployment import check_policy_plan, check_training_plan

        def plan(source, read_only=True):
            bind = {"type": "bind", "source": source, "read_only": read_only}
            return {"services": {"train": {"network_mode": "none", "volumes": [bind]}, "hub_import": {}}}, {
                "services": {"act_server": {"volumes": [bind]}, "policy_source": {}}
            }

        training, policy = plan("/ws/core/ai_lerobot/ai_lerobot")
        self.assertEqual(check_training_plan(training, "/ws"), training)
        self.assertEqual(check_policy_plan(policy, "/ws"), policy)
        for source, read_only, root in (
            ("/ws/core/ai_lerobot", False, "/ws"),
            ("/ws/../etc", True, "/ws"),
            ("/wsx/code", True, "/ws"),
            ("/ws/core", True, None),
        ):
            training, policy = plan(source, read_only)
            with self.assertRaises(ValueError):
                check_training_plan(training, root)
            with self.assertRaises(ValueError):
                check_policy_plan(policy, root)

    def test_gpu_detection_reports_usable_gpu_and_actionable_reasons(self):
        import sys
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch

        sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "deployment")]
        try:
            import agent
        except ModuleNotFoundError as exc:
            self.skipTest(f"MRP workspace dependency not available: {exc.name}")

        def run(returncode, stdout="", stderr=""):
            return patch(
                "agent.subprocess.run",
                return_value=SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr),
            )

        with run(0, "NVIDIA RTX 4060,8589934592\n"):
            self.assertEqual(
                agent.detect_gpu(), {"gpu": True, "name": "NVIDIA RTX 4060", "vram_gb": 8.0, "detail": ""}
            )
        for stderr, text in (
            ("Unable to find image 'x' locally", "not built"),
            ('could not select device driver "" with capabilities: [[gpu]]', "container toolkit"),
            ("AssertionError: torch.cuda.is_available() is False", "cannot use the GPU"),
        ):
            with run(1, stderr=stderr):
                result = agent.detect_gpu()
            self.assertFalse(result["gpu"])
            self.assertIn(text, result["detail"])
        with patch("agent.subprocess.run", side_effect=FileNotFoundError):
            self.assertFalse(agent.detect_gpu()["gpu"])

    def test_training_progress_reports_step_eta_and_big_number_suffixes(self):
        import json
        import sys
        import tempfile
        from pathlib import Path

        base = Path(__file__).resolve().parents[1]
        sys.path[:0] = [str(base / "deployment"), str(base.parent.parent / "core/cell_config")]
        try:
            from agent import training_progress
        except ModuleNotFoundError as exc:
            self.skipTest(f"MRP workspace dependency not available: {exc.name}")
        with tempfile.TemporaryDirectory() as root:
            run = Path(root)
            (run / "job.json").write_text(
                json.dumps({"status": "running", "configuration": {"steps": 10000}})
            )
            self.assertEqual(training_progress(run)["step"], 0)  # no log yet
            (run / "train.log").write_text(
                "INFO step:200 smpl:2K loss:4.0 updt_s:0.5 data_s:0.0\n"
                "INFO step:2K smpl:16K loss:1.5 updt_s:0.5 data_s:0.0\n"
            )
            result = training_progress(run)
            self.assertEqual((result["step"], result["percent"], result["loss"]), (2000, 20.0, 1.5))
            self.assertTrue(result["step_is_approximate"])
            (run / "train.log").write_text(
                "INFO step:200 loss:4.0 updt_s:0.5\n"
                "Training:  10%|\u2589         | 99/1000 [02:54<24:32,  1.63s/step]\r"
                "Training:  10%|\u2588         | 100/1000 [02:56<24:36,  1.64s/step]"
            )
            result = training_progress(run)
            self.assertEqual((result["step"], result["percent"], result["eta_seconds"]), (100, 10.0, 1476))
            self.assertEqual(result["loss"], 4.0)
            self.assertAlmostEqual(result["seconds_per_step"], 1.64)

    def test_checkpoint_must_be_complete_act_inside_runs_volume(self):
        import json
        import sys
        import tempfile
        import uuid
        from pathlib import Path

        base = Path(__file__).resolve().parents[1]
        sys.path[:0] = [str(base / "deployment"), str(base.parent.parent / "core/cell_config")]
        try:
            from agent import CHECKPOINT_FILES, load_checkpoint
        except ModuleNotFoundError as exc:
            self.skipTest(f"MRP workspace dependency not available: {exc.name}")
        with tempfile.TemporaryDirectory() as root:
            run = str(uuid.uuid4())
            model = f"{run}/output/checkpoints/last/pretrained_model"
            folder = Path(root) / model
            folder.mkdir(parents=True)
            for name in CHECKPOINT_FILES:
                (folder / name).write_text("{}")
            (folder / "config.json").write_text(json.dumps({"type": "act"}))
            self.assertEqual(load_checkpoint(root, model)["type"], "act")
            for bad in ("/etc/passwd", f"../{model}", f"{run}/output/checkpoints/../../x/pretrained_model"):
                with self.assertRaises(ValueError):
                    load_checkpoint(root, bad)
            (folder / "model.safetensors").unlink()
            with self.assertRaises(ValueError):
                load_checkpoint(root, model)
