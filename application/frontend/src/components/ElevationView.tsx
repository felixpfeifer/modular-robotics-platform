import type { CellLayout, LayoutCatalog } from "../types";
import { topOf } from "../lib/layout";

/** Side view (x across, height up). Shows what stands on what. */
export function ElevationView({
  layout,
  catalog,
  selectedId,
  onSelect,
}: {
  layout: CellLayout;
  catalog: LayoutCatalog;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const W = layout.workspace.width_m;
  const top = Math.max(1.2, ...layout.modules.map(topOf)) + 0.1;
  const order = [...layout.modules].sort((a, b) => (a.z ?? 0) - (b.z ?? 0));
  return (
    <svg
      role="img"
      aria-label="Side elevation of the workspace"
      viewBox={`-0.12 -0.05 ${W + 0.24} ${top + 0.15}`}
      style={{ width: "100%", display: "block", background: "#f4f7f5", borderRadius: 8 }}
    >
      {[0.5, 1, 1.5, 2]
        .filter((h) => h < top)
        .map((h) => (
          <g key={h}>
            <line x1={0} x2={W} y1={top - h} y2={top - h} stroke="#d5ddd8" strokeWidth={0.003} />
            <text x={-0.02} y={top - h + 0.012} fontSize={0.035} textAnchor="end" fill="#71807b">
              {h} m
            </text>
          </g>
        ))}
      <line x1={0} x2={W} y1={top} y2={top} stroke="#9aa6a1" strokeWidth={0.008} />
      {order.map((module) => {
        const spec = catalog.module_types[module.type];
        // Thin things (zones, cameras) get a minimum drawn height so they remain visible.
        const h = Math.max(module.height ?? 0, 0.025);
        return (
          <g
            key={module.id}
            data-testid={`elevation-${module.id}`}
            opacity={module.enabled ? 1 : 0.4}
            style={{ cursor: "pointer" }}
            onClick={() => onSelect(module.id)}
          >
            <rect
              x={module.x - module.width / 2}
              y={top - (module.z ?? 0) - h}
              width={module.width}
              height={h}
              fill={spec.color}
              fillOpacity={module.type === "fixture" ? 0.3 : 0.85}
              stroke={module.id === selectedId ? "#111" : spec.color}
              strokeWidth={module.id === selectedId ? 0.008 : 0.003}
            />
            <text
              x={module.x}
              y={top - (module.z ?? 0) - h - 0.02}
              fontSize={0.032}
              textAnchor="middle"
              fill="#1d302d"
              style={{ paintOrder: "stroke", stroke: "#fff", strokeWidth: 0.008 }}
            >
              {module.name}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
