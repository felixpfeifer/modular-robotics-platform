import { fireEvent, render, screen, waitFor } from "./testUtils";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => vi.fn());
vi.mock("../../src/api/client", async (importOriginal) =>
  (await import("./apiMock")).fakeClient(await importOriginal(), api),
);

import { ApiError } from "../../src/api/client";
import { ConfigBackupCard } from "../../src/components/ConfigBackupCard";

const report = {
  valid: true,
  applied: false,
  errors: [],
  warnings: ["'Real' names USB ports: scan the devices again in Cell setup before starting it."],
  bundle: { created: "2026-11-22T10:00:00Z", app_version: "0.1.0" },
  items: {
    calibrations: [{ name: "leader.yaml", status: "conflict" }],
    robots: [{ id: "so101", label: "SO-101", status: "known" }],
    projects: [{ name: "Real", original_name: "Real", preset: "real-so101" }],
  },
};
const run = vi.fn(async (work: () => Promise<unknown>) => {
  await work();
});
const file = () => new File(["x"], "setup.tar.gz", { type: "application/gzip" });

afterEach(() => {
  vi.restoreAllMocks();
  api.mockReset();
});

describe("ConfigBackupCard", () => {
  it("lists backups and creates a new one", async () => {
    api.mockImplementation(async (path: string) =>
      path === "/api/v1/config/backups"
        ? { backups: [{ name: "mrp-config-20261122-100000.tar.gz", bytes: 2048, created: 1 }] }
        : {},
    );
    render(<ConfigBackupCard run={run} />);
    expect(await screen.findByText("mrp-config-20261122-100000.tar.gz")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute(
      "href",
      "/api/v1/config/backups/mrp-config-20261122-100000.tar.gz",
    );
    fireEvent.click(screen.getByRole("button", { name: "Create backup" }));
    expect(run).toHaveBeenCalledWith(expect.any(Function), "Backup saved.");
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/config/export", {}));
  });

  it("validates first, shows conflicts, and only imports after confirmation", async () => {
    const uploads = () => api.mock.calls.filter(([, body]) => body instanceof File);
    api.mockImplementation(async (path: string) =>
      path === "/api/v1/config/validate"
        ? report
        : path.startsWith("/api/v1/config/import")
          ? {
              ...report,
              applied: true,
              result: {
                calibrations_stored: ["leader.yaml"],
                calibrations_kept: [],
                projects_created: [{ id: "1", name: "Real" }],
              },
            }
          : { backups: [] },
    );
    render(<ConfigBackupCard run={run} />);
    fireEvent.change(screen.getByTestId("bundle-input"), { target: { files: [file()] } });
    expect(await screen.findByText(/All checks passed/)).toBeInTheDocument();
    expect(uploads().map(([path]) => path)).toEqual(["/api/v1/config/validate"]);
    expect(screen.getByText(/names USB ports/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/Replace my existing leader.yaml/));
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(await screen.findByText(/Imported 1 project/)).toBeInTheDocument();
    expect(uploads()[1][0]).toBe("/api/v1/config/import?overwrite_calibrations=true");
  });

  it("blocks import and shows why when validation fails", async () => {
    api.mockImplementation(async (path: string) =>
      path === "/api/v1/config/validate"
        ? {
            ...report,
            valid: false,
            errors: ["calibration/leader.yaml: Calibration needs all six joints"],
          }
        : { backups: [] },
    );
    render(<ConfigBackupCard run={run} />);
    fireEvent.change(screen.getByTestId("bundle-input"), { target: { files: [file()] } });
    expect(await screen.findByText(/did not pass validation/)).toBeInTheDocument();
    expect(screen.getByText(/needs all six joints/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Import" })).not.toBeInTheDocument();
  });

  it("shows the server's reason for a rejected file", async () => {
    api.mockImplementation(async (path: string) => {
      if (path === "/api/v1/config/validate")
        throw new ApiError("This is not a readable .tar.gz bundle.", 400);
      return { backups: [] };
    });
    render(<ConfigBackupCard run={run} />);
    fireEvent.change(screen.getByTestId("bundle-input"), { target: { files: [file()] } });
    expect(await screen.findByText(/not a readable/)).toBeInTheDocument();
  });
});
