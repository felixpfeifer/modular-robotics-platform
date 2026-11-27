import unittest
import unittest.mock

from mrp_app import arms
from mrp_app.catalog import PRESETS, CellSpecError, describe, validate_spec

MOCK = {"leader": "mock", "follower": "mock", "camera": "synthetic", "task_id": "pipeline_check"}


class ArmInterfaceTests(unittest.TestCase):
    def test_every_model_declares_the_full_interface(self):
        keys = {
            "label", "vendor", "status", "roles", "connection", "backends", "kinematics", "dof",
            "gripper", "leader_output", "command_interfaces", "robot_profile", "safety",
        }  # fmt: skip
        for ident, arm in arms.ARMS.items():
            with self.subTest(arm=ident):
                self.assertLessEqual(keys, set(arm))
                self.assertIn(arm["connection"], arms.CONNECTIONS)
                self.assertLessEqual(set(arm["roles"]), set(arms.ROLES))
                self.assertEqual(set(arm["backends"]), set(arm["roles"]))
                self.assertLessEqual(set(arm["command_interfaces"]), set(arms.COMMAND_INTERFACES))
                self.assertLessEqual(set(arm["safety"]), set(arms.SAFETY))
                if "leader" in arm["roles"]:
                    self.assertIn(arm["leader_output"], arms.LEADER_OUTPUTS)
                if "follower" in arm["roles"]:
                    self.assertTrue(arm["command_interfaces"])
                if arm["status"] == arms.AVAILABLE:
                    self.assertTrue(arm["robot_profile"], "an available model needs a driver profile")

    def test_requested_targets_are_catalogued_as_planned(self):
        for ident, role in [
            ("meta_quest", "leader"),
            ("ur", "follower"),
            ("fanuc", "follower"),
            ("trossen_x_series", "follower"),
            ("trossen_ai", "follower"),
        ]:
            with self.subTest(arm=ident):
                self.assertEqual(arms.ARMS[ident]["status"], arms.PLANNED)
                self.assertIn(role, arms.ARMS[ident]["roles"])

    def test_bindings_follow_from_capabilities(self):
        self.assertEqual(
            arms.binding("so101", "so101"),
            {
                "mapper": "joint_mapping",
                "solver": "none",
                "command": "joint",
                "status": "available",
                "reason": "",
            },
        )
        # A pose leader drives a Cartesian-capable arm directly, a joint-only arm through IK.
        self.assertEqual(arms.binding("meta_quest", "ur")["command"], "cartesian")
        self.assertEqual(arms.binding("meta_quest", "fanuc")["solver"], "ik")
        self.assertEqual(arms.binding("meta_quest", "so101")["status"], "planned")
        # A joint leader only maps onto the same kinematics.
        self.assertEqual(arms.binding("so101", "ur")["status"], "unsupported")
        self.assertEqual(arms.binding("trossen_x_series", "trossen_x_series")["status"], "available")

    def test_catalog_lists_models_and_presets_name_them(self):
        catalog = describe()["arms"]
        self.assertEqual(catalog["interface_version"], arms.INTERFACE_VERSION)
        self.assertIn("meta_quest->ur", catalog["bindings"])
        self.assertNotIn("ur->so101", catalog["bindings"])  # UR is follower-only
        for preset in PRESETS.values():
            self.assertTrue(all(arms.ARMS[m]["status"] == arms.AVAILABLE for m in preset["models"].values()))


class CellModelValidationTests(unittest.TestCase):
    def test_specs_without_models_keep_meaning_so101(self):
        spec, preset = validate_spec(MOCK)
        self.assertEqual(preset, "mock-so101")
        self.assertNotIn("leader_model", spec)
        spec, preset = validate_spec({**MOCK, "leader_model": "so101", "follower_model": "so101"})
        self.assertEqual((spec["follower_model"], preset), ("so101", "mock-so101"))

    def test_planned_unknown_and_misplaced_models_are_rejected(self):
        cases = [
            ({"follower_model": "ur"}, "planned"),
            ({"follower_model": "fanuc"}, "planned"),
            ({"follower_model": "trossen_ai"}, "planned"),
            ({"leader_model": "meta_quest"}, "planned"),
            ({"leader_model": "ur"}, "cannot be used as the leader"),
            ({"follower_model": "kuka"}, "Unknown follower_model"),
            ({"leader_model": 3}, "Unknown leader_model"),
        ]
        for extra, message in cases:
            with self.subTest(extra=extra), self.assertRaises(CellSpecError) as error:
                validate_spec({**MOCK, **extra})
            self.assertIn(message, str(error.exception))

    def test_available_models_still_go_through_the_pairing_rules(self):
        # Pretend the UR driver landed, but no joint leader can drive it.
        ur = {**arms.ARMS["ur"], "status": arms.AVAILABLE}
        with unittest.mock.patch.dict(arms.ARMS, {"ur": ur}):
            with self.assertRaises(CellSpecError) as error:
                validate_spec({**MOCK, "follower_model": "ur"})
        self.assertIn("same kinematics", str(error.exception))


if __name__ == "__main__":
    unittest.main()


class LayoutModelTests(unittest.TestCase):
    """The layout's arm/camera modules pick a catalogue model and an optional variant."""

    def layout(self, **properties):
        from mrp_app.layout import validate_layout

        module_type = properties.pop("type", "arm")
        return validate_layout({
            "workspace": {"name": "W", "width_m": 1, "depth_m": 1},
            "modules": [{"id": "m", "type": module_type, "name": "M", "properties": properties}],
        })["modules"][0]["properties"]  # fmt: skip

    def test_free_text_models_from_old_layouts_map_to_catalogue_ids(self):
        self.assertEqual(self.layout(model="SO-101")["model"], "so101")
        self.assertEqual(self.layout(model="Some custom arm")["model"], "other")

    def test_variants_must_belong_to_the_model(self):
        self.assertEqual(self.layout(model="ur", variant="ur5e")["variant"], "ur5e")
        self.assertNotIn("variant", self.layout(model="so101", variant=""))
        self.assertEqual(self.layout(type="camera", model="realsense", variant="d435")["variant"], "d435")
        from mrp_app.layout import LayoutError

        with self.assertRaises(LayoutError):
            self.layout(model="so101", variant="ur5e")
        with self.assertRaises(LayoutError):
            self.layout(type="camera", model="ids_ueye", variant="d435")

    def test_catalog_lists_model_labels_and_variants(self):
        from mrp_app.layout import describe

        arm = describe()["module_types"]["arm"]
        self.assertEqual(arm["models"]["ur"]["variants"]["ur5e"], "UR5e")
        self.assertIn("ids_ueye", describe()["module_types"]["camera"]["models"])
        self.assertNotIn("models", describe()["module_types"]["zone"])
