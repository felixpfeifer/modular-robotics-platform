#!/usr/bin/env python3
"""Read-only probe and calibration capture for SO-101 arms (Feetech STS3215 servos).

Stdlib only (Linux termios), so it runs in the robot image or on the host. Every command
prints one JSON document on stdout. It never writes servo registers: the calibration
steps only read positions and write a YAML file in the format of
config/calibration/follower.example.yaml. The driver applies that file at startup.

  so101_probe.py scan PORT
  so101_probe.py watch PORT [--seconds 5]
  so101_probe.py calibrate PORT --role leader|follower --dir DIR --step zero|range|save [--name FILE.yaml]
                 [--seconds 10]

Calibration needs torque OFF so the arm can be moved by hand: stop the cell first.
"""

import argparse
import json
import os
import re
import select
import sys
import termios
import time
from pathlib import Path

JOINTS = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
]
IDS = [1, 2, 3, 4, 5, 6]
STS3215_MODEL = 777
RESOLUTION = 4096
CENTER = RESOLUTION // 2

# STS control table addresses.
ADDR_MODEL = 3  # 2 bytes
ADDR_HOMING_OFFSET = 31  # 2 bytes, sign-magnitude (bit 11)
ADDR_TORQUE_ENABLE = 40
ADDR_PRESENT_POSITION = 56  # 2 bytes
ADDR_PRESENT_VOLTAGE = 62  # 0.1 V
ADDR_PRESENT_TEMPERATURE = 63
INST_PING, INST_READ = 0x01, 0x02  # no write instruction is implemented on purpose


class ProbeError(RuntimeError):
    pass


def checksum(payload):
    return (~sum(payload)) & 0xFF


def packet(servo_id, instruction, params=()):
    body = [servo_id, len(params) + 2, instruction, *params]
    return bytes([0xFF, 0xFF, *body, checksum(body)])


def decode_sign_magnitude(value, bit=11):
    return -(value & ~(1 << bit)) if value & (1 << bit) else value


class Bus:
    """Half-duplex Feetech bus on a tty at 1 Mbaud, or any object with a compatible `io`."""

    def __init__(self, port=None, io=None, timeout=0.05):
        self.timeout = timeout
        self.fd = None
        self.io = io
        if io is None:
            self.fd = self._open(port)

    @staticmethod
    def _open(port):
        try:
            fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError as exc:
            raise ProbeError(f"Cannot open {port}: {exc.strerror}") from exc
        attrs = termios.tcgetattr(fd)
        attrs[0] = 0  # iflag
        attrs[1] = 0  # oflag
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[3] = 0  # lflag: raw
        attrs[4] = attrs[5] = termios.B1000000
        attrs[6][termios.VMIN], attrs[6][termios.VTIME] = 0, 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIOFLUSH)
        return fd

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _write(self, data):
        if self.io is not None:
            return self.io.write(data)
        termios.tcflush(self.fd, termios.TCIFLUSH)
        os.write(self.fd, data)

    def _read(self, count):
        if self.io is not None:
            return self.io.read(count)
        data = b""
        deadline = time.monotonic() + self.timeout
        while len(data) < count and time.monotonic() < deadline:
            ready, _, _ = select.select(
                [self.fd], [], [], max(0.0, deadline - time.monotonic())
            )
            if ready:
                data += os.read(self.fd, count - len(data))
        return data

    def request(self, servo_id, instruction, params=()):
        """Return the response parameters, or None when the servo did not answer."""
        self._write(packet(servo_id, instruction, params))
        # The tty is half duplex: the transmitted packet may be echoed first.
        header = self._read(4)
        if len(header) < 4:
            return None
        if header[:2] != b"\xff\xff":
            return None
        if header[2] != servo_id:
            return None
        length = header[3]
        rest = self._read(length)
        if len(rest) < length or checksum(header[2:] + rest[:-1]) != rest[-1]:
            return None
        return list(rest[1:-1])  # drop error byte and checksum

    def ping(self, servo_id):
        return self.request(servo_id, INST_PING) is not None

    def read(self, servo_id, address, length):
        data = self.request(servo_id, INST_READ, [address, length])
        if data is None or len(data) != length:
            return None
        return int.from_bytes(bytes(data), "little")


def inspect_servo(bus, servo_id):
    if not bus.ping(servo_id):
        return {"id": servo_id, "present": False}
    model = bus.read(servo_id, ADDR_MODEL, 2)
    voltage = bus.read(servo_id, ADDR_PRESENT_VOLTAGE, 1)
    offset = bus.read(servo_id, ADDR_HOMING_OFFSET, 2)
    return {
        "id": servo_id,
        "present": True,
        "model": model,
        "is_sts3215": model == STS3215_MODEL,
        "voltage_v": None if voltage is None else voltage / 10.0,
        "temperature_c": bus.read(servo_id, ADDR_PRESENT_TEMPERATURE, 1),
        "position": bus.read(servo_id, ADDR_PRESENT_POSITION, 2),
        "homing_offset": None if offset is None else decode_sign_magnitude(offset),
        "torque_enabled": bus.read(servo_id, ADDR_TORQUE_ENABLE, 1) == 1,
    }


def scan(bus):
    servos = [inspect_servo(bus, servo_id) for servo_id in IDS]
    problems = []
    for servo in servos:
        if not servo["present"]:
            problems.append(
                f"Servo {servo['id']} ({JOINTS[servo['id'] - 1]}) does not answer."
            )
        elif not servo["is_sts3215"]:
            problems.append(
                f"Servo {servo['id']} is not an STS3215 (model {servo['model']})."
            )
    voltages = [s["voltage_v"] for s in servos if s.get("voltage_v")]
    return {
        "ok": not problems,
        "problems": problems,
        "servos": servos,
        "voltage_v": round(sum(voltages) / len(voltages), 1) if voltages else None,
        "torque_enabled": any(s.get("torque_enabled") for s in servos),
    }


def sample_positions(bus, seconds, rate_hz=20.0):
    """Collect present positions for all six joints; returns {id: [positions]}."""
    samples = {servo_id: [] for servo_id in IDS}
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        started = time.monotonic()
        for servo_id in IDS:
            position = bus.read(servo_id, ADDR_PRESENT_POSITION, 2)
            if position is not None:
                samples[servo_id].append(position)
        time.sleep(max(0.0, 1.0 / rate_hz - (time.monotonic() - started)))
    return samples


def circular_span(values):
    """Smallest arc (in ticks) covering all positions on the 0..4095 circle."""
    if not values:
        return 0
    ordered = sorted(set(values))
    gaps = [(b - a) for a, b in zip(ordered, ordered[1:])] + [
        ordered[0] + RESOLUTION - ordered[-1]
    ]
    return RESOLUTION - max(gaps)


def watch(bus, seconds):
    samples = sample_positions(bus, seconds)
    return {
        "seconds": seconds,
        "joints": {
            JOINTS[i - 1]: {
                "id": i,
                "samples": len(values),
                "travel": circular_span(values),
                "last": values[-1] if values else None,
            }
            for i, values in samples.items()
        },
        "total_travel": sum(circular_span(v) for v in samples.values()),
    }


def to_new_frame(raw, new_offset):
    return (raw - new_offset) % RESOLUTION


def calibration_name(value):
    """A plain calibration file name such as left_follower.yaml (no paths)."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,60}\.ya?ml", value or ""):
        raise argparse.ArgumentTypeError(
            "calibration name must be a plain .yaml file name"
        )
    return value


def calibrate(bus, role, directory, step, seconds=10.0, name=None):
    directory = Path(directory)
    session = Path(name).stem if name else role
    state_path = directory / f".session-{session}.json"
    state = json.loads(state_path.read_text()) if state_path.is_file() else {}
    info = scan(bus)
    if not info["ok"]:
        raise ProbeError("; ".join(info["problems"]))
    if info["torque_enabled"]:
        raise ProbeError(
            "Servo torque is on. Stop the cell (it releases torque on shutdown) so the arm can be moved by hand."
        )
    servos = {s["id"]: s for s in info["servos"]}
    if step == "zero":
        # present = raw - offset, so raw = present + offset. Zero pose should read 2048.
        offsets = {}
        for servo_id, servo in servos.items():
            raw = (servo["position"] + servo["homing_offset"]) % RESOLUTION
            delta = (raw - CENTER) % RESOLUTION
            offsets[str(servo_id)] = delta - RESOLUTION if delta >= CENTER else delta
        state = {"offsets": offsets}
    elif step == "range":
        if "offsets" not in state:
            raise ProbeError("Capture the zero pose first.")
        offsets = {int(k): v for k, v in state["offsets"].items()}
        end = time.monotonic() + seconds
        previous = state.get("ranges", {})
        low = {i: previous.get(str(i), [RESOLUTION, 0])[0] for i in IDS}
        high = {i: previous.get(str(i), [RESOLUTION, 0])[1] for i in IDS}
        while time.monotonic() < end:
            for servo_id in IDS:
                present = bus.read(servo_id, ADDR_PRESENT_POSITION, 2)
                offset = bus.read(servo_id, ADDR_HOMING_OFFSET, 2)
                if present is None or offset is None:
                    continue
                raw = (present + decode_sign_magnitude(offset)) % RESOLUTION
                position = to_new_frame(raw, offsets[servo_id])
                low[servo_id], high[servo_id] = (
                    min(low[servo_id], position),
                    max(high[servo_id], position),
                )
            time.sleep(0.02)
        state["ranges"] = {str(i): [low[i], high[i]] for i in IDS if low[i] <= high[i]}
    elif step == "save":
        if "offsets" not in state or "ranges" not in state:
            raise ProbeError("Capture the zero pose and the joint ranges first.")
        missing = [JOINTS[i - 1] for i in IDS if str(i) not in state["ranges"]]
        stuck = [
            JOINTS[i - 1]
            for i in IDS
            if str(i) in state["ranges"]
            and state["ranges"][str(i)][1] - state["ranges"][str(i)][0] < 50
        ]
        if missing or stuck:
            raise ProbeError(
                "These joints were not moved through their range: "
                + ", ".join(missing + stuck)
            )
        lines = [f"# SO-101 {role} calibration captured by so101_probe.py", "joints:"]
        for i in IDS:
            low, high = state["ranges"][str(i)]
            lines.append(
                f"  {JOINTS[i - 1]}: {{id: {i}, homing_offset: {state['offsets'][str(i)]}, "
                f"range_min: {low}, range_max: {high}}}"
            )
        target = directory / (name or f"{role}.yaml")
        temporary = directory / f".{target.name}.tmp"
        temporary.write_text("\n".join(lines) + "\n")
        os.replace(temporary, target)
        state_path.unlink(missing_ok=True)
        return {"saved": str(target.name), "joints": len(IDS)}
    else:
        raise ProbeError("Unknown calibration step.")
    directory.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state))
    return {"step": step, "state": state}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("scan", "watch", "calibrate"):
        command = sub.add_parser(name)
        command.add_argument("port")
        if name != "scan":
            command.add_argument(
                "--seconds", type=float, default=5.0 if name == "watch" else 10.0
            )
        if name == "calibrate":
            command.add_argument(
                "--role", choices=["leader", "follower"], required=True
            )
            command.add_argument("--dir", required=True)
            command.add_argument(
                "--step", choices=["zero", "range", "save"], required=True
            )
            # One file per arm when a cell has several leaders or followers.
            command.add_argument("--name", type=calibration_name, default=None)
    args = parser.parse_args(argv)
    try:
        bus = Bus(args.port)
        try:
            if args.command == "scan":
                result = scan(bus)
            elif args.command == "watch":
                result = watch(bus, max(0.5, min(args.seconds, 60.0)))
            else:
                result = calibrate(
                    bus,
                    args.role,
                    args.dir,
                    args.step,
                    max(1.0, min(args.seconds, 120.0)),
                    args.name,
                )
        finally:
            bus.close()
    except ProbeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
