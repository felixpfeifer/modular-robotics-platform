export type Finding = { rule_id: string; severity: string; summary: string };
export type Hint = { title: string; why: string; fix: string; showDetail?: boolean };
export type Verdict = { errors: Finding[]; warnings: Finding[]; checked: boolean };

/** Failing and warning findings from a validation.json document (unknown shape is tolerated). */
export function parseVerdict(validation: unknown): Verdict {
  const findings = (validation as { findings?: unknown })?.findings;
  if (!Array.isArray(findings)) return { errors: [], warnings: [], checked: false };
  const list = findings.filter(
    (item): item is Finding =>
      typeof item === "object" && item !== null && typeof (item as Finding).rule_id === "string",
  );
  return {
    errors: list.filter((f) => f.severity === "error" || f.severity === "fatal"),
    warnings: list.filter((f) => f.severity === "warning"),
    checked: true,
  };
}

const CAMERA = /^camera(?:\.([a-z0-9_]+))?\.(max_gap|fps|coverage|decode|dimensions|format|blank)$/;
const CAMERA_HINTS: Record<string, Omit<Hint, "title"> & { title: (camera: string) => string }> = {
  max_gap: {
    title: (camera) => `${camera}: frames arrived too late`,
    why: "There was a pause between two camera frames that was longer than the allowed limit, so the video would stutter in training.",
    fix: "Lower the camera fps or resolution (Components > Settings), switch off the second camera, close heavy programs, then record again. For a USB camera, brighter light avoids slow exposure. If the cause is a one-off stall, you can allow a longer gap (Components > Settings > Recording > Max camera gap).",
    showDetail: true,
  },
  fps: {
    title: (camera) => `${camera}: wrong frame rate`,
    why: "The camera delivered a different frame rate than the one configured for recording.",
    fix: "Run the connection test, use the frame rate it measures (Components > Settings), and record again.",
    showDetail: true,
  },
  coverage: {
    title: (camera) => `${camera}: missing frames`,
    why: "Too many camera frames were missing during the episode.",
    fix: "Lower the camera fps or resolution and check the USB connection, then record again.",
    showDetail: true,
  },
  decode: {
    title: (camera) => `${camera}: broken images`,
    why: "Some camera images could not be decoded.",
    fix: "Re-plug the camera or restart the cell, then record again.",
  },
  dimensions: {
    title: (camera) => `${camera}: wrong image size`,
    why: "The images do not have the configured resolution.",
    fix: "Make the camera resolution in Settings match what the camera delivers (run the connection test).",
    showDetail: true,
  },
  format: {
    title: (camera) => `${camera}: wrong image format`,
    why: "The camera images are not in the expected format.",
    fix: "Restart the cell. If it repeats, check the camera settings.",
  },
  blank: {
    title: (camera) => `${camera}: images are blank`,
    why: "The camera produced black or empty images.",
    fix: "Check the lens cover, lighting and the camera connection.",
  },
};

const EXACT: Record<string, Hint> = {
  "sync.action_causal_coverage": {
    title: "Some camera frames had no valid robot command",
    why: "At the time those images were taken, the recorder had no command that was still valid. Training needs a valid command for each frame.",
    fix: "Wait until Action is ready before recording. Keep teleoperation enabled until you click Success or Failure. If this repeats, check the leader and teleoperation logs for missing or late commands.",
  },
  "sync.state_max": {
    title: "Robot state and camera are out of sync",
    why: "Robot joint readings and camera frames were too far apart in time.",
    fix: "Lower the camera load (fps, resolution, second camera) and close other programs, then record again.",
    showDetail: true,
  },
  "episode.minimum_duration": {
    title: "The episode was too short",
    why: "Episodes shorter than the configured minimum are not accepted.",
    fix: "Record for longer, or lower the minimum duration (Components > Settings > Recording).",
    showDetail: true,
  },
  "episode.operator_success": {
    title: "The episode was not marked as a success",
    why: "Only episodes you mark as success are accepted for training.",
    fix: "Mark Success when the task worked, or record again.",
  },
  "command.no_rejection": {
    title: "The robot rejected some commands",
    why: "The arbiter or bridge refused commands, for example outside joint limits or when the leader and follower were not aligned.",
    fix: "Move the leader to match the follower before enabling teleoperation and stay within the joint limits.",
  },
  "safety.no_error": {
    title: "A safety event happened",
    why: "A safety error was recorded during the episode.",
    fix: "Check the safety events in the recording, fix the cause, then record again.",
  },
  "writer.no_drops": {
    title: "The recorder dropped data",
    why: "The recorder could not write all messages fast enough.",
    fix: "Free disk space, lower camera fps or resolution, and record again.",
  },
  "writer.no_errors": {
    title: "The recorder reported write errors",
    why: "Writing the recording failed.",
    fix: "Check free disk space and the recorder log, then record again.",
  },
  "action.schema_finite_limits": {
    title: "Invalid robot commands",
    why: "Some commands had invalid or out-of-range values.",
    fix: "Check the leader arm and calibration.",
  },
  "state.schema_finite_limits": {
    title: "Invalid robot state",
    why: "Some robot joint readings were invalid or out of range.",
    fix: "Check the follower arm and calibration.",
  },
};

const PREFIX: [string, Hint][] = [
  [
    "storage.",
    {
      title: "The recording file is damaged",
      why: "The saved file failed an integrity check.",
      fix: "Record again. If it repeats, check disk space and health.",
    },
  ],
  [
    "metadata.",
    {
      title: "The recording is missing information",
      why: "Required metadata (configuration or calibration) is missing or does not match.",
      fix: "Restart the cell so the configuration is generated again, then record again.",
    },
  ],
  [
    "time.",
    {
      title: "Timestamps are invalid",
      why: "Message timestamps went backwards or were missing.",
      fix: "Restart the cell and record again.",
    },
  ],
];

const label = (name?: string) =>
  name ? `${name[0].toUpperCase()}${name.slice(1)} camera` : "Main camera";

/** A plain-language explanation for a validator rule id. */
export function explain(ruleId: string, summary = ""): Hint {
  const camera = CAMERA.exec(ruleId);
  if (camera) {
    const hint = CAMERA_HINTS[camera[2]];
    const name = camera[1] === "webcam" ? undefined : camera[1];
    return { ...hint, title: hint.title(label(name)) };
  }
  if (ruleId === "sync.action_causal_coverage")
    return { ...EXACT[ruleId], showDetail: /^\d+ of \d+ camera frames\b/.test(summary) };
  if (EXACT[ruleId]) return EXACT[ruleId];
  const prefix = PREFIX.find(([start]) => ruleId.startsWith(start));
  if (prefix) return prefix[1];
  return {
    title: summary || ruleId,
    why: `The check '${ruleId}' failed.`,
    fix: "Open the episode for details, fix the cause and record again.",
  };
}
