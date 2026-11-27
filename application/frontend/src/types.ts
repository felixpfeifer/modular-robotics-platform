export type Project = {
  id: string;
  name: string;
  cell_spec?: CellSpec;
  preset?: string;
  cell_layout?: CellLayout;
  layout_saved?: boolean;
};
export type Session = {
  id: string;
  project_id: string;
  state: string;
  started?: number;
  ended?: number | null;
  detail?: string;
  annotations?: { time: number; text: string }[];
  snapshot: { task_id?: string };
};
export type RobotSample = {
  stamp_ns: number;
  joint_names: string[];
  positions: (number | null)[];
  velocities: (number | null)[];
  fresh: boolean;
  source?: string;
};
export type Runtime = {
  cell_running: boolean;
  active_source: string;
  active_episode_id?: string;
  checks: { name: string; ready: boolean; detail: string }[];
  message: string;
  camera_previews?: string[];
  robot_data_simulated?: boolean;
  robot_data?: Partial<Record<"Leader" | "Follower" | "Action", RobotSample>>;
};
export type Target = {
  id: string;
  name: string;
  runtime: string;
  url: string;
  token_mode: "saved" | "own" | "none";
  token_set: boolean;
};
export type Settings = { hf_token_set: boolean; hf_namespace: string; targets?: Target[] };
export type PolicyRuntime = {
  label: string;
  protocol: string;
  default_port: number;
  needs_gpu: boolean;
  local_train: boolean;
  local_serve: boolean;
  hub_download: boolean;
  note: string;
  local_available?: boolean;
  local_reason?: string;
};
export type Hardware = { gpu: boolean; name: string; vram_gb: number; detail?: string };
export type HubRepo = {
  repo_id: string;
  private: boolean;
  updated: string;
  size: number;
  runtime?: string;
  lerobot?: boolean;
};
export type LaunchCommand = { command: string; notes: string[]; token_included: boolean };
export type Status = {
  mode: "demo" | "ros";
  runtime: Runtime;
  projects: Project[];
  sessions: Session[];
  settings: Settings;
  export_enabled: boolean;
  agent_configured?: boolean;
  jobs?: Job[];
  uploads?: Upload[];
  trainings?: Training[];
  models?: ModelRow[];
  deployments?: Deployment[];
};
export type Episode = {
  id: string;
  project_id?: string | null;
  project_name?: string | null;
  status: string;
  manifest: { task_id?: string; started_ns?: number };
  validation?: unknown;
  size_bytes?: number | null;
  annotations?: { time: number; text: string }[];
};
export type McapTopic = { topic: string; type: string; encoding: string; messages: number | null };
export type EpisodeDetail = Episode & {
  mcap: {
    file: string;
    size_bytes: number;
    has_summary: boolean;
    message_count: number | null;
    duration_s: number | null;
    topics: McapTopic[];
  } | null;
  mcap_error: string | null;
  status_document?: Record<string, unknown>;
};

export type ModuleType = "arm" | "camera" | "sensor" | "input" | "fixture" | "zone" | "object";
export type Topic = { name: string; type: string; role: string };
export type LayoutModule = {
  id: string;
  type: ModuleType;
  name: string;
  x: number;
  y: number;
  z: number;
  yaw_deg: number;
  width: number;
  depth: number;
  height: number;
  parent: string;
  enabled: boolean;
  notes: string;
  namespace: string;
  properties: Record<string, string | number | boolean>;
  topics: Topic[];
};
export type CellLayout = {
  schema_version: string;
  workspace: { name: string; width_m: number; depth_m: number; frame_id: string };
  modules: LayoutModule[];
};
export type PropertyRule =
  | { kind: "enum"; options: string[] }
  | { kind: "int" | "float"; min: number; max: number }
  | { kind: "text"; max_length: number }
  | { kind: "bool" };
export type LayoutCatalog = {
  max_modules: number;
  module_types: Record<
    ModuleType,
    {
      label: string;
      color: string;
      size: [number, number];
      height: number;
      defaults: Record<string, string | number | boolean>;
      properties: Record<string, PropertyRule>;
      /** Arm and camera modules: label, status and variants of every `model` choice. */
      models?: Record<string, ModelChoice>;
    }
  >;
  templates: Record<string, { label: string; description: string; layout: CellLayout }>;
  policies?: Record<string, PolicyInfo>;
  runtimes?: Record<string, PolicyRuntime>;
  hardware?: Hardware;
};
/** One `model` choice of an arm or camera module. Cameras also say where the model comes from. */
export type ModelChoice = {
  label: string;
  status: "available" | "planned";
  variants: Record<string, string>;
  origin?: CameraOrigin;
  /** Whether the driver image is on the deployment host (unknown without an agent). */
  installed?: boolean;
};
/** builtin: first-party driver; discovered: a labelled local image; custom: added in the UI. */
export type CameraOrigin = "builtin" | "discovered" | "custom";
export type PolicyInfo = { label: string; status: "available" | "planned"; note?: string };
export type Stage = {
  id: string;
  label: string;
  state: "done" | "todo" | "blocked" | "active";
  summary: string;
  blocked_reason?: string;
};
export type Workflow = { stages: Stage[]; accepted_episode_ids: string[] };
export type Job = {
  id: string;
  project_id?: string | null;
  state: string;
  created: number;
  detail: string;
  payload?: {
    repo_id?: string;
    episode_ids?: string[];
    format?: string;
    downsample_hz_ratio?: number;
  };
};
export type Upload = {
  id: string;
  state: string;
  detail: string;
  revision?: string | null;
  payload: { export_id?: string; model_id?: string; repo_id: string; visibility: string };
};
export type Training = Job & { payload?: { label?: string; settings?: Record<string, unknown> } };
export type ModelRow = {
  id: string;
  project_id: string;
  source: string;
  label: string;
  path: string;
  state: string;
  created: number;
  detail: string;
  runtime?: string;
  kind?: "local" | "hub";
  repo_id?: string | null;
  revision?: string | null;
};
export type Deployment = Job & { payload?: { action?: string; model?: string } };
export type Page =
  | "overview"
  | "projects"
  | "cell"
  | "devices"
  | "record"
  | "episodes"
  | "dataset"
  | "train"
  | "deploy"
  | "settings";
export type RunAction = (work: () => Promise<unknown>, message: string) => Promise<void>;

export type CameraSettings = { width: number; height: number; fps: number };
export type CellSettings = {
  camera: CameraSettings;
  side_camera: CameraSettings & { enabled: boolean; source: "synthetic" | "opencv_usb" };
  recording: {
    minimum_duration_seconds: number;
    preflight_min_free_gib: number;
    maximum_camera_gap_ms: number;
    instruction: string;
  };
  mock_motion: { seed: number; speed: number; mode: "waypoints" | "sine" };
  teleop: TeleopSettings;
};
/** Per follower joint; every field is optional (unset = same-named leader joint, scale 1, no offset). */
export type JointMappingEntry = {
  leader_joint?: string;
  scale?: number;
  leader_reference_rad?: number;
  follower_reference_rad?: number;
};
export type TeleopSettings = {
  validity_ms: number;
  max_leader_age_ms: number;
  source_timeout_ms: number;
  max_handover_jump_rad: number;
  joint_mapping: Record<string, JointMappingEntry>;
};
/** A driver's profile.json, served by the deployment agent through the catalog. */
export type RobotProfile = {
  id: string;
  label?: string;
  joint_names: string[];
  topics: { joint_states: string; leader_joint_states: string };
};
/** One entry of catalog.arms.models: what a leader/follower device exposes (see arms.py). */
export type ArmModel = {
  label: string;
  vendor: string;
  status: "available" | "planned";
  roles: ("leader" | "follower")[];
  connection: string;
  backends: Partial<Record<"leader" | "follower", string[]>>;
  kinematics: string | null;
  dof: number | null;
  gripper: boolean;
  leader_output: "joint_state" | "cartesian_pose" | null;
  command_interfaces: ("joint" | "cartesian")[];
  robot_profile: string | null;
  safety: string[];
  note?: string;
  /** Variant id -> label, e.g. "ur5e" -> "UR5e". Empty when the model has none. */
  variants: Record<string, string>;
};
/** A real camera driver (backend cameras.py). A real camera's `source` is its model id. */
export type CameraModel = {
  label: string;
  status: "available" | "planned";
  driver: string;
  image: string;
  access: "video_node" | "usb_bus" | "network";
  origin?: CameraOrigin;
  installed?: boolean;
  fps_type?: "int" | "float";
  probe_command?: string[];
  usb?: { vendor_id: string; product?: string };
  connections: string[];
  connections_available?: string[];
  variants: Record<string, string>;
  fields: Record<string, string>;
  note?: string;
};
export type CameraCatalog = {
  default: string;
  models: Record<string, CameraModel>;
  /** Labelled images that could not be read, an unreadable custom store, an agent that cannot see it. */
  problems?: string[];
  custom_store?: boolean;
};
/** What the "Add custom camera" form sends to POST /api/v1/cameras. */
export type CustomCameraRequest = {
  id: string;
  label: string;
  image: string;
  access: "usb_bus" | "network";
  fps_type: "int" | "float";
  probe_command: string[];
  variants?: Record<string, string>;
  usb?: { vendor_id: string; product?: string };
  note?: string;
  trusted: boolean;
  pull: boolean;
};
export type ArmBinding = {
  mapper: string | null;
  solver: string | null;
  command: string | null;
  status: "available" | "planned" | "unsupported";
  reason: string;
};
export type ArmCatalog = {
  interface_version: string;
  default: string;
  models: Record<string, ArmModel>;
  bindings: Record<string, ArmBinding>;
};
/** One leader or follower arm of a cell (spec `arms[]`, see backend components.py). */
export type ArmEntry = {
  id: string;
  role: "leader" | "follower";
  backend: "mock" | "real";
  model: string;
  variant?: string;
  name?: string;
  module?: string;
  /** Followers only: the id of the leader that drives it. */
  leader?: string;
  device?: ArmDevice;
  joint_mapping?: Record<string, JointMappingEntry>;
};
/** One camera of a cell (spec `cameras[]`). The id becomes the topic and the dataset feature. */
export type CameraEntry = {
  id: string;
  /** "synthetic" (mock) or, for a real camera, its model's driver id. */
  source: "synthetic" | CameraModelId;
  /** The camera's type from the layout; the driver used when it is real. */
  model?: CameraModelId;
  variant?: string;
  name?: string;
  module?: string;
  device?: CameraDevice;
  width: number;
  height: number;
  fps: number;
};

export type CellSpec = {
  leader?: string;
  follower?: string;
  leader_model?: string;
  follower_model?: string;
  camera?: string;
  task_id?: string;
  mock_motion?: boolean;
  devices?: Devices;
  images?: Partial<Record<"leader" | "follower" | "camera" | "side_camera", string>>;
  /** Per-arm and per-camera lists, derived from the workspace layout; replace the single-pair keys. */
  arms?: ArmEntry[];
  cameras?: CameraEntry[];
  settings?: Partial<{ [K in keyof CellSettings]: Partial<CellSettings[K]> }>;
};
export type NetworkInfo = { ros_domain_id: string; zenoh_port: string; zenoh_bind: string };
export type ArmDevice = { port?: string; serial?: string; calibration?: string };
/** Built-in ids, or a discovered/custom camera model's id (see CameraCatalog). */
export type CameraModelId = "opencv_usb" | "realsense" | "ids_ueye" | (string & {});
export type CameraDevice = {
  /** SDK cameras (RealSense, IDS): usb or gige. */
  connection?: string;
  /** Network cameras (custom drivers): IP address or host name. */
  address?: string;
  device?: string;
  serial?: string;
  card?: string;
  width?: number;
  height?: number;
  fps?: number;
};
export type Devices = {
  leader?: ArmDevice;
  follower?: ArmDevice;
  camera?: CameraDevice;
  side_camera?: CameraDevice;
};
export type SerialPort = {
  port: string;
  serial: string;
  vendor_id: string;
  product: string;
  likely_so101: boolean;
};
export type VideoDevice = {
  device: string;
  card: string;
  serial: string;
  integrated: boolean;
};
export type DeviceScan = {
  serial: SerialPort[];
  video: VideoDevice[];
  calibrations: string[];
  hints: string[];
  wsl: boolean;
};
export type TestCheck = {
  name: string;
  ok: boolean;
  level: "ok" | "warn" | "error";
  detail: string;
  jpeg_base64?: string | null;
  /** "camera"/"side_camera" for the original two cameras, else the camera id. */
  role?: string;
  camera_id?: string;
  measured_fps?: number;
  target_fps?: number;
};
export type TestResult = { passed: boolean; checks: TestCheck[]; fingerprint: string };
export type IdentifyResult = {
  suggested_leader: string | null;
  suggested_follower: string | null;
  detail: string;
};

/** GET /api/v1/catalog: everything the UI can offer for cells, policies and runtimes. */
export type Catalog = {
  layout?: LayoutCatalog;
  presets?: Record<string, { robot?: string }>;
  robots?: Record<string, RobotProfile>;
  arms?: ArmCatalog;
  cameras?: CameraCatalog;
  policies?: Record<string, PolicyInfo>;
  runtimes?: Record<string, PolicyRuntime>;
  hardware?: Hardware;
};
export type TrainingProgress = {
  status: string;
  step?: number;
  steps?: number;
  percent?: number;
  loss?: number | null;
  seconds_per_step?: number | null;
  eta_seconds?: number | null;
  elapsed_seconds?: number | null;
  step_is_approximate?: boolean;
  log_tail?: string[];
};
export type LaunchRequest = {
  purpose: "serve" | "train";
  runtime: string;
  target?: string;
  repo_id?: string;
  steps?: number;
  batch_size?: number;
};
export type CustomCameraReply = {
  id: string;
  pull: { ok: boolean; detail: string } | null;
  cameras: CameraCatalog;
};
export type CameraActionReply = { ok?: boolean; detail?: string };
export type Backup = { name: string; bytes: number; created: number };
export type BundleReport = {
  valid: boolean;
  applied: boolean;
  errors: string[];
  warnings: string[];
  bundle: { created: string; app_version: string };
  items: {
    calibrations: { name: string; status: "new" | "identical" | "conflict" }[];
    robots: { id: string; label: string; status: "known" | "differs" | "unknown" }[];
    projects: { name: string; original_name: string; preset: string }[];
  };
  result?: {
    calibrations_stored: string[];
    calibrations_kept: string[];
    projects_created: { id: string; name: string }[];
  };
};
export type DatasetValidation = {
  valid?: boolean;
  scope?: string;
  episodes?: number;
  frames?: number;
  error?: string;
};
