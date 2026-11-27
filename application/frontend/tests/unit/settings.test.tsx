import { fireEvent, render, screen } from "./testUtils";
import { describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => vi.fn().mockResolvedValue({}));
vi.mock("../../src/api/client", async (importOriginal) =>
  (await import("./apiMock")).fakeClient(await importOriginal(), api),
);

import { SettingsPage } from "../../src/pages/SettingsPage";

const settings = { hf_token_set: false, hf_namespace: "acme" };

describe("SettingsPage", () => {
  it("sends the token and namespace, and masks the token field", async () => {
    const run = vi.fn(async (work: () => Promise<unknown>) => {
      await work();
    });
    render(<SettingsPage settings={settings} run={run} />);
    const token = screen.getByLabelText("Access token");
    expect(token).toHaveAttribute("type", "password");
    fireEvent.change(token, { target: { value: "hf_secret" } });
    fireEvent.change(screen.getByLabelText("Default namespace"), { target: { value: "lab" } });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(run).toHaveBeenCalledWith(expect.any(Function), "Settings saved.");
    expect(api).toHaveBeenLastCalledWith("/api/v1/settings", {
      hf_token: "hf_secret",
      hf_namespace: "lab",
    });
  });
  it("omits the token when left blank so a saved one is kept", () => {
    const run = vi.fn(async (work: () => Promise<unknown>) => {
      await work();
    });
    render(<SettingsPage settings={{ ...settings, hf_token_set: true }} run={run} />);
    expect(screen.getByPlaceholderText(/A token is saved/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(api).toHaveBeenLastCalledWith("/api/v1/settings", {
      hf_token: undefined,
      hf_namespace: "acme",
    });
  });
  it("removes the saved token explicitly", () => {
    const run = vi.fn(async (work: () => Promise<unknown>) => {
      await work();
    });
    render(<SettingsPage settings={{ ...settings, hf_token_set: true }} run={run} />);
    fireEvent.click(screen.getByRole("button", { name: "Remove token" }));
    expect(run).toHaveBeenCalledWith(expect.any(Function), "Saved token removed.");
    expect(api).toHaveBeenLastCalledWith("/api/v1/settings", { clear_hf_token: true });
  });
  it("follows the namespace saved on the server", () => {
    const run = vi.fn();
    const { rerender } = render(<SettingsPage settings={settings} run={run} />);
    rerender(<SettingsPage settings={{ ...settings, hf_namespace: "other" }} run={run} />);
    expect(screen.getByLabelText("Default namespace")).toHaveValue("other");
  });
});
