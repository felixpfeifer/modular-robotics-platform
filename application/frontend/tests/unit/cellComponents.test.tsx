import { fireEvent, render, screen, waitFor, within } from "./testUtils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanCameras,
  defaultCalibration,
  deriveArms,
  deriveCameras,
  listProblems,
  toId,
} from "../../src/lib/cellComponents";
import { buildCell, defaultSelection, fromProject, presetFor } from "../../src/lib/cellSpec";
import { CellSetupPage } from "../../src/pages/CellSetupPage";
import type { CellLayout, LayoutModule, Project } from "../../src/types";

const api = vi.hoisted(() => vi.fn());
vi.mock("../../src/api/client", async (importOriginal) =>
  (await import("./apiMock")).fakeClient(await importOriginal(), api),
);

function module(
  id: string,
  type: LayoutModule["type"],
  x: number,
  properties: LayoutModule["properties"] = {},
): LayoutModule {
  return {
    id, type, name: id.replace(/_/g, " "), x, y: 0.1, z: 0.75, yaw_deg: 0, width: 0.1, depth: 0.1,
    height: 0.1, parent: "", enabled: true, notes: "", namespace: "", properties, topics: [],
  }; // prettier-ignore
}

/** Two leader/follower pairs side by side and three cameras, as dropped on the composer. */
const layout: CellLayout = {
  schema_version: "mrp-cell-layout/v1",
  workspace: { name: "Dual", width_m: 1.6, depth_m: 0.9, frame_id: "world" },
  modules: [
    module("leader-left", "arm", 0.1, { role: "leader" }),
    module("leader-right", "arm", 1.5, { role: "leader" }),
    module("arm_left", "arm", 0.4, { role: "follower" }),
    module("arm_right", "arm", 1.2, { role: "follower" }),
    module("cam_top", "camera", 0.8, { resolution: "1280x720", fps: 25 }),
    module("cam_front", "camera", 0.8, { resolution: "640x480", fps: 30 }),
    module("Wrist Cam", "camera", 0.4, {}),
    module("table", "fixture", 0.8),
  ],
};

describe("components from the workspace layout", () => {
  it("makes backend-safe, unique ids", () => {
    const used = new Set<string>();
    expect(toId("leader-left", used)).toBe("leader_left");
    expect(toId("Leader Left", used)).toBe("leader_left_2");
    expect(toId("1st arm", used)).toBe("arm_1st_arm");
    expect(toId("adapter", used)).toBe("arm_adapter");
  });
  it("gives every leader and follower its own entry and pairs followers with the nearest leader", () => {
    const arms = deriveArms(layout, null);
    expect(arms.map((a) => [a.id, a.role, a.leader])).toEqual([
      ["leader_left", "leader", undefined],
      ["leader_right", "leader", undefined],
      ["arm_left", "follower", "leader_left"],
      ["arm_right", "follower", "leader_right"],
    ]);
    // Saved settings stay with their module, including a changed pairing.
    const saved = arms.map((a) =>
      a.id === "arm_right"
        ? { ...a, backend: "real" as const, leader: "leader_left", joint_mapping: { gripper_joint: { scale: -1 } } }
        : a,
    ); // prettier-ignore
    const again = deriveArms(layout, saved);
    expect(again[3]).toMatchObject({ backend: "real", leader: "leader_left" });
    expect(again[3].joint_mapping).toEqual({ gripper_joint: { scale: -1 } });
  });
  it("adds an implicit leader when the layout places only followers", () => {
    const onlyFollowers = {
      ...layout,
      modules: layout.modules.filter((m) => m.properties.role !== "leader"),
    };
    const arms = deriveArms(onlyFollowers, null);
    expect(arms.map((a) => [a.id, a.leader])).toEqual([
      ["leader", undefined],
      ["arm_left", "leader"],
      ["arm_right", "leader"],
    ]);
  });
  it("starts camera settings from the module and keeps saved ones", () => {
    const cameras = deriveCameras(layout, null);
    expect(cameras.map((c) => [c.id, c.width, c.height, c.fps])).toEqual([
      ["cam_top", 1280, 720, 25],
      ["cam_front", 640, 480, 30],
      ["wrist_cam", 640, 480, 30],
    ]);
    const saved = cameras.map((c) =>
      c.id === "cam_front" ? { ...c, source: "opencv_usb" as const, fps: 15 } : c,
    );
    expect(deriveCameras(layout, saved)[1]).toMatchObject({ source: "opencv_usb", fps: 15 });
  });
  it("reports what blocks the test and picks per-arm calibration files", () => {
    const arms = deriveArms(layout, null).map((a) => ({ ...a, backend: "real" as const }));
    expect(listProblems(arms, null)).toContain("arm left port");
    expect(defaultCalibration(arms[2], arms)).toBe("arm_left.yaml");
    const pair = [arms[0], { ...arms[2], leader: arms[0].id }];
    expect(defaultCalibration(pair[1], pair)).toBe("follower.yaml");
    const mockLeader = [{ ...arms[0], backend: "mock" as const }, arms[2]];
    expect(listProblems(mockLeader, null)).toContain("a real leader for arm left");
  });
  it("builds the list form of the cell and picks the preset from the arms", () => {
    const project = { id: "p", name: "P", cell_layout: layout } as Project;
    const selection = fromProject(project);
    expect(selection.arms).toHaveLength(4);
    expect(selection.cameras).toHaveLength(3);
    const cell = buildCell(selection);
    expect(cell.leader).toBeUndefined();
    expect(cell.camera).toBeUndefined();
    expect(cell.arms?.[2]).toEqual({
      id: "arm_left", role: "follower", backend: "mock", model: "so101", name: "arm left",
      module: "arm_left", leader: "leader_left", joint_mapping: {},
    }); // prettier-ignore
    expect(cell.cameras?.map((c) => c.id)).toEqual(["cam_top", "cam_front", "wrist_cam"]);
    expect(cell.settings?.side_camera?.enabled).toBe(false);
    const real = (selection.arms ?? []).map((a) =>
      a.id === "leader_left" || a.id === "arm_left" ? { ...a, backend: "real" as const } : a,
    );
    expect(presetFor({ ...selection, arms: real })).toBe("real-so101");
    expect(buildCell({ ...selection, arms: real }).task_id).toBe("free_teleop");
  });
  it("keeps the classic single pair when the layout has one of each and no cameras", () => {
    const single = {
      ...layout,
      modules: layout.modules.filter((m) => ["leader-left", "arm_left"].includes(m.id)),
    };
    const selection = fromProject({ id: "p", name: "P", cell_layout: single } as Project);
    expect(selection.arms).toBeNull();
    expect(selection.cameras).toBeNull();
    expect(buildCell(selection).leader).toBe("mock");
    expect(buildCell(defaultSelection).arms).toBeUndefined();
  });
  it("falls back to the first pair's choices when the layout drops back to one pair", () => {
    const spec = {
      leader: "real", follower: "mock", camera: "synthetic", task_id: "pipeline_check",
      arms: [
        { id: "l", role: "leader" as const, backend: "real" as const, model: "so101", device: { port: "/dev/ttyACM0" } },
        { id: "f", role: "follower" as const, backend: "mock" as const, model: "so101", leader: "l",
          joint_mapping: { gripper_joint: { scale: -1 } } },
      ],
    }; // prettier-ignore
    const selection = fromProject({ id: "p", name: "P", cell_spec: spec } as Project);
    expect(selection.arms).toBeNull();
    expect(selection.devices.leader).toEqual({ port: "/dev/ttyACM0" });
    expect(selection.settings.teleop.joint_mapping).toEqual({ gripper_joint: { scale: -1 } });
  });
});

describe("device types from the workspace layout", () => {
  const typed: CellLayout = {
    ...layout,
    modules: [
      module("leader-left", "arm", 0.1, { role: "leader", model: "so101" }),
      module("leader-right", "arm", 1.5, { role: "leader", model: "so101" }),
      module("arm_left", "arm", 0.4, { role: "follower", model: "ur", variant: "ur5e" }),
      module("arm_right", "arm", 1.2, { role: "follower", model: "other" }),
      module("cam_top", "camera", 0.8, { model: "ids_ueye" }),
      module("cam_front", "camera", 0.8, { model: "realsense", variant: "d435" }),
    ],
  };

  it("takes each arm's type and variant from its module", () => {
    const arms = deriveArms(typed, [{ id: "arm_left", role: "follower", backend: "mock", model: "so101", module: "arm_left" }]);
    const left = arms.find((a) => a.id === "arm_left")!;
    expect([left.model, left.variant]).toEqual(["ur", "ur5e"]);
    expect(arms.find((a) => a.id === "arm_right")!.model).toBe("so101"); // "other" sets nothing
  }); // prettier-ignore

  it("runs a real camera with the driver of its layout type and drops devices of another type", () => {
    const saved = [
      { id: "cam_top", module: "cam_top", source: "opencv_usb" as const, model: "opencv_usb" as const,
        device: { device: "/dev/video2" }, width: 640, height: 480, fps: 30 },
      { id: "cam_front", module: "cam_front", source: "synthetic" as const, width: 640, height: 480, fps: 30 },
    ]; // prettier-ignore
    const [top, front] = deriveCameras(typed, saved);
    expect([top.source, top.model, top.device]).toEqual(["ids_ueye", "ids_ueye", undefined]);
    expect([front.source, front.model, front.variant]).toEqual(["synthetic", "realsense", "d435"]);
  });

  it("sends only the device fields each driver uses and asks for serials to tell cameras apart", () => {
    const ids = { id: "a", source: "ids_ueye" as const, model: "ids_ueye" as const, width: 640, height: 480, fps: 30 };
    expect(cleanCameras([{ ...ids, device: { serial: "4102", connection: "usb", device: "/dev/video0" } }])[0].device)
      .toEqual({ serial: "4102", connection: "usb" });
    expect(cleanCameras([ids])[0].device).toBeUndefined();
    expect(listProblems(null, [ids, { ...ids, id: "b" }])).toContain(
      "a different serial number for every ids_ueye camera",
    );
  }); // prettier-ignore

  it("treats discovered and custom camera types like built-in drivers", () => {
    const custom: CellLayout = { ...typed, modules: [module("cam_top", "camera", 0.8, { model: "acme_x1", variant: "mono" })] };
    const saved = [{ id: "cam_top", module: "cam_top", source: "acme_x1", model: "acme_x1",
                     device: { serial: "A1" }, width: 640, height: 480, fps: 30 }]; // prettier-ignore
    const [top] = deriveCameras(custom, saved);
    expect([top.source, top.model, top.variant, top.device]).toEqual(["acme_x1", "acme_x1", "mono", { serial: "A1" }]);
    expect(cleanCameras([top])[0].device).toEqual({ serial: "A1" });
    const ip = { id: "door", source: "ipcam", model: "ipcam", width: 640, height: 480, fps: 30, device: { address: "10.0.0.9" } };
    expect(cleanCameras([ip])[0].device).toEqual({ address: "10.0.0.9" });
    expect(listProblems(null, [ip, { ...ip, id: "gate" }])).toContain("a different address for every ipcam camera");
    expect(listProblems(null, [ip, { ...ip, id: "gate", device: { address: "10.0.0.10" } }])).toEqual([]);
  }); // prettier-ignore
});

describe("setup page for a layout with two followers and three cameras", () => {
  const run = vi.fn(async (work: () => Promise<unknown>) => {
    await work();
  });
  beforeEach(() => {
    api.mockReset();
    api.mockResolvedValue({});
  });
  it("shows one settings section per arm and camera and saves the lists", async () => {
    const project = { id: "p1", name: "P", cell_layout: layout } as Project;
    render(<CellSetupPage project={project} busy={false} run={run} />);
    expect(screen.getByRole("heading", { name: "Arms" })).toBeInTheDocument();
    for (const name of ["leader-left", "leader-right", "arm left", "arm right"])
      expect(screen.getByRole("group", { name })).toBeInTheDocument();
    for (const name of ["cam top", "cam front", "Wrist Cam"])
      expect(screen.getByRole("group", { name })).toBeInTheDocument();
    // A follower cannot be real while its leader is mock; switching the leader unlocks it.
    const right = screen.getByRole("group", { name: "arm right" });
    expect(within(right).getByRole("button", { name: "Real" })).toBeDisabled();
    fireEvent.click(
      within(screen.getByRole("group", { name: "leader-right" })).getByRole("button", {
        name: "Real",
      }),
    );
    fireEvent.click(within(right).getByRole("button", { name: "Real" }));
    expect(screen.getByText("real-so101")).toBeInTheDocument();
    expect(screen.getAllByText(/arm right port/).length).toBeGreaterThan(0); // still needed
    const front = screen.getByRole("group", { name: "cam front" });
    fireEvent.change(within(front).getByLabelText("FPS"), { target: { value: "15" } });
    // Mock the pair again so the cell can be saved without devices.
    fireEvent.click(
      within(screen.getByRole("group", { name: "leader-right" })).getByRole("button", {
        name: "Mock",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save cell" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/api/v1/projects/p1/cell",
        expect.objectContaining({
          cell: expect.objectContaining({
            task_id: "pipeline_check",
            arms: expect.arrayContaining([
              expect.objectContaining({ id: "arm_right", backend: "mock", leader: "leader_right" }),
            ]),
            cameras: expect.arrayContaining([
              expect.objectContaining({ id: "cam_front", fps: 15 }),
            ]),
          }),
        }),
      ),
    );
  });
});
