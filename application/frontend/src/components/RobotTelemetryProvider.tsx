import { createContext, useContext, useState, type ReactNode } from "react";
import { useReconnectingWebSocket } from "../lib/useReconnectingWebSocket";
import type { Runtime } from "../types";

type Telemetry = Pick<Runtime, "robot_data" | "robot_data_simulated">;
const RobotTelemetryContext = createContext<Telemetry | null>(null);

export function useRobotTelemetry() {
  return useContext(RobotTelemetryContext);
}

export function RobotTelemetryProvider({ children }: { children: ReactNode }) {
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  useReconnectingWebSocket("/api/v1/telemetry", {
    // The backend sends at least one sample per second; silence means a stale connection.
    idleTimeoutMs: 3000,
    onMessage: (event, close) => {
      try {
        const value = JSON.parse(String(event.data));
        if (!value || typeof value.robot_data !== "object" || !value.robot_data) return;
        setTelemetry({
          robot_data: value.robot_data,
          robot_data_simulated: value.robot_data_simulated,
        });
      } catch {
        close();
      }
    },
    onClose: () => setTelemetry(null),
  });

  return (
    <RobotTelemetryContext.Provider value={telemetry}>{children}</RobotTelemetryContext.Provider>
  );
}
