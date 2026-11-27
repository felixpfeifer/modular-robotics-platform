import { fireEvent, render, screen, waitFor } from "./testUtils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defaultSettings } from "../../src/lib/cellSpec";
import { CellSetupPage } from "../../src/pages/CellSetupPage";

const api = vi.hoisted(() => vi.fn());
vi.mock("../../src/api/client", async (importOriginal) =>
  (await import("./apiMock")).fakeClient(await importOriginal(), api),
);

const project = { id: "p1", name: "P" };
const run = vi.fn(async (work: () => Promise<unknown>) => {
  await work();
});

describe("component selection page", () => {
  beforeEach(() => {
    api.mockReset();
    api.mockResolvedValue({}); // the page also asks for the network info on load
    run.mockClear();
  });
  it("blocks a real follower while the leader is mock", () => {
    render(<CellSetupPage project={project} busy={false} run={run} />);
    const follower = screen.getByRole("group", { name: "Follower arm" });
    expect(follower.querySelector("button[value=real]")).toBeDisabled();
    expect(screen.getByText("mock-so101")).toBeInTheDocument();
  });
  it("shows USB device pickers once a component is real and scans on request", async () => {
    api.mockResolvedValue({
      serial: [
        { port: "/dev/ttyACM0", serial: "A1", vendor_id: "1a86", product: "", likely_so101: true },
      ],
      video: [],
      calibrations: [],
      hints: ["No external USB camera found."],
      wsl: true,
    });
    render(<CellSetupPage project={project} busy={false} run={run} />);
    expect(screen.queryByText("USB devices")).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("group", { name: "Leader arm" }).querySelector("button[value=real]")!,
    );
    expect(screen.getByText("USB devices")).toBeInTheDocument();
    expect(screen.getByText("hwleader-so101")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Scan devices" }));
    await waitFor(() =>
      expect(screen.getByText("No external USB camera found.")).toBeInTheDocument(),
    );
    expect(api).toHaveBeenCalledWith("/api/v1/devices/scan");
  });
  it("loads saved calibration files without requiring a manual scan", async () => {
    api.mockImplementation(async (path: string) =>
      path === "/api/v1/devices/scan"
        ? { serial: [], video: [], calibrations: ["leader.yaml"], hints: [], wsl: false }
        : {},
    );
    render(<CellSetupPage project={project} busy={false} run={run} />);
    fireEvent.click(
      screen.getByRole("group", { name: "Leader arm" }).querySelector("button[value=real]")!,
    );
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/devices/scan"));
    fireEvent.mouseDown(screen.getByLabelText("Calibration file"));
    expect(await screen.findByRole("option", { name: "leader.yaml" })).toBeInTheDocument();
  });
  it("saves a mock cell with moving joints and the chosen settings", async () => {
    api.mockResolvedValue({});
    render(<CellSetupPage project={project} busy={false} run={run} />);
    fireEvent.click(screen.getByRole("switch", { name: /moves on its own/ }));
    fireEvent.change(screen.getByLabelText("FPS"), { target: { value: "25" } });
    fireEvent.click(screen.getByRole("button", { name: "Save cell" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/api/v1/projects/p1/cell", {
        cell: {
          leader: "mock",
          follower: "mock",
          leader_model: "so101",
          follower_model: "so101",
          camera: "synthetic",
          task_id: "pipeline_check",
          mock_motion: true,
          settings: { ...defaultSettings, camera: { width: 640, height: 480, fps: 25 } },
        },
      }),
    );
  });
  it("warns about unsaved changes and clears the warning after saving", async () => {
    const onDirtyChange = vi.fn();
    render(
      <CellSetupPage project={project} busy={false} run={run} onDirtyChange={onDirtyChange} />,
    );
    fireEvent.click(screen.getByRole("switch", { name: /moves on its own/ }));
    expect(screen.getByText(/Unsaved changes/)).toBeInTheDocument();
    expect(onDirtyChange).toHaveBeenLastCalledWith(true);
    fireEvent.click(screen.getByRole("button", { name: "Save cell" }));
    await waitFor(() => expect(screen.queryByText(/Unsaved changes/)).not.toBeInTheDocument());
    expect(onDirtyChange).toHaveBeenLastCalledWith(false);
  });
  it("blocks saving while a setting is out of range", () => {
    render(<CellSetupPage project={project} busy={false} run={run} />);
    fireEvent.change(screen.getByLabelText("FPS"), { target: { value: "500" } });
    expect(screen.getByRole("button", { name: "Save cell" })).toBeDisabled();
    expect(screen.getByText(/Fix: camera fps/)).toBeInTheDocument();
  });
  it("saves Docker Hub image selections", async () => {
    render(<CellSetupPage project={project} busy={false} run={run} />);
    fireEvent.change(screen.getByLabelText("Main camera"), {
      target: { value: "acme/camera:v1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save cell" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/api/v1/projects/p1/cell",
        expect.objectContaining({
          cell: expect.objectContaining({ images: { camera: "acme/camera:v1" } }),
        }),
      ),
    );
  });
  it("adds a second camera with its own settings and needs a device for a USB one", () => {
    render(<CellSetupPage project={project} busy={false} run={run} />);
    fireEvent.click(screen.getByRole("switch", { name: /Second camera/ }));
    expect(screen.getAllByLabelText("FPS")).toHaveLength(2);
    fireEvent.mouseDown(screen.getByLabelText("Source"));
    fireEvent.click(screen.getByRole("option", { name: "USB" }));
    expect(screen.getByText("USB devices")).toBeInTheDocument();
  });
  it("offers to use the frame rate the camera actually delivers", async () => {
    api.mockImplementation(async (path: string) =>
      path.endsWith("/cell/test")
        ? {
            passed: false,
            fingerprint: "f",
            checks: [
              {
                name: "Camera frame rate",
                ok: false,
                level: "error",
                detail: "25 fps (need 30)",
                role: "camera",
                measured_fps: 25,
                target_fps: 30,
              },
            ],
          }
        : {},
    );
    const usb = {
      ...project,
      cell_spec: {
        leader: "mock",
        follower: "mock",
        camera: "opencv_usb",
        devices: { camera: { device: "/dev/video2" } },
      },
    };
    render(<CellSetupPage project={usb} busy={false} run={run} />);
    fireEvent.click(screen.getByRole("button", { name: "Run connection test" }));
    fireEvent.click(await screen.findByRole("button", { name: "Use 25 fps" }));
    expect(screen.getByDisplayValue("25")).toBeInTheDocument();
  });
});
