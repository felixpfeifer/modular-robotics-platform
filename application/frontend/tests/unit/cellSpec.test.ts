import { describe, expect, it } from "vitest";
import type { ArmCatalog } from "../../src/types";
import {
  armChoices,
  buildCell,
  defaultSelection,
  defaultSettings,
  followerAllowed,
  fromProject,
  hasRealDevices,
  mergeSettings,
  missingDevices,
  presetFor,
  setJointMapping,
  settingsErrors,
} from "../../src/lib/cellSpec";

describe("cell component selection", () => {
  it("maps the staged combinations to presets", () => {
    expect(presetFor(defaultSelection)).toBe("mock-so101");
    expect(presetFor({ ...defaultSelection, leader: "real" })).toBe("hwleader-so101");
    expect(presetFor({ ...defaultSelection, leader: "real", follower: "real" })).toBe("real-so101");
  });
  it("never allows a real follower behind a mock leader", () => {
    expect(followerAllowed("mock")).toBe(false);
    expect(followerAllowed("real")).toBe(true);
  });
  it("sends only devices that are in use and the matching task", () => {
    const cell = buildCell({
      ...defaultSelection,
      leader: "real",
      follower: "mock",
      camera: "opencv_usb",
      mockMotion: true,
      images: {},
      settings: defaultSettings,
      devices: {
        leader: { port: "/dev/ttyACM0", serial: "A" },
        follower: { port: "/dev/ttyACM1" },
        camera: { device: "/dev/video2" },
      },
    });
    expect(cell.devices).toEqual({
      leader: { port: "/dev/ttyACM0", serial: "A" },
      camera: { device: "/dev/video2" },
    });
    expect(cell.mock_motion).toBeUndefined(); // motion only drives a mock leader
    expect(cell.task_id).toBe("pipeline_check");
    expect(buildCell({ ...defaultSelection, leader: "real", follower: "real" }).task_id).toBe(
      "free_teleop",
    );
    expect(buildCell({ ...defaultSelection, mockMotion: true }).mock_motion).toBe(true);
  });
  it("keeps settings with the cell and validates their limits", () => {
    const settings = mergeSettings({
      camera: { fps: 25 },
      recording: { minimum_duration_seconds: 8 },
    });
    expect(settings.camera).toEqual({ width: 640, height: 480, fps: 25 });
    expect(buildCell({ ...defaultSelection, settings }).settings?.camera?.fps).toBe(25);
    expect(settingsErrors(settings)).toEqual([]);
    expect(settingsErrors({ ...settings, camera: { ...settings.camera, fps: 500 } })).toEqual([
      "camera fps",
    ]);
    expect(
      settingsErrors({
        ...settings,
        side_camera: { ...settings.side_camera, enabled: true, width: 1 },
      }),
    ).toEqual(["side camera width"]);
  });
  it("treats a USB side camera as a real device that needs its own node", () => {
    const side = {
      ...defaultSelection,
      settings: mergeSettings({ side_camera: { enabled: true, source: "opencv_usb" } }),
    };
    expect(hasRealDevices(side)).toBe(true);
    expect(missingDevices(side)).toEqual(["side USB camera"]);
    const twice = {
      ...side,
      camera: "opencv_usb" as const,
      devices: { camera: { device: "/dev/video2" }, side_camera: { device: "/dev/video2" } },
    };
    expect(missingDevices(twice)).toEqual(["different devices for the two cameras"]);
    expect(
      buildCell({ ...side, devices: { side_camera: { device: "/dev/video4" } } }).devices,
    ).toEqual({
      side_camera: { device: "/dev/video4" },
    });
  });
  it("reports what is missing before a test can run", () => {
    const real = { ...defaultSelection, leader: "real", follower: "real" } as const;
    expect(missingDevices(real)).toEqual(["leader port", "follower port"]);
    expect(
      missingDevices({
        ...real,
        devices: { leader: { port: "/dev/ttyACM0" }, follower: { port: "/dev/ttyACM0" } },
      }),
    ).toEqual(["different ports for leader and follower"]);
  });
  it("restores a saved selection and falls back to mock for older projects", () => {
    expect(fromProject(undefined)).toEqual(defaultSelection);
    expect(
      fromProject({
        id: "p",
        name: "P",
        cell_spec: { leader: "real", follower: "mock", camera: "synthetic", mock_motion: false },
      }).leader,
    ).toBe("real");
  });
  it("saves and restores custom image references", () => {
    const cell = buildCell({
      ...defaultSelection,
      images: { leader: " acme/robot:v1 ", camera: " " },
    });
    expect(cell.images).toEqual({ leader: "acme/robot:v1" });
    expect(fromProject({ id: "p", name: "P", cell_spec: cell }).images).toEqual(cell.images);
  });
});

describe("teleop settings", () => {
  it("keeps old projects working with teleop defaults", () => {
    const merged = mergeSettings({ camera: { fps: 25 } });
    expect(merged.teleop).toEqual(defaultSettings.teleop);
    expect(merged.teleop.joint_mapping).not.toBe(defaultSettings.teleop.joint_mapping);
  });

  it("stores only the mapping fields that were set and drops empty joints", () => {
    let mapping = setJointMapping({}, "shoulder_pan_joint", "scale", -1);
    mapping = setJointMapping(mapping, "shoulder_pan_joint", "leader_reference_rad", 0.2);
    expect(mapping).toEqual({ shoulder_pan_joint: { scale: -1, leader_reference_rad: 0.2 } });
    mapping = setJointMapping(mapping, "shoulder_pan_joint", "scale", undefined);
    mapping = setJointMapping(mapping, "shoulder_pan_joint", "leader_reference_rad", undefined);
    expect(mapping).toEqual({});
  });

  it("blocks invalid teleop values before saving", () => {
    const teleop = {
      ...defaultSettings.teleop,
      validity_ms: 5,
      joint_mapping: { gripper_joint: { scale: 0, leader_joint: "bad name" } },
    };
    expect(settingsErrors({ ...defaultSettings, teleop })).toEqual([
      "teleop intent validity",
      "gripper_joint scale",
      "gripper_joint leader joint name",
    ]);
  });
});

describe("arm models", () => {
  const arm = (
    label: string,
    status: "available" | "planned",
    roles: ("leader" | "follower")[],
  ) => ({
    label,
    vendor: "",
    status,
    roles,
    connection: "usb_serial",
    backends: {},
    kinematics: null,
    dof: null,
    gripper: false,
    leader_output: null,
    variants: {},
    command_interfaces: [],
    robot_profile: null,
    safety: [],
  });
  const catalog: ArmCatalog = {
    interface_version: "mrp-arm-interface/v1",
    default: "so101",
    bindings: {},
    models: {
      so101: arm("SO-101", "available", ["leader", "follower"]),
      meta_quest: arm("Meta Quest 3", "planned", ["leader"]),
      ur: arm("Universal Robots", "planned", ["follower"]),
    },
  };
  it("lists only the models for a role and disables planned ones", () => {
    expect(armChoices(catalog, "leader").map((c) => [c.id, c.disabled])).toEqual([
      ["so101", false],
      ["meta_quest", true],
    ]);
    expect(armChoices(catalog, "follower").find((c) => c.id === "ur")?.label).toBe(
      "Universal Robots (planned)",
    );
    expect(armChoices(undefined, "follower")).toEqual([
      { id: "so101", label: "SO-101", disabled: false },
    ]);
  });
  it("sends the models and defaults old cells to SO-101", () => {
    const cell = buildCell(defaultSelection);
    expect([cell.leader_model, cell.follower_model]).toEqual(["so101", "so101"]);
    const old = fromProject({
      cell_spec: {
        leader: "real",
        follower: "mock",
        camera: "synthetic",
        task_id: "pipeline_check",
      },
    } as never);
    expect([old.leaderModel, old.followerModel]).toEqual(["so101", "so101"]);
  });
});
