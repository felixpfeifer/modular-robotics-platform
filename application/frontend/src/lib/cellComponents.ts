import type { ArmEntry, CameraEntry, CameraModelId, CellLayout, LayoutModule } from "../types";

export type { ArmEntry, CameraEntry };

/** The built-in camera models. Discovered and custom ones come from the catalogue at runtime. */
export const CAMERA_MODELS: CameraModelId[] = ["opencv_usb", "realsense", "ids_ueye"];
export const DEFAULT_CAMERA_MODEL: CameraModelId = "opencv_usb";
const MOCK_CAMERA_SOURCES = ["synthetic", "gazebo_scene"];

/** A camera that runs a hardware driver (any source except the mocks), custom models included. */
export const isRealCamera = (camera: Pick<CameraEntry, "source">) =>
  Boolean(camera.source) && !MOCK_CAMERA_SOURCES.includes(camera.source);

/** The arm/camera type a layout module sets ("other" and missing mean: not set). */
export function moduleModel(module?: LayoutModule | null): string | undefined {
  const model = module?.properties.model;
  return typeof model === "string" && model && model !== "other" ? model : undefined;
}

export function moduleVariant(module?: LayoutModule | null): string | undefined {
  const variant = module?.properties.variant;
  return typeof variant === "string" && variant ? variant : undefined;
}

export const MAX_PER_ROLE = 4;
export const MAX_CAMERAS = 6;
const ARM_ID = /^[a-z][a-z0-9_]{0,15}$/;

/** A backend-safe id from a layout module id or name: lowercase, `_`, starts with a letter. */
export function toId(text: string, used: Set<string>, maxLength = 16, fallback = "arm"): string {
  let base = text
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (!/^[a-z]/.test(base)) base = `${fallback}_${base}`.replace(/_+$/, "");
  base = base.slice(0, maxLength).replace(/_+$/, "") || fallback;
  if (base === "adapter") base = `${fallback}_adapter`.slice(0, maxLength);
  let id = base;
  for (let n = 2; used.has(id); n += 1)
    id = `${base.slice(0, maxLength - String(n).length - 1)}_${n}`;
  used.add(id);
  return id;
}

const enabled = (layout: CellLayout | undefined, type: LayoutModule["type"]) =>
  (layout?.modules ?? []).filter((m) => m.type === type && m.enabled !== false);

function armModules(layout?: CellLayout) {
  const arms = enabled(layout, "arm");
  return {
    leaders: arms.filter((m) => m.properties.role === "leader"),
    followers: arms.filter((m) => m.properties.role === "follower"),
  };
}

/** The layout asks for per-arm settings when it has more than one leader or follower. */
export function layoutHasArmList(layout?: CellLayout): boolean {
  const { leaders, followers } = armModules(layout);
  return leaders.length > 1 || followers.length > 1;
}

/** Cameras come from the layout as soon as it places any. */
export function layoutHasCameraList(layout?: CellLayout): boolean {
  return enabled(layout, "camera").length > 0;
}

/**
 * One arm entry per leader/follower module of the layout. Settings already saved for a module
 * (backend, model, device, mapping, pairing) are kept; new followers are driven by the nearest
 * leader. A layout without a leader (the default templates) gets one implicit leader.
 */
export function deriveArms(layout: CellLayout | undefined, saved: ArmEntry[] | null): ArmEntry[] {
  const { leaders, followers } = armModules(layout);
  const byModule = new Map((saved ?? []).filter((a) => a.module).map((a) => [a.module, a]));
  // Entries without a module (the single pair the cell had before) seed the first new modules.
  const unplaced = (saved ?? []).filter((a) => !a.module || !byModule.has(a.module));
  const take = (role: ArmEntry["role"]) => {
    const index = unplaced.findIndex(
      (a) => a.role === role && !(a.module && byModule.has(a.module)),
    );
    return index < 0 ? undefined : unplaced.splice(index, 1)[0];
  };
  const used = new Set<string>();
  const entry = (module: LayoutModule | null, role: ArmEntry["role"]): ArmEntry => {
    const placed = module ? byModule.get(module.id) : undefined;
    const old = placed ?? take(role);
    // An entry saved for this module keeps its id; a seed from the old single pair does not.
    const id = toId(placed?.id ?? module?.id ?? old?.id ?? role, used);
    // The type and variant are set on the arm module of the layout; that choice wins.
    const arm: ArmEntry = {
      id,
      role,
      backend: old?.backend ?? "mock",
      model: moduleModel(module) ?? old?.model ?? "so101",
    };
    const variant = module ? moduleVariant(module) : old?.variant;
    if (variant) arm.variant = variant;
    if (module) {
      arm.name = module.name;
      arm.module = module.id;
    }
    if (old?.device) arm.device = old.device;
    if (role === "follower") arm.joint_mapping = old?.joint_mapping ?? {};
    return arm;
  };
  const leaderArms = (leaders.length ? leaders : [null])
    .slice(0, MAX_PER_ROLE)
    .map((m) => entry(m, "leader"));
  const followerModules = followers.length ? followers : [null];
  const followerArms = followerModules.slice(0, MAX_PER_ROLE).map((module) => {
    const arm = entry(module, "follower");
    const old = module ? byModule.get(module.id) : undefined;
    const kept = leaderArms.find((l) => l.id === old?.leader);
    arm.leader = (kept ?? nearestLeader(module, leaders, leaderArms)).id;
    return arm;
  });
  return [...leaderArms, ...followerArms];
}

function nearestLeader(module: LayoutModule | null, modules: LayoutModule[], arms: ArmEntry[]) {
  if (!module || !modules.length) return arms[0];
  let best = 0;
  modules.forEach((m, index) => {
    const d = Math.hypot(m.x - module.x, m.y - module.y);
    const bestModule = modules[best];
    if (d < Math.hypot(bestModule.x - module.x, bestModule.y - module.y)) best = index;
  });
  return arms[best] ?? arms[0];
}

const clamp = (value: number, low: number, high: number) =>
  Math.min(high, Math.max(low, Math.round(value)));

/** One camera entry per camera module; resolution and FPS start from the module's properties. */
export function deriveCameras(
  layout: CellLayout | undefined,
  saved: CameraEntry[] | null,
): CameraEntry[] {
  const byModule = new Map((saved ?? []).filter((c) => c.module).map((c) => [c.module, c]));
  const used = new Set<string>();
  return enabled(layout, "camera")
    .slice(0, MAX_CAMERAS)
    .map((module) => {
      const old = byModule.get(module.id);
      // "640x480" and a positive fps from the module; anything else keeps the defaults.
      const size = /^(\d+)\s*x\s*(\d+)$/.exec(String(module.properties.resolution ?? "").trim());
      const fps = Number(module.properties.fps) > 0 ? Number(module.properties.fps) : NaN;
      const [w, h] = size ? [Number(size[1]), Number(size[2])] : [NaN, NaN];
      const layoutModel = moduleModel(module);
      // Any type the layout sets (the backend validated it against the catalogue).
      const model: CameraModelId = layoutModel ?? old?.model ?? DEFAULT_CAMERA_MODEL;
      // A real camera always runs the driver of the type the layout gives it.
      const real = old ? isRealCamera(old) : false;
      const camera: CameraEntry = {
        id: toId(old?.id ?? module.id, used, 24, "camera"),
        source: real ? model : "synthetic",
        model,
        name: module.name,
        module: module.id,
        width: old?.width ?? (Number.isFinite(w) ? clamp(w, 160, 1920) : 640),
        height: old?.height ?? (Number.isFinite(h) ? clamp(h, 120, 1080) : 480),
        fps: old?.fps ?? (Number.isFinite(fps) ? clamp(fps, 5, 60) : 30),
      };
      const variant = moduleVariant(module);
      if (variant) camera.variant = variant;
      // A device chosen for another camera type does not carry over.
      if (old?.device && (old.model ?? DEFAULT_CAMERA_MODEL) === model) camera.device = old.device;
      return camera;
    });
}

export const armLabel = (arm: ArmEntry) => arm.name ?? `${arm.role} ${arm.id}`;

/** What still blocks the connection test for listed arms and cameras. */
export function listProblems(arms: ArmEntry[] | null, cameras: CameraEntry[] | null): string[] {
  const missing: string[] = [];
  for (const arm of arms ?? []) {
    if (!ARM_ID.test(arm.id)) missing.push(`a valid id for ${armLabel(arm)}`);
    if (arm.backend === "real" && !arm.device?.port) missing.push(`${armLabel(arm)} port`);
    if (arm.role === "follower" && arm.backend === "real") {
      const leader = arms?.find((l) => l.id === arm.leader);
      if (leader?.backend !== "real") missing.push(`a real leader for ${armLabel(arm)}`);
    }
  }
  const ports = (arms ?? []).flatMap((a) =>
    a.backend === "real" && a.device?.port ? [a.device.port] : [],
  );
  if (new Set(ports).size !== ports.length) missing.push("a different port for every arm");
  for (const camera of cameras ?? [])
    if (camera.source === "opencv_usb" && !camera.device?.device)
      missing.push(`USB device for ${camera.name ?? camera.id}`);
  // Several SDK cameras of one type are told apart by serial number, network ones by address.
  const realModels = new Set((cameras ?? []).filter(isRealCamera).map((c) => c.source));
  for (const model of [...realModels].filter((m) => m !== "opencv_usb")) {
    const same = (cameras ?? []).filter((c) => c.source === model);
    const byAddress = same.some((c) => c.device?.address !== undefined);
    const values = same.map((c) => (byAddress ? c.device?.address : c.device?.serial) ?? "");
    if (same.length > 1 && (values.includes("") || new Set(values).size !== values.length))
      missing.push(
        `a different ${byAddress ? "address" : "serial number"} for every ${model} camera`,
      );
  }
  const nodes = (cameras ?? []).flatMap((c) =>
    c.source === "opencv_usb" && c.device?.device ? [c.device.device] : [],
  );
  if (new Set(nodes).size !== nodes.length) missing.push("a different device for every camera");
  return missing;
}

/** The arm entries as the backend accepts them: devices only for real arms, mapping for followers. */
export function cleanArms(arms: ArmEntry[]): ArmEntry[] {
  return arms.map((arm) => {
    const clean: ArmEntry = { id: arm.id, role: arm.role, backend: arm.backend, model: arm.model };
    if (arm.variant) clean.variant = arm.variant;
    if (arm.name) clean.name = arm.name;
    if (arm.module) clean.module = arm.module;
    if (arm.backend === "real" && arm.device?.port) clean.device = arm.device;
    if (arm.role === "follower") {
      clean.leader = arm.leader;
      clean.joint_mapping = arm.joint_mapping ?? {};
    }
    return clean;
  });
}

/** The camera entries as the backend accepts them: a device only where that driver uses one. */
export function cleanCameras(cameras: CameraEntry[]): CameraEntry[] {
  return cameras.map(({ device, variant, ...camera }) => {
    const clean: CameraEntry = { ...camera, ...(variant && { variant }) };
    if (camera.source === "opencv_usb" && device?.device) clean.device = device;
    else if (isRealCamera(camera) && device?.address) {
      clean.device = { address: device.address }; // network camera (custom driver)
    } else if (isRealCamera(camera) && camera.source !== "opencv_usb") {
      const sdk = {
        ...(device?.serial && { serial: device.serial }),
        ...(camera.source === "ids_ueye" &&
          device?.connection && { connection: device.connection }),
      };
      if (Object.keys(sdk).length) clean.device = sdk;
    }
    return clean;
  });
}

/** The calibration file a real arm uses unless one is picked (same rule as the backend). */
export function defaultCalibration(arm: ArmEntry, arms: ArmEntry[]): string {
  const only = arms.filter((item) => item.role === arm.role).length === 1;
  return only ? `${arm.role}.yaml` : `${arm.id}.yaml`;
}
