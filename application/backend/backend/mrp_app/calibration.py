"""Calibration file format shared by the deployment agent and the configuration bundles."""

import re

CALIBRATION_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,60}\.ya?ml")

CALIBRATION_JOINT = re.compile(
    r"\s+(shoulder_pan|shoulder_lift|elbow_flex|wrist_flex|wrist_roll|gripper):\s*"
    r"\{\s*id:\s*([1-6])\s*,\s*homing_offset:\s*(-?\d{1,5})\s*"
    r"(?:,\s*range_min:\s*(\d{1,4})\s*,\s*range_max:\s*(\d{1,4})\s*)?\}"
)
JOINT_IDS = {
    "shoulder_pan": "1",
    "shoulder_lift": "2",
    "elbow_flex": "3",
    "wrist_flex": "4",
    "wrist_roll": "5",
    "gripper": "6",
}


def validate_calibration(text):
    """Accept only the calibration format the driver reads (see follower.example.yaml).

    Returns the file rewritten from the parsed numbers, so nothing else is ever stored.
    """
    if not isinstance(text, str) or len(text) > 8000:
        raise ValueError("Calibration file is too large or not text.")
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines or lines[0].strip() != "joints:":
        raise ValueError("Calibration file must start with 'joints:'.")
    seen = {}
    for line in lines[1:]:
        match = CALIBRATION_JOINT.fullmatch(line)
        if not match or JOINT_IDS[match[1]] != match[2]:
            raise ValueError(f"Unsupported calibration line: {line[:80]!r}")
        fields = f"id: {match[2]}, homing_offset: {int(match[3])}"
        if match[4] is not None:
            if int(match[4]) > int(match[5]) or int(match[5]) > 4095:
                raise ValueError(f"Invalid range for {match[1]}.")
            fields += f", range_min: {int(match[4])}, range_max: {int(match[5])}"
        seen[match[1]] = f"  {match[1]}: {{{fields}}}"
    if set(seen) != set(JOINT_IDS):
        raise ValueError("Calibration needs all six joints: " + ", ".join(JOINT_IDS))
    return "joints:\n" + "\n".join(seen[name] for name in JOINT_IDS) + "\n"
