import { Box, Chip, Stack, Typography } from "@mui/material";
import { useCatalog } from "../api";
import { useRobotTelemetry } from "./RobotTelemetryProvider";
import { WorkspaceCanvas } from "./WorkspaceCanvas";
import type { CellLayout, Runtime } from "../types";

const noop = () => undefined;

/**
 * Browser-side illustration driven by the demo runtime's simulated joint samples.
 * Recording remains a UI state; no physical robot or camera is connected.
 */
export function DemoCellView({
  layout,
  robotData,
  recording,
}: {
  layout: CellLayout;
  robotData?: Runtime["robot_data"];
  recording: boolean;
}) {
  const liveRobotData = useRobotTelemetry()?.robot_data ?? robotData;
  const catalog = useCatalog().data?.layout;
  if (!catalog) return null;
  const D = layout.workspace.depth_m;
  const arms = layout.modules.filter((m) => m.type === "arm" && m.enabled);
  const overlay = arms.map((arm) => {
    const reach = Number(arm.properties.reach_m) || 0.3;
    const sample = liveRobotData?.[arm.properties.role === "leader" ? "Leader" : "Follower"];
    const position = (name: string) => sample?.positions[sample.joint_names.indexOf(name)] ?? 0;
    const angle = (arm.yaw_deg * Math.PI) / 180 + position("shoulder_pan");
    const radius = reach * (0.65 + 0.25 * Math.sin(position("elbow_flex")));
    const tx = arm.x + radius * Math.cos(angle);
    const ty = arm.y + radius * Math.sin(angle);
    return (
      <g key={arm.id} pointerEvents="none">
        <line
          x1={arm.x}
          y1={D - arm.y}
          x2={tx}
          y2={D - ty}
          stroke="#111"
          strokeWidth={0.012}
          strokeLinecap="round"
        />
        <circle cx={tx} cy={D - ty} r={0.02} fill="#e0a72e" stroke="#111" strokeWidth={0.004} />
      </g>
    );
  });
  return (
    <Box sx={{ position: "relative" }} aria-label="Simulated cell view">
      <WorkspaceCanvas
        layout={layout}
        catalog={catalog}
        selectedId={null}
        snapStep={0}
        level={null}
        readOnly
        overlay={overlay}
        onSelect={noop}
        onMove={noop}
        onNudge={noop}
        onDelete={noop}
      />
      <Stack direction="row" spacing={1} sx={{ position: "absolute", top: 14, left: 14 }}>
        <Chip size="small" label="SIMULATED VIEW" sx={{ bgcolor: "#fff3d6", color: "#7a5600" }} />
        {recording && <Chip size="small" color="error" label="REC" />}
      </Stack>
      <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
        Simulated joint motion. No physical robot or camera.
      </Typography>
    </Box>
  );
}
