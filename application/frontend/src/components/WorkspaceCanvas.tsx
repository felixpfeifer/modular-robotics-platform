import { useRef, type ReactNode } from "react";
import { Box } from "@mui/material";
import type { CellLayout, LayoutCatalog, LayoutModule } from "../types";
import { clamp, round, snap } from "../lib/layout";

type Props = {
  layout: CellLayout;
  catalog: LayoutCatalog;
  selectedId: string | null;
  snapStep: number;
  level: number | null;
  /** Extra SVG drawn above the modules, in svg coordinates (y is flipped: svgY = depth - y). */
  overlay?: ReactNode;
  readOnly?: boolean;
  onSelect: (id: string | null) => void;
  onMove: (id: string, x: number, y: number) => void;
  onNudge: (id: string, dx: number, dy: number) => void;
  onDelete: (id: string) => void;
};

const MARGIN = 0.12;

/** Top-down workspace view. Operator at the bottom edge; x to the right, y away from the operator. */
export function WorkspaceCanvas({
  layout,
  catalog,
  selectedId,
  snapStep,
  level,
  overlay,
  readOnly,
  onSelect,
  onMove,
  onNudge,
  onDelete,
}: Props) {
  const { width_m: W, depth_m: D } = layout.workspace;
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<{ id: string; dx: number; dy: number } | null>(null);
  const toWorld = (event: { clientX: number; clientY: number }) => {
    const element = svg.current;
    const matrix = element?.getScreenCTM?.();
    if (!element || !matrix) return { x: 0, y: 0 };
    const point = element.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const local = point.matrixTransform(matrix.inverse());
    return { x: local.x, y: D - local.y };
  };
  const grid = [];
  const major = W > 4 || D > 4 ? 1 : 0.5;
  for (let x = 0; x <= W + 1e-9; x += 0.1)
    grid.push(
      <line
        key={`gx${x.toFixed(2)}`}
        x1={x}
        x2={x}
        y1={0}
        y2={D}
        stroke="#d5ddd8"
        strokeWidth={Math.abs(x / major - Math.round(x / major)) < 1e-6 ? 0.004 : 0.0015}
      />,
    );
  for (let y = 0; y <= D + 1e-9; y += 0.1)
    grid.push(
      <line
        key={`gy${y.toFixed(2)}`}
        x1={0}
        x2={W}
        y1={D - y}
        y2={D - y}
        stroke="#d5ddd8"
        strokeWidth={Math.abs(y / major - Math.round(y / major)) < 1e-6 ? 0.004 : 0.0015}
      />,
    );
  // Lower things are drawn first so whatever sits on top stays visible and clickable. Footprint-only
  // types (fixtures, zones) go under equally high modules.
  const layer = (module: LayoutModule) =>
    module.type === "fixture" ? 0 : module.type === "zone" ? 1 : 2;
  const ordered = [...layout.modules].sort(
    (a, b) => (a.z ?? 0) - (b.z ?? 0) || layer(a) - layer(b),
  );
  return (
    <Box
      sx={{
        bgcolor: "#f4f7f5",
        border: "1px solid",
        borderColor: "divider",
        borderRadius: 2,
        p: 1,
        touchAction: "none",
        "&:focus-within": { outline: "2px solid #245c56" },
      }}
    >
      <svg
        ref={svg}
        role="application"
        tabIndex={0}
        aria-label={`Workspace layout, ${W} by ${D} metres. Arrow keys move the selected module, Delete removes it.`}
        viewBox={`${-MARGIN} ${-MARGIN} ${W + 2 * MARGIN} ${D + 2 * MARGIN + 0.08}`}
        style={{ width: "100%", display: "block", userSelect: "none", outline: "none" }}
        onPointerDown={(event) => {
          if (event.target === event.currentTarget) onSelect(null);
        }}
        onPointerMove={(event) => {
          const active = drag.current;
          if (!active) return;
          const world = toWorld(event);
          onMove(
            active.id,
            round(clamp(snap(world.x - active.dx, snapStep), 0, W)),
            round(clamp(snap(world.y - active.dy, snapStep), 0, D)),
          );
        }}
        onPointerUp={() => (drag.current = null)}
        onPointerCancel={() => (drag.current = null)}
        onKeyDown={(event) => {
          if (!selectedId) return;
          const step = event.shiftKey ? 0.1 : 0.01;
          const moves: Record<string, [number, number]> = {
            ArrowLeft: [-step, 0],
            ArrowRight: [step, 0],
            ArrowUp: [0, step],
            ArrowDown: [0, -step],
          };
          if (moves[event.key]) {
            event.preventDefault();
            onNudge(selectedId, ...moves[event.key]);
          } else if (event.key === "Delete" || event.key === "Backspace") {
            event.preventDefault();
            onDelete(selectedId);
          } else if (event.key === "Escape") onSelect(null);
        }}
      >
        <rect
          x={0}
          y={0}
          width={W}
          height={D}
          fill="#ffffff"
          stroke="#9aa6a1"
          strokeWidth={0.006}
        />
        {grid}
        <text x={W / 2} y={D + 0.1} fontSize={0.04} textAnchor="middle" fill="#71807b">
          operator side · {W} × {D} m · frame “{layout.workspace.frame_id}”
        </text>
        {ordered.map((module) => {
          const spec = catalog.module_types[module.type];
          const selected = module.id === selectedId;
          const cy = D - module.y;
          const fov = Number(module.properties.fov_deg) || 70;
          const reach = Number(module.properties.reach_m) || 0;
          const wedge = 0.3;
          // Modules are drawn facing "up" (yaw 90°). SVG rotates clockwise, world yaw counter-clockwise,
          // so yaw 0° points right (+x) and -90° points at the operator.
          const rotation = `rotate(${90 - module.yaw_deg} ${module.x} ${cy})`;
          const half = (fov / 2) * (Math.PI / 180);
          return (
            <g
              key={module.id}
              opacity={
                (module.enabled ? 1 : 0.4) *
                (level === null || Math.abs((module.z ?? 0) - level) < 0.005 ? 1 : 0.22)
              }
              style={{ cursor: "grab" }}
              data-testid={`module-${module.id}`}
              onPointerDown={(event) => {
                if (readOnly) return;
                event.stopPropagation();
                onSelect(module.id);
                svg.current?.focus({ preventScroll: true });
                const world = toWorld(event);
                drag.current = { id: module.id, dx: world.x - module.x, dy: world.y - module.y };
                (event.currentTarget as Element).setPointerCapture?.(event.pointerId);
              }}
            >
              <g transform={rotation}>
                {module.type === "arm" && reach > 0 && (
                  <circle
                    cx={module.x}
                    cy={cy}
                    r={reach}
                    pointerEvents="none"
                    fill={spec.color}
                    fillOpacity={0.06}
                    stroke={spec.color}
                    strokeOpacity={0.5}
                    strokeWidth={0.004}
                    strokeDasharray="0.02 0.015"
                  />
                )}
                {module.type === "camera" && (
                  <path
                    pointerEvents="none"
                    d={`M ${module.x} ${cy} L ${module.x + wedge * Math.sin(half)} ${cy - wedge * Math.cos(half)} A ${wedge} ${wedge} 0 0 0 ${module.x - wedge * Math.sin(half)} ${cy - wedge * Math.cos(half)} Z`}
                    fill={spec.color}
                    fillOpacity={0.14}
                    stroke={spec.color}
                    strokeOpacity={0.6}
                    strokeWidth={0.003}
                  />
                )}
                <rect
                  x={module.x - module.width / 2}
                  y={cy - module.depth / 2}
                  width={module.width}
                  height={module.depth}
                  rx={module.type === "object" ? module.width / 2 : 0.008}
                  fill={spec.color}
                  fillOpacity={
                    module.type === "fixture" ? 0.18 : module.type === "zone" ? 0.25 : 0.85
                  }
                  stroke={selected ? "#111" : spec.color}
                  strokeWidth={selected ? 0.008 : 0.004}
                  strokeDasharray={module.type === "zone" ? "0.02 0.012" : undefined}
                />
                {module.type !== "fixture" && module.type !== "zone" && (
                  <path
                    d={`M ${module.x} ${cy} l 0 ${-Math.max(module.depth, 0.06) / 2 - 0.025}`}
                    stroke="#fff"
                    strokeWidth={0.008}
                    strokeLinecap="round"
                  />
                )}
              </g>
              <text
                x={module.x}
                y={cy + Math.max(module.depth, 0.06) / 2 + 0.04}
                fontSize={0.032}
                textAnchor="middle"
                fill="#1d302d"
                fontWeight={selected ? 700 : 500}
                style={{ paintOrder: "stroke", stroke: "#fff", strokeWidth: 0.008 }}
              >
                {module.name}
                {(module.z ?? 0) > 0 ? ` · z ${(module.z ?? 0).toFixed(2)}` : ""}
              </text>
            </g>
          );
        })}
        {overlay}
      </svg>
    </Box>
  );
}
