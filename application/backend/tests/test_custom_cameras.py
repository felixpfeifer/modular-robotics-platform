"""Camera models beyond the built-in ones: discovered from labelled driver images, or added in the UI."""

import copy
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mrp_app import cameras, components
from mrp_app import layout as cell_layout
from mrp_app.catalog import CellSpecError, validate_spec
from mrp_app.deployment import PRESET_SERVICES, check_plan
from mrp_app.runtime import DemoRuntime
from mrp_app.server import make_server
from mrp_app.service import Application

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parent.parent

ACME = {
    "id": "acme_x1",
    "label": "Acme X1",
    "access": "usb_bus",
    "variants": {"mono": "Mono", "color": "Color"},
    "probe_command": ["ros2", "run", "camera_acme", "camera_node"],
    "usb": {"vendor_id": "1d6b", "product": "acme"},
}
IPCAM = {
    "id": "ipcam",
    "label": "RTSP IP camera",
    "access": "network",
    "probe_command": ["ros2", "run", "camera_rtsp", "camera_node"],
}


def labels(manifest):
    return {cameras.LABEL_KIND: cameras.KIND_CAMERA, cameras.LABEL_MANIFEST: json.dumps(manifest)}


class ManifestTests(unittest.TestCase):
    def test_a_valid_manifest_becomes_a_usb_bus_model(self):
        ident, model = cameras.parse_manifest(ACME, "acme/camera-x1:1.0", "custom")
        self.assertEqual(ident, "acme_x1")
        self.assertEqual(model["image"], "acme/camera-x1:1.0")
        self.assertEqual(
            (model["access"], model["connections"], model["origin"]), ("usb_bus", ["usb"], "custom")
        )
        self.assertEqual(model["fields"], {"serial": "camera serial number (empty = the first camera found)"})
        self.assertEqual(model["usb"], {"vendor_id": "1d6b", "product": "acme"})
        self.assertEqual(cameras.parse_manifest(IPCAM, "acme/rtsp", "custom")[1]["connections"], ["network"])

    def test_stored_form_round_trips(self):
        ident, model = cameras.parse_manifest(ACME, "acme/camera-x1:1.0", "custom")
        stored = cameras.to_manifest(ident, model)
        image = stored.pop("image")
        self.assertEqual(cameras.parse_manifest(stored, image, "custom"), (ident, model))

    def test_rejects_what_could_widen_access_or_confuse_the_catalogue(self):
        bad = [
            ({**ACME, "id": "realsense"}, "acme/x", "reserved"),
            ({**ACME, "id": "synthetic"}, "acme/x", "reserved"),
            ({**ACME, "id": "other"}, "acme/x", "reserved"),
            ({**ACME, "id": "Bad-Id"}, "acme/x", "id must"),
            ({**ACME, "access": "video_node"}, "acme/x", "access"),
            ({**ACME, "access": "privileged"}, "acme/x", "access"),
            ({**ACME, "cap_add": ["SYS_ADMIN"]}, "acme/x", "Unknown manifest keys"),
            ({**ACME, "probe_command": ["sh", "-c", "rm -rf /"]}, "acme/x", "probe_command"),
            ({**ACME, "probe_command": ["a;b"]}, "acme/x", "probe_command"),
            ({**ACME, "probe_command": []}, "acme/x", "probe_command"),
            ({**IPCAM, "usb": {"vendor_id": "1d6b"}}, "acme/x", "usb is only"),
            ({**ACME, "usb": {"vendor_id": "xyz"}}, "acme/x", "vendor_id"),
            (ACME, "mrp-camera-ids", "built-in"),
            (ACME, "evil/mrp-camera-ids:latest", "built-in"),
            (ACME, "docker.io/mrp-camera-realsense", "built-in"),
            (ACME, "localhost/acme", "image"),
            (ACME, "acme/x;touch /tmp/p", "image"),
            (ACME, None, "image"),
            ({**ACME, "label": ""}, "acme/x", "label"),
        ]
        for manifest, image, message in bad:
            with (
                self.subTest(manifest=manifest, image=image),
                self.assertRaisesRegex(cameras.CameraModelError, message),
            ):
                cameras.parse_manifest(manifest, image, "custom")

    def test_labels_mark_camera_drivers_only(self):
        self.assertIsNone(cameras.parse_labels({}, "x"))
        self.assertIsNone(cameras.parse_labels({cameras.LABEL_KIND: "robot"}, "x"))
        self.assertIsNone(cameras.parse_labels(None, "x"))
        ident, model = cameras.parse_labels(labels(ACME), "acme/camera-x1:1.0")
        self.assertEqual((ident, model["origin"]), ("acme_x1", "discovered"))
        with self.assertRaisesRegex(cameras.CameraModelError, "not valid JSON"):
            cameras.parse_labels({cameras.LABEL_KIND: "camera", cameras.LABEL_MANIFEST: "{"}, "x")

    def test_custom_wins_over_discovered_and_builtin_ids_never_merge(self):
        custom = dict([cameras.parse_manifest(ACME, "acme/mine", "custom")])
        found = dict([cameras.parse_manifest(ACME, "acme/found", "discovered")])
        found["realsense"] = {"image": "x"}
        merged = cameras.merge(custom, found)
        self.assertEqual(list(merged), ["acme_x1"])
        self.assertEqual(merged["acme_x1"]["image"], "acme/mine")

    def test_a_broken_custom_file_reports_instead_of_failing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "camera_models.json"
            self.assertEqual(cameras.load_custom(path), ({}, []))
            path.write_text("{")
            self.assertIn("could not be read", cameras.load_custom(path)[1][0])
            path.write_text(
                json.dumps({"models": [{**ACME, "image": "acme/x"}, {**ACME, "id": "realsense"}]})
            )
            models, problems = cameras.load_custom(path)
            self.assertEqual(list(models), ["acme_x1"])
            self.assertIn("reserved", problems[0])


class RegisteredModelTests(unittest.TestCase):
    """Once registered, a custom model is a camera source and layout type like the built-in ones."""

    def setUp(self):
        cameras.set_extra(
            dict(
                [
                    cameras.parse_manifest(ACME, "acme/camera-x1:1.0", "custom"),
                    cameras.parse_manifest(IPCAM, "acme/rtsp:2", "discovered"),
                ]
            )
        )

    def tearDown(self):
        cameras.set_extra({})

    def spec(self, *camera_list):
        return {
            "task_id": "pipeline_check",
            "leader": "mock",
            "follower": "mock",
            "cameras": list(camera_list),
        }

    def test_cells_accept_registered_models_and_their_devices(self):
        spec, preset = validate_spec(
            self.spec(
                {"id": "top", "source": "acme_x1", "variant": "mono", "device": {"serial": "A1"}},
                {"id": "door", "source": "ipcam", "device": {"address": "192.168.1.50"}},
            )
        )
        self.assertEqual(preset, "mock-so101")
        self.assertEqual(spec["camera"], "opencv_usb")  # presets only know "a real camera"
        self.assertEqual(spec["cameras"][1]["device"], {"address": "192.168.1.50"})

    def test_devices_follow_the_model_access(self):
        for camera, message in [
            ({"id": "top", "source": "acme_x1", "variant": "zoom"}, "no variant"),
            ({"id": "top", "source": "acme_x1", "device": {"device": "/dev/video0"}}, "may only contain"),
            ({"id": "top", "source": "ipcam", "device": {"serial": "A1"}}, "may only contain"),
            ({"id": "top", "source": "ipcam", "device": {"address": "a b"}}, "address"),
        ]:
            with self.subTest(camera=camera), self.assertRaisesRegex(CellSpecError, message):
                validate_spec(self.spec(camera))
        with self.assertRaisesRegex(CellSpecError, "different address"):
            validate_spec(
                self.spec(
                    {"id": "a", "source": "ipcam", "device": {"address": "10.0.0.2"}},
                    {"id": "b", "source": "ipcam", "device": {"address": "10.0.0.2"}},
                )
            )

    def test_unregistered_models_are_rejected_again(self):
        cameras.set_extra({})
        with self.assertRaisesRegex(CellSpecError, "source must be one of"):
            validate_spec(self.spec({"id": "top", "source": "acme_x1"}))

    def test_layout_offers_and_accepts_registered_models(self):
        described = cell_layout.describe()["module_types"]["camera"]
        self.assertIn("acme_x1", described["properties"]["model"]["options"])
        self.assertEqual(described["models"]["acme_x1"]["origin"], "custom")
        self.assertEqual(described["models"]["realsense"]["origin"], "builtin")
        self.assertEqual(described["models"]["acme_x1"]["variants"], {"mono": "Mono", "color": "Color"})
        layout = copy.deepcopy(cell_layout.default_layout("mock-so101"))  # never edit the shared template
        camera = next(m for m in layout["modules"] if m["type"] == "camera")
        camera["properties"].update(model="acme_x1", variant="color")
        cell_layout.validate_layout(layout)
        camera["properties"]["variant"] = "zoom"
        with self.assertRaises(cell_layout.LayoutError):
            cell_layout.validate_layout(layout)

    def test_only_usb_bus_models_reach_the_usb_bus_and_never_with_capabilities(self):
        services = {name: {} for name in PRESET_SERVICES["mock-so101"]}
        services.update(
            leader={"environment": {"BACKEND": "mock"}}, follower={"environment": {"BACKEND": "mock"}}
        )
        usb = {"image": "acme/camera-x1:1.0", "device_cgroup_rules": ["c 189:* rmw"],
               "volumes": [{"type": "bind", "source": "/dev/bus/usb", "target": "/dev/bus/usb"}]}  # fmt: skip
        extra = {"services": {"camera_top"}, "usb_bus": {"camera_top": "acme/camera-x1:1.0"}}
        check_plan({"services": {**services, "camera_top": usb}}, "mock-so101", extra=extra)
        for service in (
            {**usb, "image": "acme/other"},
            {**usb, "cap_add": ["NET_ADMIN", "SYS_NICE"]},
            {**usb, "privileged": True},
        ):
            with self.subTest(service=service), self.assertRaises(ValueError):
                check_plan({"services": {**services, "camera_top": service}}, "mock-so101", extra=extra)
        # A network camera is not in the usb_bus map: no USB bus for it.
        with self.assertRaises(ValueError):
            check_plan(
                {"services": {**services, "camera_top": {**usb, "image": "acme/rtsp:2"}}},
                "mock-so101",
                extra={"services": {"camera_top"}, "usb_bus": {}},
            )

    def test_sources_include_registered_models(self):
        self.assertIn("acme_x1", components.camera_sources())
        self.assertIn("synthetic", components.camera_sources())


sys.path[:0] = [str(BASE / "deployment"), str(ROOT / "core/cell_config")]
try:
    import agent
    from test_devices import FakeCompose, fake_sysfs
except ModuleNotFoundError:  # pragma: no cover - workspace dependency missing
    agent = None


@unittest.skipIf(agent is None, "MRP workspace dependency not available")
class AgentCameraTests(unittest.TestCase):
    """The agent finds labelled driver images, merges the custom store and runs them in cells."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(cameras.set_extra, {})
        self.sys = Path(self.temp.name) / "sys"
        fake_sysfs(self.sys)
        self.models_file = Path(self.temp.name) / "camera_models.json"
        self.images = {"acme/camera-x1:1.0": labels(ACME), "busybox:latest": {}}
        self.missing = {"mrp-camera-ids"}
        self.pulls, self.probes = [], []
        self.probe_report = {"ok": True, "width": 640, "height": 480, "resolution_ok": True,
                             "fps": 30.0, "frames": 90, "log": []}  # fmt: skip

        def runner(command, **_):
            joined = " ".join(command)
            if command[1:3] == ["image", "ls"]:
                return subprocess.CompletedProcess(command, 0, "\n".join(self.images) + "\n", "")
            if command[1:3] == ["image", "inspect"]:
                ref = command[-1]
                if "{{json .Config.Labels}}" in command:
                    return subprocess.CompletedProcess(command, 0, json.dumps(self.images.get(ref)), "")
                present = ref in self.images or (ref.startswith("mrp-") and ref not in self.missing)
                return subprocess.CompletedProcess(command, 0 if present else 1, "sha256:x", "")
            if command[1] == "pull":
                self.pulls.append(command[2])
                return subprocess.CompletedProcess(command, 0, "Status: Downloaded newer image", "")
            if "sdk_camera_probe.py" in joined:
                self.probes.append(command)
                return subprocess.CompletedProcess(command, 0, json.dumps(self.probe_report), "")
            if "ls" in command:  # calibration listing
                return subprocess.CompletedProcess(command, 0, "", "")
            return subprocess.CompletedProcess(command, 0, "sha256:abc", "")

        FakeCompose.calls = self.calls = []
        self.addCleanup(setattr, agent, "ComposePreset", agent.ComposePreset)
        agent.ComposePreset = lambda files, project: FakeCompose(project, files)
        presets = {
            name: FakeCompose("mrp-mock-so101") for name in ("mock-so101", "hwleader-so101", "real-so101")
        }
        self.state = Path(self.temp.name) / "state"
        self.server = agent.make_server(
            presets, Path(self.temp.name) / "exports", port=0, workspace_root=ROOT, sys_root=str(self.sys),
            runner=runner, state_dir=self.state, camera_models_file=self.models_file,
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

    def call(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = Request(self.url + path, data, {"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.load(exc)

    def store(self, *entries):
        self.models_file.write_text(json.dumps({"models": list(entries)}))

    def overlay(self):
        return json.loads((self.state / "mrp-mock-so101.cell.json").read_text())["services"]

    def test_catalogue_lists_builtin_discovered_and_custom_models_with_their_images(self):
        self.store({**IPCAM, "image": "acme/rtsp:2"})
        self.images["acme/broken:1"] = {cameras.LABEL_KIND: "camera", cameras.LABEL_MANIFEST: "{"}
        status, catalog = self.call("/api/v1/cameras")
        self.assertEqual(status, 200, catalog)
        models = catalog["models"]
        self.assertEqual(models["acme_x1"]["origin"], "discovered")
        self.assertTrue(models["acme_x1"]["installed"])
        self.assertEqual(models["ipcam"]["origin"], "custom")
        self.assertFalse(models["ipcam"]["installed"])  # not pulled yet
        self.assertEqual(models["realsense"]["origin"], "builtin")
        self.assertTrue(models["realsense"]["installed"])
        self.assertFalse(models["ids_ueye"]["installed"])
        self.assertNotIn("busybox", json.dumps(models))  # unlabelled images are not cameras
        self.assertTrue(any("acme/broken:1" in p for p in catalog["problems"]), catalog["problems"])
        self.assertTrue(catalog["custom_store"])

    def test_a_discovered_camera_runs_its_own_image_with_the_usb_bus_only(self):
        (self.sys / "bus/usb/devices/3-1").mkdir(parents=True)
        for key, value in {
            "idVendor": "1d6b",
            "idProduct": "0001",
            "product": "ACME X1",
            "serial": "A1",
        }.items():
            (self.sys / "bus/usb/devices/3-1" / key).write_text(value)
        cameras_list = [{"id": "top", "source": "acme_x1", "device": {"serial": "A1"}}]
        body = {"preset": "mock-so101", "cameras": cameras_list}
        status, report = self.call("/api/v1/devices/test", body)
        self.assertEqual(status, 200, report)
        self.assertTrue(report["passed"], report)
        names = {c["name"]: c for c in report["checks"]}
        self.assertIn("1 Acme X1 USB device(s) found", names["Camera 'top' connected"]["detail"])
        probe = self.probes[0]
        self.assertIn("acme/camera-x1:1.0", probe)
        self.assertEqual(probe[probe.index("--network") + 1], "none")
        self.assertIn("camera_acme", probe)
        self.assertNotIn("NET_ADMIN", probe)
        status, reply = self.call("/api/v1/deployment/up", body)
        self.assertEqual(status, 200, reply)
        top = self.overlay()["camera"]
        self.assertEqual(top["image"], "acme/camera-x1:1.0")
        self.assertEqual(top["volumes"], ["/dev/bus/usb:/dev/bus/usb"])
        self.assertEqual(top["device_cgroup_rules"], ["c 189:* rmw"])
        self.assertNotIn("cap_add", top)
        self.assertIn("serial_number:='A1'", top["command"])

    def test_a_custom_network_camera_gets_no_host_device(self):
        self.store({**IPCAM, "image": "acme/rtsp:2"})
        self.images["acme/rtsp:2"] = {}
        body = {
            "preset": "mock-so101",
            "cameras": [{"id": "door", "source": "ipcam", "device": {"address": "10.0.0.9"}}],
        }
        status, report = self.call("/api/v1/devices/test", body)
        self.assertEqual(status, 200, report)
        self.assertTrue(report["passed"], report)
        connected = next(c for c in report["checks"] if c["name"] == "Camera 'door' connected")
        self.assertEqual(connected["level"], "warn")  # only opening it can tell
        probe = self.probes[0]
        self.assertEqual(probe[probe.index("--network") + 1], "bridge")
        self.assertNotIn("/dev/bus/usb:/dev/bus/usb", probe)
        status, reply = self.call("/api/v1/deployment/up", body)
        self.assertEqual(status, 200, reply)
        door = self.overlay()["camera"]
        self.assertEqual(door["image"], "acme/rtsp:2")
        self.assertNotIn("volumes", door)
        self.assertNotIn("device_cgroup_rules", door)
        self.assertIn("address:='10.0.0.9'", door["command"])

    def test_a_missing_custom_image_fails_the_test_with_a_way_to_get_it(self):
        self.store({**ACME, "id": "acme_y", "image": "acme/camera-y:1"})
        body = {"preset": "mock-so101", "cameras": [{"id": "top", "source": "acme_y"}]}
        status, report = self.call("/api/v1/devices/test", body)
        self.assertFalse(report["passed"])
        image = next(c for c in report["checks"] if c["name"] == "Camera 'top' driver image")
        self.assertIn("Pull it", image["detail"])

    def test_pull_only_pulls_catalogue_images(self):
        self.store({**IPCAM, "image": "acme/rtsp:2"})
        status, reply = self.call("/api/v1/cameras/pull", {"model": "ipcam"})
        self.assertEqual(status, 200, reply)
        self.assertEqual(self.pulls, ["acme/rtsp:2"])
        for body in ({"model": "realsense"}, {"model": "nope"}, {"model": "ipcam", "image": "evil/x"}):
            with self.subTest(body=body):
                self.assertEqual(self.call("/api/v1/cameras/pull", body)[0], 400)
        self.assertEqual(self.pulls, ["acme/rtsp:2"])

    def test_unknown_models_are_still_refused(self):
        body = {"preset": "mock-so101", "cameras": [{"id": "top", "source": "acme_zzz"}]}
        status, reply = self.call("/api/v1/deployment/up", body)
        self.assertEqual(status, 400)
        self.assertIn("source must be one of", reply["error"])


class ApplicationCameraTests(unittest.TestCase):
    """The web API: add a custom camera, use it in a layout and cell, remove it when unused."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(Path(self.temp.name), DemoRuntime())
        self.server = make_server(self.app, port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.app.close()
        self.temp.cleanup()
        cameras.set_extra({})

    def call(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = Request(self.url + path, data, {"Content-Type": "application/json"} if data else {})
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.load(exc)

    def test_add_use_and_remove_a_custom_camera(self):
        body = {**ACME, "image": "acme/camera-x1:1.0"}
        status, reply = self.call("/api/v1/cameras", body)
        self.assertEqual(status, 400)
        self.assertIn("trust", reply["error"])
        status, reply = self.call("/api/v1/cameras", {**body, "trusted": True})
        self.assertEqual(status, 200, reply)
        self.assertEqual(reply["cameras"]["models"]["acme_x1"]["origin"], "custom")
        stored = json.loads((Path(self.temp.name) / "camera_models.json").read_text())
        self.assertEqual(stored["models"][0]["image"], "acme/camera-x1:1.0")
        self.assertNotIn("trusted", stored["models"][0])

        status, catalog = self.call("/api/v1/catalog")
        self.assertEqual(catalog["layout"]["module_types"]["camera"]["models"]["acme_x1"]["label"], "Acme X1")
        self.assertIn("acme_x1", catalog["cameras"]["models"])

        status, project = self.call("/api/v1/projects", {"name": "Custom camera cell"})
        self.assertEqual(status, 200, project)
        layout = project["cell_layout"]
        camera = next(m for m in layout["modules"] if m["type"] == "camera")
        camera["properties"].update(model="acme_x1", variant="mono")
        status, saved = self.call(f"/api/v1/projects/{project['id']}/layout", {"layout": layout})
        self.assertEqual(status, 200, saved)
        cell = {
            "task_id": "pipeline_check",
            "leader": "mock",
            "follower": "mock",
            "cameras": [{"id": "top", "source": "synthetic", "model": "acme_x1"}],
        }
        status, saved = self.call(f"/api/v1/projects/{project['id']}/cell", {"cell": cell})
        self.assertEqual(status, 200, saved)

        status, reply = self.call("/api/v1/cameras/acme_x1/delete", {})
        self.assertEqual(status, 409)
        self.assertIn("Custom camera cell", reply["error"])
        camera["properties"]["model"] = "opencv_usb"
        camera["properties"].pop("variant")
        self.assertEqual(self.call(f"/api/v1/projects/{project['id']}/layout", {"layout": layout})[0], 200)
        cell["cameras"][0]["model"] = "opencv_usb"
        self.assertEqual(self.call(f"/api/v1/projects/{project['id']}/cell", {"cell": cell})[0], 200)
        status, reply = self.call("/api/v1/cameras/acme_x1/delete", {})
        self.assertEqual(status, 200, reply)
        self.assertNotIn("acme_x1", reply["cameras"]["models"])
        self.assertEqual(self.call("/api/v1/cameras/acme_x1/delete", {})[0], 404)

    def test_invalid_custom_cameras_are_refused(self):
        for body in (
            {**ACME, "image": "mrp-camera-realsense", "trusted": True},
            {**ACME, "image": "acme/x", "access": "video_node", "trusted": True},
            {**ACME, "image": "acme/x", "trusted": True, "privileged": True},
        ):
            with self.subTest(body=body):
                self.assertEqual(self.call("/api/v1/cameras", body)[0], 400)

    def test_pulling_needs_an_agent(self):
        self.assertEqual(self.call("/api/v1/cameras/acme_x1/pull", {})[0], 503)

    def test_agent_models_are_checked_again_and_a_blind_agent_is_reported(self):
        self.app.agent_url = "http://agent.invalid"
        (Path(self.temp.name) / "camera_models.json").write_text(
            json.dumps({"models": [{**ACME, "image": "acme/camera-x1:1.0"}]})
        )
        good = dict([cameras.parse_manifest(IPCAM, "acme/rtsp", "discovered")])
        reported = {
            "models": {**cameras.describe()["models"], **good,
                       "evil": {**good["ipcam"], "image": "mrp-camera-ids", "origin": "discovered"}},
            "custom_store": False, "problems": [],
        }  # fmt: skip
        from unittest.mock import patch

        with patch("mrp_app.service.remote_json", return_value=reported):
            catalog = self.app.cameras(refresh=True)
        self.assertIn("ipcam", catalog["models"])
        self.assertNotIn("evil", catalog["models"])
        self.assertIn("ipcam", cameras.models())
        self.assertNotIn("evil", cameras.models())
        self.assertTrue(any("does not see the custom cameras" in p for p in catalog["problems"]))


if __name__ == "__main__":
    unittest.main()
