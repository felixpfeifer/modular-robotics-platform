import { act, fireEvent, render, screen, within } from "./testUtils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RobotTelemetry } from "../../src/components/RobotTelemetry";
import { DeployPage } from "../../src/pages/DeployPage";
import { DatasetPage } from "../../src/pages/DatasetPage";
import { OverviewPage } from "../../src/pages/OverviewPage";
import { RecordPage } from "../../src/pages/RecordPage";
import { ProjectsPage } from "../../src/pages/ProjectsPage";
import type { Runtime, Status } from "../../src/types";

vi.mock("../../src/components/HubBrowser", () => ({ HubBrowser: () => null }));
vi.mock("../../src/components/TargetPicker", () => ({ TargetPicker: () => null }));

const runtime: Runtime = {
  cell_running: false,
  active_source: "none",
  checks: [{ name: "Camera", ready: false, detail: "offline" }],
  message: "Start the cell",
};
describe("live robot telemetry", () => {
  const live: Runtime = {
    ...runtime,
    cell_running: true,
    active_source: "policy",
    robot_data: {
      Follower: {
        stamp_ns: 100,
        joint_names: ["shoulder", "gripper"],
        positions: [0.5, 0.2],
        velocities: [],
        fresh: true,
      },
      Action: {
        stamp_ns: 101,
        joint_names: ["gripper", "shoulder"],
        positions: [0.3, 0.8],
        velocities: [0.1, 0.4],
        fresh: true,
        source: "policy_act",
      },
    },
  };
  beforeEach(() => {
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });
  it("aligns measured and command values by joint name, not array index", () => {
    render(<RobotTelemetry runtime={live} />);
    const row = screen.getByRole("row", { name: /shoulder 0.500 0.800 Unavailable 0.300/ });
    expect(within(row).getByText("0.300")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /all joints position history/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Actual robot position" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Requested position" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Leader arm position" })).toBeInTheDocument();
    expect(screen.getByText("Command source: policy_act")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Velocity" }));
    expect(screen.getByRole("columnheader", { name: "Actual robot velocity" })).toBeInTheDocument();
    expect(
      screen.getByRole("row", { name: /shoulder Unavailable 0.400 Unavailable Unavailable/ }),
    ).toBeInTheDocument();
  });
  it("expires displayed values when status updates stop", () => {
    vi.useFakeTimers();
    render(<RobotTelemetry runtime={live} />);
    expect(screen.getByText("Measured: Live")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(6000));
    expect(screen.getByText("Measured: Unavailable / stale")).toBeInTheDocument();
    expect(
      screen.getByRole("row", { name: /shoulder Unavailable Unavailable Unavailable Unavailable/ }),
    ).toBeInTheDocument();
  });
  it("does not present stale or non-finite measurements as live values", () => {
    render(
      <RobotTelemetry
        runtime={{
          ...live,
          robot_data: {
            ...live.robot_data,
            Follower: { ...live.robot_data!.Follower!, fresh: false },
            Action: { ...live.robot_data!.Action!, positions: [0.3, Number.NaN] },
          },
        }}
      />,
    );
    expect(
      screen.getByRole("row", { name: /shoulder Unavailable Unavailable Unavailable Unavailable/ }),
    ).toBeInTheDocument();
  });
  it("shows an explicit empty state without inventing robot data", () => {
    const { rerender } = render(<RobotTelemetry runtime={runtime} />);
    expect(screen.getByText("Joint readings offline.")).toBeInTheDocument();
    rerender(<RobotTelemetry runtime={{ ...runtime, cell_running: true }} />);
    expect(screen.getByText("Waiting for joint readings.")).toBeInTheDocument();
  });
  it("labels demo values as simulated, never live measurements", () => {
    const { rerender } = render(
      <RobotTelemetry runtime={{ ...live, robot_data_simulated: true }} />,
    );
    expect(screen.getByText("Simulated joint motion")).toBeInTheDocument();
    expect(screen.getByText("Follower: Simulated")).toBeInTheDocument();
    expect(screen.getByText("Command: Simulated")).toBeInTheDocument();
    expect(screen.queryByText("Measured: Live")).not.toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Difference Requested − actual" }),
    ).toBeInTheDocument();
    rerender(
      <RobotTelemetry
        runtime={{
          ...live,
          active_source: "none",
          robot_data_simulated: true,
          robot_data: { Follower: live.robot_data!.Follower },
        }}
      />,
    );
    expect(screen.getByText("Command: Inactive")).toBeInTheDocument();
  });
  it("shows robot telemetry in the inference view", () => {
    const status: Status = {
      mode: "ros",
      agent_configured: true,
      runtime: live,
      projects: [],
      sessions: [],
      settings: { hf_token_set: false, hf_namespace: "" },
      export_enabled: false,
    };
    render(
      <DeployPage
        project={{ id: "one", name: "Test" }}
        status={status}
        busy={false}
        run={vi.fn()}
      />,
    );
    expect(screen.getByRole("region", { name: "Joint motion" })).toBeInTheDocument();
    expect(screen.getByText("Command: Live")).toBeInTheDocument();
  });
});
describe("workspace pages", () => {
  it("guides a new user to projects", () => {
    const go = vi.fn();
    render(<OverviewPage sessions={[]} go={go} />);
    expect(screen.getByText("No sessions yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Go to projects" }));
    expect(go).toHaveBeenCalledWith("projects");
  });
  it("selects a project with a button", () => {
    const select = vi.fn();
    render(
      <ProjectsPage
        projects={[{ id: "one", name: "Pick and place" }]}
        projectId=""
        selectProject={select}
        createProject={vi.fn()}
        renameProject={vi.fn()}
        deleteProject={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Pick and place/ }));
    expect(select).toHaveBeenCalledWith("one");
  });
  it("guards recording actions and exposes the offline camera state", () => {
    const mark = vi.fn();
    const props = {
      runtime,
      busy: false,
      projectId: "",
      start: vi.fn(),
      mark,
      cell: vi.fn(),
      teleop: vi.fn(),
    };
    const { rerender } = render(<RecordPage {...props} />);
    expect(screen.getByText("Camera is offline")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start episode/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Enable teleop" })).toBeDisabled();
    rerender(
      <RecordPage
        {...props}
        projectId="one"
        runtime={{ ...runtime, cell_running: true, active_episode_id: "episode" }}
      />,
    );
    expect(screen.getByRole("button", { name: /Start episode/ })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Success" }));
    expect(mark).toHaveBeenCalledWith("success");
  });
  it("shows camera availability and recovers when frames return", () => {
    render(
      <RecordPage
        runtime={{ ...runtime, cell_running: true }}
        busy={false}
        projectId="one"
        start={vi.fn()}
        mark={vi.fn()}
        cell={vi.fn()}
        teleop={vi.fn()}
      />,
    );
    const image = screen.getByAltText("Robot camera preview");
    expect(screen.getByText(/Camera preview unavailable/)).toBeInTheDocument();
    fireEvent.load(image);
    expect(screen.queryByText(/Camera preview unavailable/)).not.toBeInTheDocument();
    fireEvent.error(image);
    expect(screen.getByText(/Camera preview unavailable/)).toBeInTheDocument();
    fireEvent.load(image);
    expect(screen.queryByText(/Camera preview unavailable/)).not.toBeInTheDocument();
  });
  it("requires selected recordings and an available export service", () => {
    const exportData = vi.fn();
    const episode = {
      id: "episode-123",
      project_id: "one",
      status: "accepted",
      manifest: { task_id: "pick_up" },
      validation: {},
    };
    const toggle = vi.fn();
    const { rerender } = render(
      <DatasetPage
        episodes={[episode]}
        selected={new Set()}
        toggle={toggle}
        exportData={exportData}
        enabled
        busy={false}
      />,
    );
    expect(screen.getByRole("button", { name: /Export selected/ })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Select episode/ }));
    expect(toggle).toHaveBeenCalledWith(episode.id);
    rerender(
      <DatasetPage
        episodes={[episode]}
        selected={new Set([episode.id])}
        toggle={toggle}
        exportData={exportData}
        enabled={false}
        busy={false}
      />,
    );
    expect(screen.getByRole("button", { name: /Export selected/ })).toBeDisabled();
    expect(screen.getByText(/Export is currently unavailable/)).toBeInTheDocument();
    rerender(
      <DatasetPage
        episodes={[episode]}
        selected={new Set([episode.id])}
        toggle={toggle}
        exportData={exportData}
        enabled
        busy={false}
      />,
    );
    fireEvent.change(screen.getByLabelText("Frame stride"), { target: { value: "0" } });
    expect(screen.getByRole("button", { name: /Export selected/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Frame stride"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: /Export selected/ }));
    expect(exportData).toHaveBeenCalledWith(2);
  });
});

describe("real hardware safety", () => {
  const props = {
    runtime: { ...runtime },
    busy: false,
    projectId: "p",
    start: vi.fn(),
    mark: vi.fn(),
    teleop: vi.fn(),
  };
  it("asks the operator to confirm before starting a real cell", () => {
    const cell = vi.fn();
    render(<RecordPage {...props} cell={cell} realHardware />);
    fireEvent.click(screen.getByRole("button", { name: "Start cell" }));
    expect(cell).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Start with real hardware" }));
    expect(cell).toHaveBeenCalledWith(true);
  });
  it("requires a project to start a cell but allows stopping one", () => {
    const cell = vi.fn();
    const { rerender } = render(<RecordPage {...props} projectId="" cell={cell} />);
    expect(screen.getByRole("button", { name: "Start cell" })).toBeDisabled();
    expect(
      screen.getByText("Create or select a project before starting the cell."),
    ).toBeInTheDocument();
    rerender(
      <RecordPage
        {...props}
        projectId=""
        cell={cell}
        runtime={{ ...runtime, cell_running: true }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Stop cell" }));
    expect(cell).toHaveBeenCalledTimes(1);
  });
  it("starts mock cells without a confirmation", () => {
    const cell = vi.fn();
    render(<RecordPage {...props} cell={cell} />);
    fireEvent.click(screen.getByRole("button", { name: "Start cell" }));
    expect(cell).toHaveBeenCalledTimes(1);
  });
});

describe("recording state follows the session, not only the recorder", () => {
  const base = {
    busy: false,
    projectId: "p",
    start: vi.fn(),
    mark: vi.fn(),
    cell: vi.fn(),
    teleop: vi.fn(),
    note: vi.fn(),
  };
  const live = { ...runtime, cell_running: true, active_episode_id: "s1", checks: [] };
  const session = (state: string) => ({
    id: "s1",
    project_id: "p",
    state,
    started: Date.now() / 1000 - 3,
    snapshot: {},
  });
  it("lets a recording session be marked and shows the timer", () => {
    render(<RecordPage {...base} runtime={live} sessions={[session("recording")]} />);
    expect(screen.getByText(/^Recording · /)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Success" })).toBeEnabled();
  });
  it("disables controls and shows progress during cell and episode operations", () => {
    const { rerender } = render(
      <RecordPage
        {...base}
        runtime={{ ...runtime, cell_running: false }}
        busy
        recordAction="starting-cell"
      />,
    );
    expect(screen.getByRole("button", { name: "Starting cell…" })).toBeDisabled();
    rerender(
      <RecordPage
        {...base}
        runtime={{ ...runtime, cell_running: true }}
        busy
        recordAction="stopping-cell"
      />,
    );
    expect(screen.getByRole("button", { name: "Stopping cell…" })).toBeDisabled();
    rerender(
      <RecordPage
        {...base}
        runtime={{ ...runtime, cell_running: true }}
        busy
        recordAction="starting-episode"
      />,
    );
    expect(screen.getByRole("button", { name: "Starting episode…" })).toBeDisabled();
    rerender(<RecordPage {...base} runtime={live} sessions={[session("starting")]} />);
    expect(screen.getByRole("button", { name: "Starting episode…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Stop cell" })).toBeDisabled();
  });
  it("stops the timer and disables marking once the episode is being finalized", () => {
    render(<RecordPage {...base} runtime={live} sessions={[session("finalizing")]} />);
    expect(screen.getByText("Saving recording…")).toBeInTheDocument();
    expect(screen.queryByText(/^Recording · /)).not.toBeInTheDocument();
    for (const name of ["Success", "Failure", "Cancel"])
      expect(screen.getByRole("button", { name })).toBeDisabled();
    expect(screen.getByLabelText("Quick note")).toBeDisabled();
  });
  it("shows validation as a separate stage after the recording is saved", () => {
    render(<RecordPage {...base} runtime={live} sessions={[session("recorded")]} />);
    expect(screen.getByText("Checking recording…")).toBeInTheDocument();
    expect(
      screen.getByText(/Recording saved\. Waiting for the validation result/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/^Recording · /)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Success" })).toBeDisabled();
  });
});
