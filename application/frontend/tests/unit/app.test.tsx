import { act, fireEvent, render, screen, waitFor, within } from "./testUtils";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { Episode, Status } from "../../src/types";

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

const posts = () => backend.calls.filter(([, body]) => body !== undefined);
const lastPost = (path: string) =>
  posts()
    .filter(([p]) => p === path)
    .at(-1);

function fakeBackend(overrides: Partial<Status> = {}, episodes: Episode[] = []) {
  const state: Status = {
    mode: "ros",
    runtime: { cell_running: false, active_source: "none", checks: [], message: "Ready" },
    projects: [
      { id: "p1", name: "First", preset: "mock", cell_spec: { task_id: "pick_up" } },
      { id: "p2", name: "Second" },
    ],
    sessions: [],
    settings: { hf_token_set: false, hf_namespace: "" },
    export_enabled: true,
    ...overrides,
  };
  const fail: { next: string | null } = { next: null };
  backend.handler = (path, body) => {
    if (body !== undefined && fail.next) {
      const message = fail.next;
      fail.next = null;
      throw new Error(message);
    }
    if (path === "/api/v1/status") return structuredClone(state);
    if (path === "/api/v1/episodes") return { episodes };
    if (path === "/api/v1/cell/up") state.runtime.cell_running = true;
    if (path === "/api/v1/cell/down") state.runtime.cell_running = false;
    if (path === "/api/v1/control")
      state.runtime.active_source = (body as { source: string }).source;
    if (path === "/api/v1/sessions") state.runtime.active_episode_id = "episode-1";
    if (path.endsWith("/mark")) state.runtime.active_episode_id = undefined;
    if (path === "/api/v1/projects") {
      const project = { id: "p3", name: (body as { name: string }).name };
      state.projects.push(project);
      return project;
    }
    return {};
  };
  return { state, fail };
}

// jsdom renders both the permanent and the (mobile) temporary drawer; use the first.
const nav = (name: string) => screen.getAllByRole("link", { name })[0];
const goTo = async (name: string) => {
  fireEvent.click(nav(name));
  // The top bar names the page once its route has loaded and rendered.
  await screen.findByRole("heading", { level: 1, name });
  if (name === "Record") await screen.findByText("Recording studio");
};

beforeEach(() => {
  backend.calls = [];
  localStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("App", () => {
  it("shows local exports and loads cloud datasets for the selected project", async () => {
    fakeBackend({
      settings: { hf_token_set: true, hf_namespace: "" },
      jobs: [
        {
          id: "finished",
          project_id: "p1",
          state: "complete",
          created: 1,
          detail: "Verified",
          payload: { repo_id: "local/first" },
        },
        { id: "running", project_id: "p1", state: "running", created: 2, detail: "Converting" },
        { id: "old", project_id: null, state: "failed", created: 3, detail: "Failed" },
        { id: "other", project_id: "p2", state: "complete", created: 4, detail: "" },
      ],
    });
    const inner = backend.handler!;
    backend.handler = (path, body) =>
      path === "/api/v1/hub/datasets"
        ? { items: [{ repo_id: "account/dataset", private: true, updated: "", size: 0 }] }
        : inner(path, body);
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    await goTo("Dataset");
    expect(screen.getByText("local/first")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download ZIP" })).toHaveAttribute(
      "href",
      "/api/v1/exports/finished/dataset.zip",
    );
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText(/Unassigned project/)).toBeInTheDocument();
    expect(screen.queryByText("other")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Push to Hub" }));
    fireEvent.change(screen.getByLabelText("Repository"), { target: { value: "account/first" } });
    fireEvent.click(screen.getByLabelText("Public dataset"));
    expect(screen.getByRole("button", { name: "Push dataset" })).toBeDisabled();
    fireEvent.click(screen.getByLabelText("I understand this dataset will be public"));
    fireEvent.click(screen.getByRole("button", { name: "Push dataset" }));
    await waitFor(() =>
      expect(lastPost("/api/v1/uploads")?.[1]).toMatchObject({
        export_id: "finished",
        repo_id: "account/first",
        visibility: "public",
        confirm_public: true,
        use_saved_token: true,
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Browse my Hub datasets" }));
    expect(await screen.findByRole("link", { name: "account/dataset" })).toHaveAttribute(
      "href",
      "https://huggingface.co/datasets/account/dataset",
    );
  });
  it("requires confirmation before publishing a model", async () => {
    fakeBackend({
      settings: { hf_token_set: true, hf_namespace: "account" },
      agent_configured: true,
      models: [
        {
          id: "model1",
          project_id: "p1",
          source: "local_training",
          label: "Test model",
          path: "path",
          state: "complete",
          created: 1,
          detail: "",
          kind: "local",
        },
      ],
    });
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    await goTo("Train");
    fireEvent.click(screen.getByRole("button", { name: "Push model to Hub" }));
    fireEvent.change(screen.getByLabelText("Model repository"), {
      target: { value: "account/model" },
    });
    fireEvent.click(screen.getByLabelText("Public model"));
    expect(screen.getByRole("button", { name: "Push model" })).toBeDisabled();
    fireEvent.click(screen.getByLabelText("I understand this model will be public"));
    fireEvent.click(screen.getByRole("button", { name: "Push model" }));
    await waitFor(() =>
      expect(lastPost("/api/v1/model-uploads")?.[1]).toMatchObject({
        model_id: "model1",
        repo_id: "account/model",
        visibility: "public",
        confirm_public: true,
      }),
    );
  });
  it("shows a spinner, then the workspace once the API answers", async () => {
    fakeBackend();
    render(<App />);
    expect(screen.getByText("Connecting to MRP…")).toBeInTheDocument();
    expect(await screen.findByText("Welcome to MRP Studio")).toBeInTheDocument();
    expect(screen.getAllByText("First").length).toBeGreaterThan(0);
  });

  it("updates live robot data from the socket without waiting for status polling", async () => {
    class FakeWebSocket {
      static instances: FakeWebSocket[] = [];
      closed = false;
      onopen: (() => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      onerror: (() => void) | null = null;
      onclose: ((event: CloseEvent) => void) | null = null;

      constructor(readonly url: string | URL) {
        FakeWebSocket.instances.push(this);
      }

      close() {
        this.closed = true;
        this.onclose?.({} as CloseEvent);
      }
    }
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
    fakeBackend({
      runtime: { cell_running: true, active_source: "teleop", checks: [], message: "Ready" },
    });
    const view = render(<App />);
    try {
      await screen.findByText("Welcome to MRP Studio");
      expect(FakeWebSocket.instances).toHaveLength(0);
      await goTo("Record");
      await waitFor(() =>
        expect(
          FakeWebSocket.instances.some((socket) =>
            String(socket.url).endsWith("/api/v1/telemetry"),
          ),
        ).toBe(true),
      );
      const telemetrySocket = FakeWebSocket.instances.find((socket) =>
        String(socket.url).endsWith("/api/v1/telemetry"),
      )!;
      const sample = {
        stamp_ns: 1,
        joint_names: ["shoulder_pan"],
        positions: [0.75],
        velocities: [0.1],
        fresh: true,
      };
      act(() =>
        telemetrySocket.onmessage?.({
          data: JSON.stringify({
            robot_data: {
              Leader: sample,
              Follower: sample,
              Action: { ...sample, source: "teleop" },
            },
          }),
        } as MessageEvent),
      );
      expect(await screen.findByText("Measured: Live")).toBeInTheDocument();
      expect(screen.getByRole("row", { name: /shoulder_pan/ })).toHaveTextContent("0.750");
      await goTo("Overview");
      expect(telemetrySocket.closed).toBe(true);
    } finally {
      view.unmount();
      vi.unstubAllGlobals();
    }
  });

  it("offers a retry when the API is down and recovers when it returns", async () => {
    backend.handler = () => {
      throw new Error("Network Error");
    };
    render(<App />);
    expect(await screen.findByText("Unable to connect to MRP")).toBeInTheDocument();
    expect(screen.getByText("Network Error")).toBeInTheDocument();
    fakeBackend();
    fireEvent.click(screen.getByRole("button", { name: "Retry connection" }));
    expect(await screen.findByText("Welcome to MRP Studio")).toBeInTheDocument();
  });

  it("selects the first project when none (or a deleted one) is stored", async () => {
    localStorage.setItem("mrp-project", "gone");
    fakeBackend();
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    await waitFor(() => expect(localStorage.getItem("mrp-project")).toBe("p1"));
  });

  it("remembers the chosen project across reloads", async () => {
    localStorage.setItem("mrp-project", "p2");
    fakeBackend();
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Second" })).toBeInTheDocument();
  });

  it("runs the full recording flow with the right API calls", async () => {
    fakeBackend();
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    await goTo("Record");

    const startEpisode = screen.getByRole("button", { name: /Start episode/ });
    expect(startEpisode).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Start cell" }));
    expect(await screen.findByText("Cell started.")).toBeInTheDocument();
    expect(lastPost("/api/v1/cell/up")).toBeTruthy();

    fireEvent.click(await screen.findByRole("button", { name: "Enable teleop" }));
    await screen.findByText("Control source updated.");
    expect(lastPost("/api/v1/control")?.[1]).toEqual({ source: "teleop" });

    fireEvent.click(await screen.findByRole("button", { name: /Start episode/ }));
    await screen.findByText("Recording started.");
    const body = lastPost("/api/v1/sessions")?.[1] as { project_id: string; request_id: string };
    expect(body.project_id).toBe("p1");
    expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(await screen.findByText("Recording in progress")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start episode/ })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Success" }));
    await screen.findByText("Episode marked success.");
    expect(lastPost("/api/v1/sessions/episode-1/mark")?.[1]).toEqual({ kind: "success" });
    expect(await screen.findByText("Ready to record")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Disable teleop" }));
    await waitFor(() => expect(lastPost("/api/v1/control")?.[1]).toEqual({ source: "none" }));
    fireEvent.click(await screen.findByRole("button", { name: "Stop cell" }));
    await screen.findByText("Cell stopped.");
  });

  it("shows the backend's message when an action is refused", async () => {
    const { fail } = fakeBackend();
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    await goTo("Record");
    fail.next = "Start the demo cell first.";
    fireEvent.click(screen.getByRole("button", { name: "Start cell" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Start the demo cell first.");
    // The state did not change, so the button still offers to start it.
    expect(screen.getByRole("button", { name: "Start cell" })).toBeEnabled();
    fireEvent.click(within(alert).getByRole("button", { name: /close/i }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("disables the controls while a request is in flight (no double submit)", async () => {
    fakeBackend();
    const inner = backend.handler!;
    let release: () => void = () => {};
    backend.handler = (path, body) =>
      path === "/api/v1/cell/up"
        ? new Promise((resolve) => (release = () => resolve(inner(path, body))))
        : inner(path, body);
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    await goTo("Record");
    fireEvent.click(screen.getByRole("button", { name: "Start cell" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Starting cell…" })).toBeDisabled(),
    );
    release();
    await screen.findByText("Cell started.");
    expect(posts().filter(([p]) => p === "/api/v1/cell/up")).toHaveLength(1);
  });

  it("creates a project from the dialog and makes it active", async () => {
    fakeBackend();
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    await goTo("Projects");
    fireEvent.click(screen.getByRole("button", { name: "New project" }));
    const create = screen.getByRole("button", { name: "Create" });
    expect(create).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "   " } });
    expect(create).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "Welding" } });
    fireEvent.click(create);
    await screen.findByText("Project created.");
    expect(lastPost("/api/v1/projects")?.[1]).toEqual({ name: "Welding" });
    await waitFor(() => expect(localStorage.getItem("mrp-project")).toBe("p3"));
    await waitFor(() => expect(screen.queryByLabelText("Project name")).not.toBeInTheDocument());
  });

  it("keeps the dialog open and reports the error when project creation fails", async () => {
    const { fail } = fakeBackend();
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    await goTo("Projects");
    fireEvent.click(screen.getByRole("button", { name: "New project" }));
    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "x" } });
    fail.next = "Project name already exists.";
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(await screen.findByText("Project name already exists.")).toBeInTheDocument();
    expect(screen.getByLabelText("Project name")).toBeInTheDocument();
  });

  it("lists only this project's validated, accepted recordings and exports the selection", async () => {
    const episode = (id: string, extra: Partial<Episode> = {}): Episode => ({
      id,
      project_id: "p1",
      status: "accepted",
      manifest: {},
      validation: { valid: true },
      ...extra,
    });
    fakeBackend({}, [
      episode("good-1"),
      episode("good-2"),
      episode("rejected", { status: "rejected" }),
      episode("unvalidated", { validation: undefined }),
      episode("other-project", { project_id: "p2" }),
    ]);
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    await goTo("Dataset");
    const boxes = screen.getAllByRole("checkbox", { name: /Select episode/ });
    expect(boxes.map((box) => box.getAttribute("aria-label"))).toEqual([
      "Select episode good-1",
      "Select episode good-2",
    ]);
    const exportButton = screen.getByRole("button", { name: /Export selected/ });
    expect(exportButton).toBeDisabled();
    fireEvent.click(boxes[1]);
    expect(exportButton).toBeEnabled();
    fireEvent.click(exportButton);
    await screen.findByText("Dataset export queued.");
    const body = lastPost("/api/v1/exports")?.[1] as Record<string, unknown>;
    expect(body.episode_ids).toEqual(["good-2"]);
    expect(body.project_id).toBe("p1");
    expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("clears the export selection when the project changes", async () => {
    fakeBackend({}, [
      { id: "e", project_id: "p1", status: "accepted", manifest: {}, validation: {} },
    ]);
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    await goTo("Dataset");
    fireEvent.click(screen.getByRole("checkbox", { name: /Select episode/ }));
    expect(screen.getByRole("checkbox", { name: /Select episode/ })).toBeChecked();
    await goTo("Projects");
    fireEvent.click(screen.getByRole("button", { name: /^Second/ }));
    await goTo("Dataset");
    fireEvent.mouseDown(screen.getAllByRole("combobox", { name: "Active project" })[0]);
    fireEvent.click(await screen.findByRole("option", { name: "First" }));
    expect(await screen.findByRole("checkbox", { name: /Select episode/ })).not.toBeChecked();
  });

  it("saves settings through the shared busy/notice flow", async () => {
    fakeBackend();
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    await goTo("Settings");
    fireEvent.change(screen.getByLabelText("Default namespace"), { target: { value: "lab" } });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(await screen.findByText("Settings saved.")).toBeInTheDocument();
    expect(lastPost("/api/v1/settings")?.[1]).toEqual({ hf_token: undefined, hf_namespace: "lab" });
  });

  it("warns, keeps the last data and recovers when the connection drops mid-session", async () => {
    fakeBackend();
    render(<App />);
    await screen.findByText("Welcome to MRP Studio");
    const working = backend.handler!;
    backend.handler = () => {
      throw new Error("Network Error");
    };
    expect(
      await screen.findByText(/Connection lost/, undefined, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(screen.getByText("Welcome to MRP Studio")).toBeInTheDocument();
    backend.handler = working;
    await waitFor(() => expect(screen.queryByText(/Connection lost/)).not.toBeInTheDocument(), {
      timeout: 5000,
    });
  }, 15000);

  describe("routing", () => {
    it("opens the page named in the URL and updates the URL on navigation", async () => {
      fakeBackend();
      window.history.replaceState(null, "", "/settings");
      render(<App />);
      expect(await screen.findByLabelText("Default namespace")).toBeInTheDocument();
      await goTo("Episodes");
      expect(window.location.pathname).toBe("/episodes");
    });
    it("sends unknown URLs to the overview", async () => {
      fakeBackend();
      window.history.replaceState(null, "", "/no-such-page");
      render(<App />);
      expect(await screen.findByText("Welcome to MRP Studio")).toBeInTheDocument();
      expect(window.location.pathname).toBe("/");
    });
    it("asks before leaving unsaved cell changes, and stays or leaves as chosen", async () => {
      fakeBackend();
      render(<App />);
      await screen.findByText("Welcome to MRP Studio");
      await goTo("Components");
      fireEvent.click(await screen.findByRole("switch", { name: /moves on its own/ }));
      fireEvent.click(nav("Train"));
      const dialog = await screen.findByRole("dialog", { name: "Leave without saving?" });
      fireEvent.click(within(dialog).getByRole("button", { name: "Stay" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
      expect(window.location.pathname).toBe("/components");
      expect(screen.getByText(/Unsaved changes/)).toBeInTheDocument();
      fireEvent.click(nav("Train"));
      fireEvent.click(await screen.findByRole("button", { name: "Leave without saving" }));
      await screen.findByRole("heading", { level: 1, name: "Train" });
      expect(window.location.pathname).toBe("/train");
    });
  });
});
