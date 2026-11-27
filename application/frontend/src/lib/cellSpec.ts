import {
  cleanArms,
  cleanCameras,
  deriveArms,
  deriveCameras,
  isRealCamera,
  layoutHasArmList,
  layoutHasCameraList,
  listProblems,
  moduleModel,
} from "./cellComponents";
import type {
  ArmCatalog,
  ArmEntry,
  CameraEntry,
  CellLayout,
  CellSettings,
  CellSpec,
  Devices,
  JointMappingEntry,
  Project,
} from "../types";

export type Mode = "mock" | "real";
/** Arm model ids from catalog.arms.models; cells saved before models existed are SO-101. */
export const DEFAULT_ARM_MODEL = "so101";
export type Selection = {
  leader: Mode;
  follower: Mode;
  leaderModel: string;
  followerModel: string;
  /** Per-arm settings when the layout has several leaders or followers; null = one pair above. */
  arms: ArmEntry[] | null;
  /** Per-camera settings when the layout places cameras; null = main/side camera settings. */
  cameras: CameraEntry[] | null;
  camera: "synthetic" | "opencv_usb";
  mockMotion: boolean;
  devices: Devices;
  images: NonNullable<CellSpec["images"]>;
  settings: CellSettings;
};

export const defaultSettings: CellSettings = {
  camera: { width: 640, height: 480, fps: 30 },
  side_camera: { enabled: false, source: "synthetic", width: 640, height: 480, fps: 30 },
  recording: {
    minimum_duration_seconds: 5,
    preflight_min_free_gib: 10,
    maximum_camera_gap_ms: 0,
    instruction: "",
  },
  mock_motion: { seed: 0, speed: 1, mode: "waypoints" },
  teleop: {
    validity_ms: 80,
    max_leader_age_ms: 200,
    source_timeout_ms: 200,
    max_handover_jump_rad: 0.15,
    joint_mapping: {},
  },
};

/** Settings limits, mirrored from the backend (which validates them again). */
export const limits = {
  width: [160, 1920],
  height: [120, 1080],
  fps: [5, 60],
  minimum_duration_seconds: [1, 600],
  preflight_min_free_gib: [0.5, 1000],
  maximum_camera_gap_ms: [0, 1000],
  speed: [0.2, 3],
  seed: [0, 2147483647],
  validity_ms: [20, 100],
  max_leader_age_ms: [20, 2000],
  source_timeout_ms: [50, 5000],
  max_handover_jump_rad: [0.01, 0.5],
  scale: [-10, 10],
  reference_rad: [-6.3, 6.3],
} as const;

const JOINT = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;

export const defaultSelection: Selection = {
  leader: "mock",
  follower: "mock",
  leaderModel: DEFAULT_ARM_MODEL,
  followerModel: DEFAULT_ARM_MODEL,
  arms: null,
  cameras: null,
  camera: "synthetic",
  mockMotion: false,
  devices: {},
  images: {},
  settings: defaultSettings,
};

export function mergeSettings(saved?: CellSpec["settings"]): CellSettings {
  return {
    camera: { ...defaultSettings.camera, ...saved?.camera },
    side_camera: { ...defaultSettings.side_camera, ...saved?.side_camera },
    recording: { ...defaultSettings.recording, ...saved?.recording },
    mock_motion: { ...defaultSettings.mock_motion, ...saved?.mock_motion },
    teleop: {
      ...defaultSettings.teleop,
      ...saved?.teleop,
      joint_mapping: { ...saved?.teleop?.joint_mapping },
    },
  };
}

export function inRange(value: number, key: keyof typeof limits): boolean {
  const [low, high] = limits[key];
  // 0 means "automatic" for the camera gap; otherwise it must be at least 30 ms.
  if (key === "maximum_camera_gap_ms" && value > 0 && value < 30) return false;
  if (key === "scale" && Math.abs(value) < 0.01) return false;
  return Number.isFinite(value) && value >= low && value <= high;
}

/** Every setting that has a limit, so the page can block saving an invalid value. */
export function settingsErrors(settings: CellSettings): string[] {
  const checks: [string, number, keyof typeof limits][] = [
    ["camera width", settings.camera.width, "width"],
    ["camera height", settings.camera.height, "height"],
    ["camera fps", settings.camera.fps, "fps"],
    ["minimum duration", settings.recording.minimum_duration_seconds, "minimum_duration_seconds"],
    ["free disk space", settings.recording.preflight_min_free_gib, "preflight_min_free_gib"],
    ["camera gap", settings.recording.maximum_camera_gap_ms, "maximum_camera_gap_ms"],
    ["motion speed", settings.mock_motion.speed, "speed"],
    ["motion seed", settings.mock_motion.seed, "seed"],
    ["teleop intent validity", settings.teleop.validity_ms, "validity_ms"],
    ["max leader age", settings.teleop.max_leader_age_ms, "max_leader_age_ms"],
    ["source timeout", settings.teleop.source_timeout_ms, "source_timeout_ms"],
    ["max handover jump", settings.teleop.max_handover_jump_rad, "max_handover_jump_rad"],
  ];
  for (const [joint, entry] of Object.entries(settings.teleop.joint_mapping)) {
    if (entry.scale !== undefined) checks.push([`${joint} scale`, entry.scale, "scale"]);
    for (const key of ["leader_reference_rad", "follower_reference_rad"] as const) {
      const value = entry[key];
      if (value !== undefined)
        checks.push([`${joint} ${key.split("_")[0]} reference`, value, "reference_rad"]);
    }
  }
  if (settings.side_camera.enabled)
    checks.push(
      ["side camera width", settings.side_camera.width, "width"],
      ["side camera height", settings.side_camera.height, "height"],
      ["side camera fps", settings.side_camera.fps, "fps"],
    );
  const errors = checks.filter(([, value, key]) => !inRange(value, key)).map(([label]) => label);
  if (settings.recording.instruction.length > 200)
    errors.push("task instruction (max 200 characters)");
  for (const [joint, entry] of Object.entries(settings.teleop.joint_mapping))
    if (entry.leader_joint !== undefined && !JOINT.test(entry.leader_joint))
      errors.push(`${joint} leader joint name`);
  return errors;
}

/** Set one field of a joint's mapping; unset fields are dropped, and so is an empty entry. */
export function setJointMapping(
  mapping: Record<string, JointMappingEntry>,
  joint: string,
  key: keyof JointMappingEntry,
  value: string | number | undefined,
): Record<string, JointMappingEntry> {
  const entry: JointMappingEntry = { ...mapping[joint] };
  if (value === undefined || value === "") delete entry[key];
  else Object.assign(entry, { [key]: value });
  const next = { ...mapping };
  if (Object.keys(entry).length) next[joint] = entry;
  else delete next[joint];
  return next;
}

/** A real follower may only be driven by the real leader, never by a mock one. */
export function followerAllowed(leader: Mode): boolean {
  return leader === "real";
}

/** The single-pair backends a selection stands for (any real arm of a role makes it "real"). */
export function backends(selection: Selection): { leader: Mode; follower: Mode } {
  const { arms } = selection;
  if (!arms) return { leader: selection.leader, follower: selection.follower };
  const real = (role: ArmEntry["role"]) =>
    arms.some((arm) => arm.role === role && arm.backend === "real");
  return { leader: real("leader") ? "real" : "mock", follower: real("follower") ? "real" : "mock" };
}

export function presetFor(selection: Selection): string {
  const { leader, follower } = backends(selection);
  if (leader === "real" && follower === "real") return "real-so101";
  if (leader === "real") return "hwleader-so101";
  return "mock-so101";
}

/** Switch to per-arm/per-camera lists where the workspace layout asks for them. */
export function withLayout(selection: Selection, layout?: CellLayout): Selection {
  const pair: ArmEntry[] = [
    { id: "leader", role: "leader", backend: selection.leader, model: selection.leaderModel,
      device: selection.devices.leader },
    { id: "follower", role: "follower", backend: selection.follower, model: selection.followerModel,
      device: selection.devices.follower, leader: "leader",
      joint_mapping: selection.settings.teleop.joint_mapping },
  ]; // prettier-ignore
  const arms = layoutHasArmList(layout) ? deriveArms(layout, selection.arms ?? pair) : null;
  const cameras = layoutHasCameraList(layout) ? deriveCameras(layout, selection.cameras) : null;
  // One leader and one follower keep the single-pair form; their type still comes from the layout.
  const single = (role: ArmEntry["role"]) =>
    moduleModel(
      (layout?.modules ?? []).find(
        (m) => m.type === "arm" && m.enabled !== false && m.properties.role === role,
      ),
    );
  return {
    ...selection,
    arms,
    cameras,
    leaderModel: arms ? selection.leaderModel : (single("leader") ?? selection.leaderModel),
    followerModel: arms ? selection.followerModel : (single("follower") ?? selection.followerModel),
  };
}

export function allLeadersMock(selection: Selection): boolean {
  return backends(selection).leader === "mock";
}

export function usesSideUsb(selection: Selection): boolean {
  return (
    !selection.cameras &&
    selection.settings.side_camera.enabled &&
    selection.settings.side_camera.source === "opencv_usb"
  );
}

export function usesMainUsb(selection: Selection): boolean {
  return !selection.cameras && selection.camera === "opencv_usb";
}

export function hasRealDevices(selection: Selection): boolean {
  const { leader, follower } = backends(selection);
  return (
    leader === "real" ||
    follower === "real" ||
    usesMainUsb(selection) ||
    usesSideUsb(selection) ||
    Boolean(selection.cameras?.some(isRealCamera))
  );
}

export function movesMotors(selection: Selection): boolean {
  return backends(selection).follower === "real";
}

/** The cell body for POST /api/v1/projects/{id}/cell; only devices that are in use are sent. */
export function buildCell(selection: Selection): CellSpec {
  const pair = backends(selection);
  const real = pair.leader === "real" && pair.follower === "real";
  const devices: Devices = {};
  if (!selection.arms) {
    if (selection.leader === "real" && selection.devices.leader)
      devices.leader = selection.devices.leader;
    if (selection.follower === "real" && selection.devices.follower)
      devices.follower = selection.devices.follower;
  }
  if (usesMainUsb(selection) && selection.devices.camera) devices.camera = selection.devices.camera;
  if (usesSideUsb(selection) && selection.devices.side_camera)
    devices.side_camera = selection.devices.side_camera;
  const cell: CellSpec = { task_id: real ? "free_teleop" : "pipeline_check" };
  if (selection.arms) cell.arms = cleanArms(selection.arms);
  else
    Object.assign(cell, {
      leader: selection.leader,
      follower: selection.follower,
      leader_model: selection.leaderModel,
      follower_model: selection.followerModel,
    });
  if (selection.cameras) cell.cameras = cleanCameras(selection.cameras);
  else cell.camera = selection.camera;
  if (Object.keys(devices).length) cell.devices = devices;
  const images = Object.fromEntries(
    Object.entries(selection.images)
      .filter(([, image]) => image.trim())
      .map(([role, image]) => [role, image.trim()]),
  );
  if (Object.keys(images).length) cell.images = images;
  cell.settings = {
    ...selection.settings,
    // Listed components keep these per entry; the backend rejects both forms at once.
    teleop: selection.arms
      ? { ...selection.settings.teleop, joint_mapping: {} }
      : selection.settings.teleop,
    side_camera: selection.cameras
      ? { ...selection.settings.side_camera, enabled: false }
      : selection.settings.side_camera,
  };
  if (selection.mockMotion && pair.leader === "mock") cell.mock_motion = true;
  return cell;
}

export function fromProject(project?: Project): Selection {
  const spec = project?.cell_spec;
  if (!spec || (spec.follower !== "mock" && spec.follower !== "real"))
    return withLayout(defaultSelection, project?.cell_layout);
  // A listed cell that no longer has several arms falls back to its first pair's choices.
  const first = (role: ArmEntry["role"]) => spec.arms?.find((arm) => arm.role === role);
  const leaderDevice = first("leader")?.device;
  const followerDevice = first("follower")?.device;
  return withLayout(
    {
      arms: spec.arms ?? null,
      cameras: spec.cameras ?? null,
      leader: spec.leader === "real" ? "real" : "mock",
      follower: spec.follower,
      leaderModel: spec.leader_model ?? first("leader")?.model ?? DEFAULT_ARM_MODEL,
      followerModel: spec.follower_model ?? first("follower")?.model ?? DEFAULT_ARM_MODEL,
      camera: spec.camera === "opencv_usb" ? "opencv_usb" : "synthetic",
      mockMotion: Boolean(spec.mock_motion),
      devices: {
        ...(leaderDevice && { leader: leaderDevice }),
        ...(followerDevice && { follower: followerDevice }),
        ...spec.devices,
      },
      images: spec.images ?? {},
      settings: spec.arms
        ? mergeSettings({
            ...spec.settings,
            teleop: { ...spec.settings?.teleop, joint_mapping: first("follower")?.joint_mapping },
          })
        : mergeSettings(spec.settings),
    },
    project?.cell_layout,
  );
}

/** What is still missing before the connection test can run. */
export function missingDevices(selection: Selection): string[] {
  const missing: string[] = listProblems(selection.arms, selection.cameras);
  if (!selection.arms && selection.leader === "real" && !selection.devices.leader?.port)
    missing.push("leader port");
  if (!selection.arms && selection.follower === "real" && !selection.devices.follower?.port)
    missing.push("follower port");
  if (usesMainUsb(selection) && !selection.devices.camera?.device) missing.push("USB camera");
  if (usesSideUsb(selection) && !selection.devices.side_camera?.device)
    missing.push("side USB camera");
  if (
    usesMainUsb(selection) &&
    usesSideUsb(selection) &&
    selection.devices.camera?.device &&
    selection.devices.camera.device === selection.devices.side_camera?.device
  )
    missing.push("different devices for the two cameras");
  const { leader, follower } = selection.devices;
  if (
    !selection.arms &&
    selection.leader === "real" &&
    selection.follower === "real" &&
    leader?.port &&
    leader.port === follower?.port
  )
    missing.push("different ports for leader and follower");
  return missing;
}

export type ArmChoice = { id: string; label: string; disabled: boolean; hint?: string };

/** The models a role can pick; planned ones are listed but disabled, with the reason. */
export function armChoices(
  catalog: ArmCatalog | undefined,
  role: "leader" | "follower",
): ArmChoice[] {
  if (!catalog) return [{ id: DEFAULT_ARM_MODEL, label: "SO-101", disabled: false }];
  return Object.entries(catalog.models)
    .filter(([, arm]) => arm.roles.includes(role))
    .map(([id, arm]) => ({
      id,
      label: arm.status === "planned" ? `${arm.label} (planned)` : arm.label,
      disabled: arm.status !== "available",
      hint: arm.note,
    }));
}
