import { fireEvent, render, screen } from "./testUtils";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { RobotTelemetry } from "../../src/components/RobotTelemetry";
import type { Runtime } from "../../src/types";

vi.mock("recharts", async (importOriginal) => ({
  ...(await importOriginal<typeof import("recharts")>()),
  ResponsiveContainer: ({ children }: { children: ReactNode }) => children,
  LineChart: ({ data, children }: { data: { values: number[] }[]; children: ReactNode }) => (
    <output aria-label="Plotted measurements">
      {JSON.stringify(data.map(({ values }) => values))}
      {children}
    </output>
  ),
  XAxis: ({ domain, allowDataOverflow }: { domain: number[]; allowDataOverflow: boolean }) => (
    <span aria-label="Time window" data-clipped={allowDataOverflow}>
      {domain.join(",")}
    </span>
  ),
}));

afterEach(() => vi.useRealTimers());

it("shows every joint and holds the zoomed window while new samples arrive", () => {
  function runtime(stamp: number, position: number): Runtime {
    return {
      cell_running: true,
      active_source: "teleop",
      checks: [],
      message: "Ready",
      robot_data: {
        Follower: {
          stamp_ns: stamp,
          joint_names: ["shoulder", "gripper"],
          positions: [position, 0.2],
          velocities: [],
          fresh: true,
        },
      },
    };
  }

  vi.useFakeTimers();
  vi.setSystemTime(20000);
  const { rerender } = render(<RobotTelemetry runtime={runtime(1, 0)} />);
  vi.setSystemTime(20050);
  rerender(<RobotTelemetry runtime={runtime(2, 0.8)} />);
  vi.setSystemTime(20100);
  rerender(<RobotTelemetry runtime={runtime(3, 0)} />);

  expect(screen.getByLabelText("Plotted measurements")).toHaveTextContent(
    "[[0,0.2],[0.8,0.2],[0,0.2]]",
  );
  expect(screen.getByLabelText("Time window")).toHaveTextContent("8100,20100");
  fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
  expect(screen.getByLabelText("Time window")).toHaveTextContent("14100,20100");
  expect(screen.getByLabelText("Time window")).toHaveAttribute("data-clipped", "true");

  vi.setSystemTime(21100);
  rerender(<RobotTelemetry runtime={runtime(4, 0.4)} />);
  expect(screen.getByLabelText("Time window")).toHaveTextContent("14100,20100");
  expect(screen.getByLabelText("Plotted measurements")).toHaveTextContent(
    "[[0,0.2],[0.8,0.2],[0,0.2]]",
  );
  fireEvent.click(screen.getByRole("button", { name: "Go live" }));
  expect(screen.getByLabelText("Time window")).toHaveTextContent("15100,21100");
  expect(screen.getByLabelText("Plotted measurements")).toHaveTextContent("[0.4,0.2]");
});
