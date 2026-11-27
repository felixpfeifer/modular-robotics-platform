import { fireEvent, render, screen, waitFor, within } from "./testUtils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { cameraIdFrom, parseVariants } from "../../src/components/CustomCameraDialog";
import { ModuleInspector } from "../../src/components/ModuleInspector";
import type { CellLayout, LayoutCatalog, LayoutModule } from "../../src/types";

const api = vi.hoisted(() => vi.fn());
vi.mock("../../src/api/client", async (importOriginal) =>
  (await import("./apiMock")).fakeClient(await importOriginal(), api),
);

const camera: LayoutModule = {
  id: "cam", type: "camera", name: "Top camera", x: 0.6, y: 0.4, z: 0.5, yaw_deg: -90, width: 0.07,
  depth: 0.07, height: 0.07, parent: "", enabled: true, notes: "", namespace: "",
  properties: { model: "opencv_usb" }, topics: [],
}; // prettier-ignore
const layout: CellLayout = {
  schema_version: "mrp-cell-layout/v1",
  workspace: { name: "Bench", width_m: 1.2, depth_m: 0.8, frame_id: "world" },
  modules: [camera],
};
const catalog = {
  max_modules: 64,
  templates: {},
  module_types: {
    camera: {
      label: "Camera", color: "#3a6ea5", size: [0.07, 0.07], height: 0.07, defaults: {},
      properties: { model: { kind: "enum", options: [] }, variant: { kind: "text", max_length: 40 } },
      models: {
        opencv_usb: { label: "USB webcam", status: "available", variants: {}, origin: "builtin", installed: true },
        ids_ueye: { label: "IDS uEye", status: "available", variants: {}, origin: "builtin", installed: false },
        genicam: { label: "GenICam", status: "available", variants: {}, origin: "discovered", installed: true },
        acme_x1: { label: "Acme X1", status: "available", variants: { mono: "Mono" }, origin: "custom", installed: false },
        other: { label: "Other (not deployable)", status: "planned", variants: {} },
      },
    },
  },
} as unknown as LayoutCatalog; // prettier-ignore

function renderInspector(model = "opencv_usb") {
  const onChange = vi.fn();
  const onCatalogChange = vi.fn();
  render(
    <ModuleInspector
      module={{ ...camera, properties: { model } }}
      layout={layout}
      catalog={catalog}
      onChange={onChange}
      onPlaceOn={vi.fn()}
      onDuplicate={vi.fn()}
      onDelete={vi.fn()}
      onCatalogChange={onCatalogChange}
    />,
  );
  return { onChange, onCatalogChange };
}

function openTypes() {
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "type" }));
  return within(screen.getByRole("listbox"));
}

describe("camera type dropdown", () => {
  beforeEach(() => api.mockReset());

  it("groups types by origin and marks driver images that are not on the host", () => {
    renderInspector();
    const list = openTypes();
    expect(list.getByText("Built-in")).toBeInTheDocument();
    expect(list.getByText("Found on this host")).toBeInTheDocument();
    expect(list.getByText("Custom")).toBeInTheDocument();
    expect(list.getByRole("option", { name: "IDS uEye · not on this host" })).toBeInTheDocument();
    expect(list.getByRole("option", { name: "GenICam" })).toBeInTheDocument();
    expect(list.getByRole("option", { name: "+ Add custom camera…" })).toBeInTheDocument();
  });

  it("adds a custom camera, reloads the catalogue and selects it", async () => {
    api.mockResolvedValue({ id: "acme_y2", pull: { ok: true, detail: "pulled" }, cameras: {} });
    const { onChange, onCatalogChange } = renderInspector();
    fireEvent.click(openTypes().getByRole("option", { name: "+ Add custom camera…" }));
    const dialog = within(screen.getByRole("dialog"));
    const add = dialog.getByRole("button", { name: "Add camera" });
    fireEvent.change(dialog.getByLabelText(/^Name/), { target: { value: "Acme Y2" } });
    fireEvent.change(dialog.getByLabelText(/^Docker image/), { target: { value: "acme/y2:1" } });
    fireEvent.change(dialog.getByLabelText(/^Driver node command/), {
      target: { value: "ros2 run camera_acme camera_node" },
    });
    fireEvent.change(dialog.getByLabelText("Variants"), { target: { value: "mono=Mono, color" } });
    expect(add).toBeDisabled(); // trust is not implied
    fireEvent.click(dialog.getByLabelText("I trust this image"));
    fireEvent.click(add);
    await waitFor(() => expect(onCatalogChange).toHaveBeenCalled());
    expect(api).toHaveBeenCalledWith("/api/v1/cameras", {
      id: "acme_y2",
      label: "Acme Y2",
      image: "acme/y2:1",
      access: "usb_bus",
      fps_type: "int",
      probe_command: ["ros2", "run", "camera_acme", "camera_node"],
      variants: { mono: "Mono", color: "color" },
      trusted: true,
      pull: true, // an agent reports images, so it can pull
    });
    expect(onChange).toHaveBeenCalledWith({ properties: { model: "acme_y2" } });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("offers pull and remove for a custom type whose image is missing", async () => {
    api.mockResolvedValue({ ok: true, detail: "Status: Downloaded newer image" });
    const { onCatalogChange } = renderInspector("acme_x1");
    fireEvent.click(screen.getByRole("button", { name: "Pull image" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/cameras/acme_x1/pull", {}));
    expect(await screen.findByText("Status: Downloaded newer image")).toBeInTheDocument();
    expect(onCatalogChange).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Remove custom camera" })).toBeInTheDocument();
  });

  it("built-in types get no pull or remove buttons", () => {
    renderInspector("ids_ueye");
    expect(screen.queryByRole("button", { name: "Pull image" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove custom camera" })).not.toBeInTheDocument();
  });
});

describe("custom camera form helpers", () => {
  it("derives a valid id from the name", () => {
    expect(cameraIdFrom("Acme X1 (USB)")).toBe("acme_x1_usb");
    expect(cameraIdFrom("3D Cam")).toBe("cam_3d_cam");
    expect(cameraIdFrom("x".repeat(40))).toHaveLength(32);
  });

  it("parses variants", () => {
    expect(parseVariants("d435=D435, d455")).toEqual({ d435: "D435", d455: "d455" });
    expect(parseVariants(" ")).toEqual({});
  });
});
