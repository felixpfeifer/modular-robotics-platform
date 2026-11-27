import { fireEvent, render, screen, waitFor, within } from "./testUtils";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { formatBytes, formatDuration } from "../../src/lib/format";
import {
  descendants,
  layoutProblems,
  moveWithChildren,
  nextModule,
  placeOn,
  sameLayout,
  topOf,
} from "../../src/lib/layout";
import type { CellLayout, Episode, LayoutCatalog, Status } from "../../src/types";

type Handler = (path: string, body?: unknown) => unknown;
const backend = vi.hoisted(() => ({
  handler: null as null | Handler,
  calls: [] as [string, unknown][],
}));
vi.mock("../../src/api/client", async (importOriginal) =>
  (await import("./apiMock")).fakeClient(await importOriginal(), (path, body) => {
    backend.calls.push([path, body]);
    return backend.handler!(path, body);
  }),
);

import { App } from "../../src/App";
import { preloadPages } from "../../src/router";

// Page chunks load lazily; compile them once so the first visit in a test is not slower.
beforeAll(() => preloadPages(), 30000);

const layout: CellLayout = {
  schema_version: "mrp-cell-layout/v1",
  workspace: { name: "Bench", width_m: 1.2, depth_m: 0.8, frame_id: "world" },
  modules: [
    {
      id: "cam",
      type: "camera",
      name: "Top camera",
      x: 0.6,
      y: 0.4,
      z: 0.5,
      yaw_deg: -90,
      width: 0.07,
      depth: 0.07,
      height: 0.05,
      parent: "",
      enabled: true,
      notes: "",
      namespace: "",
      properties: { fov_deg: 70 },
      topics: [
        { name: "/top/image", type: "sensor_msgs/msg/CompressedImage", role: "observation" },
      ],
    },
  ],
};
const catalog: LayoutCatalog = {
  max_modules: 64,
  module_types: {
    arm: {
      label: "Robot arm",
      color: "#245c56",
      size: [0.14, 0.14],
      height: 0.1,
      defaults: { dof: 6 },
      properties: {},
    },
    camera: {
      label: "Camera",
      color: "#3a6ea5",
      size: [0.07, 0.07],
      height: 0.1,
      defaults: { fov_deg: 70 },
      properties: { fov_deg: { kind: "float", min: 1, max: 180 } },
    },
    sensor: {
      label: "Sensor",
      color: "#888",
      size: [0.06, 0.06],
      height: 0.1,
      defaults: {},
      properties: {},
    },
    input: {
      label: "Operator input",
      color: "#c80",
      size: [0.1, 0.1],
      height: 0.1,
      defaults: {},
      properties: {},
    },
    fixture: {
      label: "Table / fixture",
      color: "#999",
      size: [0.6, 0.4],
      height: 0.1,
      defaults: {},
      properties: {},
    },
    zone: {
      label: "Target / work zone",
      color: "#4a6",
      size: [0.15, 0.1],
      height: 0.1,
      defaults: {},
      properties: {},
    },
    object: {
      label: "Task object",
      color: "#c44",
      size: [0.04, 0.04],
      height: 0.1,
      defaults: {},
      properties: {},
    },
  },
  templates: {
    empty: { label: "Empty workspace", description: "Blank", layout: { ...layout, modules: [] } },
  },
};
const episode: Episode = {
  id: "11111111-2222-4333-8444-555555555555",
  project_id: "p1",
  project_name: "First",
  status: "accepted",
  manifest: { task_id: "pick_up", started_ns: 1_700_000_000_000_000_000 },
  validation: { valid: true },
  size_bytes: 5 * 1024 * 1024,
};

function fakeBackend(episodes: Episode[] = [episode]) {
  const state: Status = {
    mode: "ros",
    runtime: { cell_running: false, active_source: "none", checks: [], message: "Ready" },
    projects: [
      {
        id: "p1",
        name: "First",
        preset: "mock",
        cell_layout: structuredClone(layout),
        layout_saved: false,
      },
      { id: "p2", name: "Second" },
    ],
    sessions: [],
    settings: { hf_token_set: false, hf_namespace: "" },
    export_enabled: true,
  };
  const list = [...episodes];
  backend.handler = (path, body) => {
    if (path === "/api/v1/status") return structuredClone(state);
    if (path === "/api/v1/episodes") return { episodes: structuredClone(list) };
    if (path === "/api/v1/catalog") return { layout: catalog };
    if (path === `/api/v1/episodes/${episode.id}`)
      return {
        ...episode,
        mcap: {
          file: "episode.mcap",
          size_bytes: 100,
          has_summary: true,
          message_count: 300,
          duration_s: 10,
          topics: [
            {
              topic: "/joint_states",
              type: "sensor_msgs/msg/JointState",
              encoding: "cdr",
              messages: 300,
            },
          ],
        },
        mcap_error: null,
      };
    if (path === "/api/v1/projects/p1/rename")
      state.projects[0].name = (body as { name: string }).name;
    if (path === "/api/v1/projects/p2/delete") state.projects.splice(1, 1);
    if (path === "/api/v1/projects/p1/layout") {
      state.projects[0].cell_layout = (body as { layout: CellLayout }).layout;
      state.projects[0].layout_saved = true;
    }
    if (path === `/api/v1/episodes/${episode.id}/delete`) list.splice(0, 1);
    return {};
  };
}
const nav = (name: string) => screen.getAllByRole("link", { name })[0];
const posts = () => backend.calls.filter(([, body]) => body !== undefined);
beforeEach(() => {
  backend.calls = [];
  localStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("layout helpers", () => {
  it("finds problems the server would reject", () => {
    const bad: CellLayout = {
      ...layout,
      modules: [
        { ...layout.modules[0] },
        {
          ...layout.modules[0],
          id: "b",
          name: "TOP CAMERA",
          topics: [{ name: "bad topic", type: "x", role: "" }],
        },
      ],
    };
    const problems = layoutProblems(bad).join("\n");
    expect(problems).toContain("must be unique");
    expect(problems).toContain("not a valid ROS topic name");
    expect(problems).toContain("not a ROS type");
    expect(layoutProblems(layout)).toEqual([]);
  });
  it("creates uniquely named modules centred in the workspace", () => {
    const first = nextModule(layout, catalog, "camera");
    expect(first.name).toBe("Camera 1");
    expect(first.x).toBe(0.6);
    const second = nextModule(
      { ...layout, modules: [...layout.modules, first] },
      catalog,
      "camera",
    );
    expect(second.id).toBe("camera_2");
    expect(sameLayout(layout, structuredClone(layout))).toBe(true);
  });
  it("formats sizes and durations", () => {
    expect(formatBytes(1536)).toBe("1.5 KiB");
    expect(formatBytes(null)).toBe("—");
    expect(formatDuration(75)).toBe("1 min 15 s");
  });
});

describe("stacking", () => {
  const table = {
    ...layout.modules[0],
    id: "table",
    name: "Table",
    type: "fixture" as const,
    x: 0.5,
    y: 0.4,
    z: 0,
    height: 0.75,
  };
  const cube = {
    ...layout.modules[0],
    id: "cube",
    name: "Cube",
    type: "object" as const,
    x: 0.4,
    y: 0.4,
    z: 0,
    height: 0.04,
  };
  const stacked: CellLayout = { ...layout, modules: [table, cube] };
  it("places a module on top of another at the base's top elevation", () => {
    const next = placeOn(stacked, "cube", "table");
    expect(next.modules[1]).toMatchObject({ parent: "table", z: 0.75 });
    expect(topOf(next.modules[1])).toBe(0.79);
    expect(placeOn(next, "cube", "").modules[1]).toMatchObject({ parent: "", z: 0 });
  });
  it("moves riders with their base and keeps them inside the workspace", () => {
    const next = moveWithChildren(placeOn(stacked, "cube", "table"), "table", 1.15, 0.4);
    expect(next.modules[0].x).toBe(1.15);
    expect(next.modules[1].x).toBe(1.05);
    expect([...descendants(placeOn(stacked, "cube", "table"), "table")]).toEqual(["cube"]);
  });
});

describe("workspace management in the app", () => {
  it("renames a project from the projects page", async () => {
    fakeBackend();
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    fireEvent.click(nav("Projects"));
    fireEvent.click(await screen.findByRole("button", { name: "Rename First" }));
    const field = await screen.findByLabelText("Project name");
    expect(screen.getByRole("button", { name: "Rename" })).toBeDisabled();
    fireEvent.change(field, { target: { value: "Sorting bench" } });
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    await waitFor(() =>
      expect(posts()).toContainEqual(["/api/v1/projects/p1/rename", { name: "Sorting bench" }]),
    );
    expect((await screen.findAllByText("Sorting bench")).length).toBeGreaterThan(0);
  });

  it("deletes a project only after confirmation, naming what is kept", async () => {
    fakeBackend();
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    fireEvent.click(nav("Projects"));
    fireEvent.click(await screen.findByRole("button", { name: "Delete Second" }));
    expect(await screen.findByText(/Raw MCAP recordings stay on disk/)).toBeInTheDocument();
    expect(posts().some(([path]) => path === "/api/v1/projects/p2/delete")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Delete project" }));
    await waitFor(() =>
      expect(posts()).toContainEqual(["/api/v1/projects/p2/delete", { confirm: true }]),
    );
    await waitFor(() => expect(screen.queryByRole("button", { name: "Rename Second" })).toBeNull());
  });

  it("lists recorded episodes, shows MCAP topics and deletes after confirmation", async () => {
    fakeBackend();
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    fireEvent.click(nav("Episodes"));
    expect(await screen.findByText("Recorded episodes")).toBeInTheDocument();
    expect(screen.getByText("5.0 MiB")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: `Open episode ${episode.id}` }));
    const details = await screen.findByRole("region", { name: "Episode details" });
    expect(await within(details).findByText("/joint_states")).toBeInTheDocument();
    expect(within(details).getByText("30.0")).toBeInTheDocument(); // 300 msgs / 10 s
    expect(within(details).getByRole("link", { name: /Download MCAP/ })).toHaveAttribute(
      "href",
      `/api/v1/episodes/${episode.id}/recording.mcap`,
    );
    fireEvent.click(within(details).getByRole("button", { name: /Delete recording/ }));
    expect(await screen.findByText(/cannot be undone/)).toBeInTheDocument();
    expect(posts().some(([path]) => path.endsWith("/delete"))).toBe(false);
    fireEvent.click(screen.getAllByRole("button", { name: "Delete recording" }).at(-1)!);
    await waitFor(() =>
      expect(posts()).toContainEqual([`/api/v1/episodes/${episode.id}/delete`, { confirm: true }]),
    );
    expect(await screen.findByText("No recorded episodes here")).toBeInTheDocument();
  });

  it("filters episodes to the active project unless asked for all", async () => {
    fakeBackend([
      episode,
      { ...episode, id: "99999999-2222-4333-8444-555555555555", project_id: "p2" },
    ]);
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    fireEvent.click(nav("Episodes"));
    await screen.findByText("Recorded episodes");
    expect(screen.getAllByRole("row")).toHaveLength(2);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Show" }));
    fireEvent.click(await screen.findByRole("option", { name: "All projects" }));
    expect(screen.getAllByRole("row")).toHaveLength(3);
  });
});

describe("cell configuration page", () => {
  async function openCell() {
    fakeBackend();
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    fireEvent.click(nav("Cell"));
    await screen.findByText("Cell configuration");
    await screen.findByTestId("module-cam");
  }

  it("shows the project's layout and its topic map", async () => {
    await openCell();
    expect(screen.getByText("Template default, not saved yet")).toBeInTheDocument();
    expect(screen.getAllByText("/top/image").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Save layout" })).toBeEnabled();
  });

  it("adds, edits and saves a module", async () => {
    await openCell();
    fireEvent.click(screen.getByRole("button", { name: "Robot arm" }));
    const inspector = await screen.findByLabelText("Settings for Robot arm 1");
    fireEvent.change(within(inspector).getByLabelText("Name"), { target: { value: "Follower" } });
    fireEvent.change(within(inspector).getByLabelText("X"), { target: { value: "0.25" } });
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save layout" }));
    await waitFor(() =>
      expect(posts().some(([p]) => p === "/api/v1/projects/p1/layout")).toBe(true),
    );
    const saved = (
      posts().find(([p]) => p === "/api/v1/projects/p1/layout")![1] as { layout: CellLayout }
    ).layout;
    const arm = saved.modules.find((m) => m.name === "Follower")!;
    expect(arm).toMatchObject({ type: "arm", x: 0.25, y: 0.4, properties: { dof: 6 } });
    await waitFor(() => expect(screen.queryByText("Unsaved changes")).toBeNull());
  });

  it("moves the selected module with the keyboard and removes it with Delete", async () => {
    await openCell();
    fireEvent.pointerDown(screen.getByTestId("module-cam"));
    const canvas = screen.getByRole("application");
    fireEvent.keyDown(canvas, { key: "ArrowRight", shiftKey: true });
    fireEvent.keyDown(canvas, { key: "ArrowUp" });
    const inspector = await screen.findByLabelText("Settings for Top camera");
    expect(within(inspector).getByLabelText("X")).toHaveValue(0.7);
    expect(within(inspector).getByLabelText("Y")).toHaveValue(0.41);
    fireEvent.keyDown(canvas, { key: "Delete" });
    await waitFor(() => expect(screen.queryByTestId("module-cam")).toBeNull());
  });

  it("blocks saving duplicate names and explains why", async () => {
    await openCell();
    fireEvent.pointerDown(screen.getByTestId("module-cam"));
    fireEvent.click(await screen.findByRole("button", { name: "Duplicate module" }));
    const inspector = await screen.findByLabelText("Settings for Top camera 2");
    fireEvent.change(within(inspector).getByLabelText("Name"), { target: { value: "top camera" } });
    expect(await screen.findByText(/Names must be unique/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save layout" })).toBeDisabled();
  });

  it("reverts unsaved edits", async () => {
    await openCell();
    fireEvent.click(screen.getByRole("button", { name: "Target / work zone" }));
    expect(await screen.findByTestId("module-zone_1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Revert" }));
    await waitFor(() => expect(screen.queryByTestId("module-zone_1")).toBeNull());
  });
});

describe("cell levels, demo recording and the pipeline", () => {
  it("highlights one level and stacks a module through the inspector", async () => {
    fakeBackend();
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    fireEvent.click(nav("Cell"));
    await screen.findByTestId("module-cam");
    // The camera sits at 0.5 m, so there are two levels once a floor module is added.
    fireEvent.click(screen.getByRole("button", { name: "Target / work zone" }));
    await screen.findByTestId("module-zone_1");
    fireEvent.click(screen.getByRole("button", { name: "Floor · 0 m" }));
    expect(screen.getByTestId("module-cam")).toHaveAttribute("opacity", "0.22");
    expect(screen.getByTestId("module-zone_1")).toHaveAttribute("opacity", "1");
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getByTestId("module-cam")).toHaveAttribute("opacity", "1");
    // Stack the zone on the camera: elevation follows the base's top (0.5 + 0.05).
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Placed on top of" }));
    fireEvent.click(await screen.findByRole("option", { name: "Top camera" }));
    const inspector = await screen.findByLabelText("Settings for Target / work zone 1");
    expect(within(inspector).getByLabelText("Elevation Z")).toHaveValue(0.55);
    expect(screen.getByTestId("elevation-zone_1")).toBeInTheDocument();
  });

  it("shows the guided pipeline on the overview and opens a step", async () => {
    fakeBackend();
    const base = backend.handler!;
    backend.handler = (path, body) =>
      path === "/api/v1/projects/p1/workflow"
        ? {
            stages: [
              { id: "setup", label: "Cell", state: "done", summary: "Mock" },
              { id: "record", label: "Record", state: "todo", summary: "0 accepted episode(s)" },
              {
                id: "dataset",
                label: "Dataset",
                state: "blocked",
                summary: "",
                blocked_reason: "Record and accept an episode first.",
              },
            ],
            accepted_episode_ids: [],
          }
        : base(path, body);
    render(<App />);
    expect(await screen.findByText("Pipeline")).toBeInTheDocument();
    expect(screen.getByText("Record and accept an episode first.")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Go" })[0]);
    expect(await screen.findByText("Recording studio")).toBeInTheDocument();
  });

  it("explains that training and deployment need the ROS runtime in demo mode", async () => {
    fakeBackend();
    const base = backend.handler!;
    backend.handler = (path, body) => {
      const result = base(path, body) as Status;
      return path === "/api/v1/status"
        ? { ...result, mode: "demo", agent_configured: false }
        : result;
    };
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    fireEvent.click(nav("Train"));
    expect(await screen.findByText("Train a policy")).toBeInTheDocument();
    expect(screen.getByText(/you are in demo mode/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start training/ })).toBeDisabled();
    fireEvent.click(nav("Deploy"));
    expect(await screen.findByText("Deploy and run inference")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Give control to policy" })).toBeDisabled();
  });

  it("lets the operator add a note during a demo recording and shows history", async () => {
    fakeBackend();
    const base = backend.handler!;
    backend.handler = (path, body) => {
      const result = base(path, body) as Status;
      if (path !== "/api/v1/status") return result;
      return {
        ...result,
        mode: "demo",
        runtime: {
          ...result.runtime,
          cell_running: true,
          active_source: "teleop",
          active_episode_id: "s1",
        },
        sessions: [
          {
            id: "s1",
            project_id: "p1",
            state: "recording",
            started: Date.now() / 1000 - 5,
            snapshot: {},
          },
          {
            id: "s0",
            project_id: "p1",
            state: "demo_complete",
            started: 1,
            ended: 9,
            snapshot: {},
          },
        ],
      };
    };
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    fireEvent.click(nav("Record"));
    expect(await screen.findByText(/Demo runtime: this shows the workflow/)).toBeInTheDocument();
    expect(screen.getByText(/^Recording · /)).toBeInTheDocument();
    expect(screen.getByText("demo complete")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Quick note"), {
      target: { value: "dropped the cube" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(posts()).toContainEqual([
        "/api/v1/sessions/s1/mark",
        { kind: "annotation", annotation: "dropped the cube" },
      ]),
    );
  });
});
