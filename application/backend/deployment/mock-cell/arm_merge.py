"""Pure logic of the arm adapter: merge per-arm joint states, split the combined joint intent.

A multi-arm cell runs every arm in its own namespace. The arbiter, the teleop source and the
recorder see one combined robot whose joints are the arms' joints prefixed with the arm id
(``left_shoulder_pan_joint``). Configuration comes from ``arms.json``, rendered per cell start.
"""

STALE_AFTER_NS = 500_000_000  # an arm silent this long stops the merged state (fail safe)


class StateMerger:
    """Latest state per arm; a merged sample is produced on each update of the first arm."""

    def __init__(self, arms, stale_after_ns=STALE_AFTER_NS):
        if not arms:
            raise ValueError("at least one arm is required")
        self.arms = [(arm["id"], list(arm["joints"]), list(arm["prefixed"])) for arm in arms]
        self.clock_arm = self.arms[0][0]
        self.stale_after_ns = stale_after_ns
        self.latest = {}  # arm id -> (received_ns, {joint: (position, velocity|None, effort|None)})

    @property
    def names(self):
        return [name for _, _, prefixed in self.arms for name in prefixed]

    def update(self, arm_id, names, positions, velocities, efforts, received_ns):
        """Store one arm's JointState; return the merged sample when the clock arm updates."""
        joints = next((joints for ident, joints, _ in self.arms if ident == arm_id), None)
        if joints is None:
            raise ValueError(f"unknown arm {arm_id}")
        values = {}
        for index, name in enumerate(names):
            values[name] = (
                float(positions[index]),
                float(velocities[index]) if len(velocities) == len(names) else None,
                float(efforts[index]) if len(efforts) == len(names) else None,
            )
        if not all(joint in values for joint in joints):
            return None  # incomplete sample: keep the previous one
        self.latest[arm_id] = (received_ns, values)
        if arm_id != self.clock_arm:
            return None
        return self.merged(received_ns)

    def merged(self, now_ns):
        """(names, positions, velocities, efforts), or None while an arm is missing or stale."""
        positions, velocities, efforts = [], [], []
        for ident, joints, _ in self.arms:
            entry = self.latest.get(ident)
            if entry is None or now_ns - entry[0] > self.stale_after_ns:
                return None
            for joint in joints:
                position, velocity, effort = entry[1][joint]
                positions.append(position)
                velocities.append(velocity)
                efforts.append(effort)
        # JointState allows empty velocity/effort arrays; use them unless every arm reports values.
        velocities = velocities if None not in velocities else []
        efforts = efforts if None not in efforts else []
        return self.names, positions, velocities, efforts


def split_intent(names, positions, velocities, followers):
    """One (follower, joint names, positions, velocities) per follower from a combined intent.

    The combined intent must name exactly the followers' prefixed joints; anything else is
    rejected as a whole so that no arm moves on a partial command.
    """
    if len(names) != len(positions) or len(set(names)) != len(names):
        raise ValueError("intent joint names and positions do not align")
    if velocities and len(velocities) != len(names):
        raise ValueError("intent velocities do not align with the joints")
    expected = {name for follower in followers for name in follower["prefixed"]}
    if set(names) != expected:
        raise ValueError(f"intent must contain exactly the {len(expected)} combined follower joints")
    position = dict(zip(names, positions))
    velocity = dict(zip(names, velocities)) if velocities else {}
    parts = []
    for follower in followers:
        prefixed = follower["prefixed"]
        parts.append(
            (
                follower,
                list(follower["joints"]),
                [float(position[name]) for name in prefixed],
                [float(velocity[name]) for name in prefixed] if velocity else [],
            )
        )
    return parts


def load(config):
    """Check an arms.json document and return it."""
    if not isinstance(config, dict) or config.get("schema_version") != "mrp-arm-adapter/v1":
        raise ValueError("arms.json must be mrp-arm-adapter/v1")
    for key in ("followers", "leaders"):
        arms = config.get(key)
        if not isinstance(arms, list) or not arms:
            raise ValueError(f"arms.json needs {key}")
        for arm in arms:
            if len(arm.get("joints", [])) != len(arm.get("prefixed", [])) or not arm["joints"]:
                raise ValueError(f"arm {arm.get('id')} has misaligned joints")
    return config
