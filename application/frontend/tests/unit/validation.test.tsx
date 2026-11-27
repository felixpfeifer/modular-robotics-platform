import { render, screen } from "./testUtils";
import { describe, expect, it } from "vitest";
import { ValidationVerdict } from "../../src/components/ValidationVerdict";
import { explain, parseVerdict } from "../../src/lib/validation";
import { RecordPage } from "../../src/pages/RecordPage";

// The two real failures from a rejected mock episode (the validator's own wording).
const validation = {
  findings: [
    {
      rule_id: "metadata.manifest",
      severity: "info",
      summary: "immutable acquisition manifest is present",
    },
    {
      rule_id: "camera.max_gap",
      severity: "error",
      summary: "webcam maximum camera gap is 122.925 ms",
    },
    {
      rule_id: "camera.side.max_gap",
      severity: "error",
      summary: "side maximum camera gap is 119.173 ms",
    },
    {
      rule_id: "sync.action_causal_coverage",
      severity: "error",
      summary: "every image is covered by a non-future, non-expired JointIntent",
    },
    { rule_id: "camera.blur_baseline", severity: "warning", summary: "advisory" },
  ],
};

describe("validation explanations", () => {
  it("separates failing checks from passes and advisory warnings", () => {
    const verdict = parseVerdict(validation);
    expect(verdict.errors.map((f) => f.rule_id)).toEqual([
      "camera.max_gap",
      "camera.side.max_gap",
      "sync.action_causal_coverage",
    ]);
    expect(verdict.warnings).toHaveLength(1);
    expect(parseVerdict(undefined)).toEqual({ errors: [], warnings: [], checked: false });
    expect(parseVerdict({ findings: "nope" }).checked).toBe(false);
  });
  it("names the camera and gives a fix for every rule id, known or not", () => {
    expect(explain("camera.max_gap").title).toBe("Main camera: frames arrived too late");
    expect(explain("camera.side.max_gap").title).toBe("Side camera: frames arrived too late");
    expect(explain("camera.side.fps").fix).toMatch(/connection test/);
    for (const rule of [
      "storage.sha256",
      "metadata.complete",
      "time.webcam.monotonic",
      "totally.new_rule",
    ]) {
      const hint = explain(rule, "raw text");
      expect(hint.title).toBeTruthy();
      expect(hint.fix).toBeTruthy();
    }
    expect(explain("totally.new_rule", "raw text").title).toBe("raw text");
  });
  it("tells the operator what failed and what to do instead of listing passing checks", () => {
    render(<ValidationVerdict status="rejected" validation={validation} />);
    expect(screen.getByText("Rejected: 3 checks failed")).toBeInTheDocument();
    expect(screen.getByText("Main camera: frames arrived too late")).toBeInTheDocument();
    expect(screen.getByText("webcam maximum camera gap is 122.925 ms")).toBeInTheDocument(); // the measurement
    expect(screen.getByText("Some camera frames had no valid robot command")).toBeInTheDocument();
    // The validator's wording for this rule is its passing sentence; it must not be shown as the reason.
    expect(screen.queryByText(/every image is covered/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/What to do:/)).toHaveLength(3);
    expect(screen.queryByText(/manifest is present/)).not.toBeInTheDocument();
  });
  it("handles accepted, missing and empty results", () => {
    const { rerender } = render(<ValidationVerdict status="accepted" validation={validation} />);
    expect(screen.getByText(/Accepted: all checks passed/)).toBeInTheDocument();
    rerender(<ValidationVerdict status="rejected" validation={undefined} />);
    expect(screen.getByText(/not available yet/)).toBeInTheDocument();
    rerender(<ValidationVerdict status="rejected" validation={{ findings: [] }} />);
    expect(screen.getByText(/no failing check was recorded/)).toBeInTheDocument();
  });
  it("shows when commands went missing without assuming a performance problem", () => {
    const summary =
      "3 of 90 camera frames had no valid robot command. First gap at 2.400 s from the first frame (the latest command had expired).";
    render(
      <ValidationVerdict
        status="rejected"
        validation={{
          findings: [{ rule_id: "sync.action_causal_coverage", severity: "error", summary }],
        }}
      />,
    );
    expect(screen.getByText(summary)).toBeInTheDocument();
    expect(screen.queryByText(/computer is lagging/)).not.toBeInTheDocument();
  });
});

describe("record page shows why the last episode was rejected", () => {
  const base = {
    busy: false,
    projectId: "p",
    start: () => {},
    mark: () => {},
    cell: () => {},
    teleop: () => {},
    runtime: { cell_running: true, active_source: "teleop", checks: [], message: "" },
  };
  const session = (state: string, detail = "") => ({
    id: "e1",
    project_id: "p",
    state,
    detail,
    started: 1,
    snapshot: {},
  });
  it("explains a validated rejection directly under the capture controls", () => {
    render(
      <RecordPage
        {...base}
        sessions={[session("recorded", "operator marked success")]}
        episodes={[{ id: "e1", status: "rejected", manifest: {}, validation }]}
      />,
    );
    expect(screen.getByText("Last episode")).toBeInTheDocument();
    expect(screen.getByText("Main camera: frames arrived too late")).toBeInTheDocument();
  });
  it("shows the recorder's refusal reason for an episode that never started", () => {
    render(
      <RecordPage
        {...base}
        sessions={[
          session(
            "failed",
            "Recorder rejected the episode. Check stream readiness and free storage.",
          ),
        ]}
      />,
    );
    expect(screen.getByText(/Not recorded \(failed\)/)).toBeInTheDocument();
    expect(screen.getByText(/free disk space/)).toBeInTheDocument();
  });
  it("says it is waiting while validation has not finished", () => {
    render(<RecordPage {...base} sessions={[session("recorded")]} episodes={[]} />);
    expect(screen.getByText(/Waiting for the validation result/)).toBeInTheDocument();
  });
});
