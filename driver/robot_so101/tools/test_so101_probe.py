import json
import tempfile
import unittest
from pathlib import Path

import so101_probe as probe


class FakeArm:
    """Simulates six STS3215 servos on a Feetech bus; records any write attempt."""

    def __init__(
        self,
        raw=None,
        offsets=None,
        voltage=70,
        torque=0,
        missing=(),
        model=probe.STS3215_MODEL,
    ):
        self.raw = dict(raw or {i: 2048 for i in probe.IDS})
        self.offsets = dict(offsets or {i: 0 for i in probe.IDS})
        self.voltage, self.torque, self.missing, self.model = (
            voltage,
            torque,
            set(missing),
            model,
        )
        self.pending = b""
        self.instructions = []

    def present(self, servo_id):
        return (self.raw[servo_id] - self.offsets[servo_id]) % probe.RESOLUTION

    def write(self, data):
        self.pending = b""
        assert data[:2] == b"\xff\xff" and data[-1] == probe.checksum(
            list(data[2:-1])
        ), "bad packet"
        servo_id, _, instruction = data[2], data[3], data[4]
        self.instructions.append(instruction)
        if servo_id in self.missing or servo_id not in self.raw:
            return
        params = []
        if instruction == probe.INST_READ:
            address, length = data[5], data[6]
            value = {
                probe.ADDR_MODEL: self.model,
                probe.ADDR_PRESENT_VOLTAGE: self.voltage,
                probe.ADDR_PRESENT_TEMPERATURE: 31,
                probe.ADDR_PRESENT_POSITION: self.present(servo_id),
                probe.ADDR_HOMING_OFFSET: abs(self.offsets[servo_id])
                | (0x800 if self.offsets[servo_id] < 0 else 0),
                probe.ADDR_TORQUE_ENABLE: self.torque,
            }[address]
            params = list(value.to_bytes(length, "little"))
        body = [servo_id, len(params) + 2, 0, *params]
        self.pending = bytes([0xFF, 0xFF, *body, probe.checksum(body)])

    def read(self, count):
        chunk, self.pending = self.pending[:count], self.pending[count:]
        return chunk


class ProbeTests(unittest.TestCase):
    def test_checksum_matches_feetech_ping_frame(self):
        self.assertEqual(
            probe.packet(1, probe.INST_PING),
            bytes([0xFF, 0xFF, 0x01, 0x02, 0x01, 0xFB]),
        )

    def test_scan_reports_servos_and_is_read_only(self):
        arm = FakeArm(offsets={**{i: 0 for i in probe.IDS}, 3: -100})
        result = probe.scan(probe.Bus(io=arm))
        self.assertTrue(result["ok"])
        self.assertEqual(result["voltage_v"], 7.0)
        self.assertEqual(result["servos"][2]["homing_offset"], -100)
        self.assertFalse(result["torque_enabled"])
        self.assertTrue(set(arm.instructions) <= {probe.INST_PING, probe.INST_READ})

    def test_scan_flags_missing_and_wrong_servos(self):
        self.assertIn(
            "Servo 4", probe.scan(probe.Bus(io=FakeArm(missing={4})))["problems"][0]
        )
        wrong = probe.scan(probe.Bus(io=FakeArm(model=1000)))
        self.assertFalse(wrong["ok"])
        self.assertIn("STS3215", wrong["problems"][0])

    def test_circular_span_handles_wraparound(self):
        self.assertEqual(probe.circular_span([4090, 5, 10]), 16)
        self.assertEqual(probe.circular_span([100, 400]), 300)
        self.assertEqual(probe.circular_span([]), 0)

    def test_calibration_round_trip_computes_offsets_from_raw_positions(self):
        # The arm sits 100 ticks off center with an existing offset of 30: raw = present + offset.
        arm = FakeArm(
            raw={i: 2148 for i in probe.IDS}, offsets={i: 30 for i in probe.IDS}
        )
        with tempfile.TemporaryDirectory() as folder:
            bus = probe.Bus(io=arm)
            zero = probe.calibrate(bus, "follower", folder, "zero")
            self.assertEqual(zero["state"]["offsets"]["1"], 100)  # raw 2148 - 2048
            with self.assertRaises(probe.ProbeError):  # joints not moved yet
                probe.calibrate(bus, "follower", folder, "save")
            # Sweep: raw positions move around; the saved range is expressed in the new offset frame.
            state_path = Path(folder) / ".session-follower.json"
            state = json.loads(state_path.read_text())
            state["ranges"] = {str(i): [1500, 2600] for i in probe.IDS}
            state_path.write_text(json.dumps(state))
            saved = probe.calibrate(bus, "follower", folder, "save")
            self.assertEqual(saved["saved"], "follower.yaml")
            text = (Path(folder) / "follower.yaml").read_text()
            self.assertIn(
                "shoulder_pan: {id: 1, homing_offset: 100, range_min: 1500, range_max: 2600}",
                text,
            )
            self.assertFalse(state_path.exists())
        self.assertTrue(set(arm.instructions) <= {probe.INST_PING, probe.INST_READ})

    def test_a_named_calibration_keeps_its_own_session_and_file(self):
        # Two followers of one cell are calibrated one after the other into their own files.
        arm = FakeArm(
            raw={i: 2048 for i in probe.IDS}, offsets={i: 0 for i in probe.IDS}
        )
        with tempfile.TemporaryDirectory() as folder:
            bus = probe.Bus(io=arm)
            probe.calibrate(bus, "follower", folder, "zero", name="right.yaml")
            self.assertTrue((Path(folder) / ".session-right.json").exists())
            self.assertFalse((Path(folder) / ".session-follower.json").exists())
            state_path = Path(folder) / ".session-right.json"
            state = json.loads(state_path.read_text())
            state["ranges"] = {str(i): [1500, 2600] for i in probe.IDS}
            state_path.write_text(json.dumps(state))
            saved = probe.calibrate(bus, "follower", folder, "save", name="right.yaml")
            self.assertEqual(saved["saved"], "right.yaml")
            self.assertFalse((Path(folder) / "follower.yaml").exists())
        for bad in ("../x.yaml", "x.txt", ""):
            with self.subTest(bad=bad), self.assertRaises(Exception):
                probe.calibration_name(bad)

    def test_range_step_uses_new_offset_frame(self):
        arm = FakeArm(raw={i: 2148 for i in probe.IDS})
        with tempfile.TemporaryDirectory() as folder:
            bus = probe.Bus(io=arm)
            probe.calibrate(bus, "leader", folder, "zero")
            result = probe.calibrate(bus, "leader", folder, "range", seconds=1.0)
            # Raw 2148 with new offset 100 -> 2048 for every joint.
            self.assertEqual(result["state"]["ranges"]["2"], [2048, 2048])

    def test_range_samples_accumulate_across_sweeps(self):
        arm = FakeArm(raw={i: 2048 for i in probe.IDS})
        with tempfile.TemporaryDirectory() as folder:
            bus = probe.Bus(io=arm)
            probe.calibrate(bus, "leader", folder, "zero")
            state_path = Path(folder) / ".session-leader.json"
            state = json.loads(state_path.read_text())
            state["ranges"] = {str(i): [1900, 2200] for i in probe.IDS}
            state_path.write_text(json.dumps(state))
            result = probe.calibrate(bus, "leader", folder, "range", seconds=0.05)
            self.assertEqual(result["state"]["ranges"]["1"], [1900, 2200])

    def test_calibration_refuses_when_torque_is_on(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            self.assertRaises(probe.ProbeError) as error,
        ):
            probe.calibrate(probe.Bus(io=FakeArm(torque=1)), "follower", folder, "zero")
        self.assertIn("torque", str(error.exception))


if __name__ == "__main__":
    unittest.main()
