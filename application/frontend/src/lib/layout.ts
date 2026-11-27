import type { CellLayout, LayoutCatalog, LayoutModule, ModuleType } from "../types";

const TOPIC = /^\/?[A-Za-z0-9_]+(\/[A-Za-z0-9_]+)*$/;
const MSG_TYPE = /^[A-Za-z0-9_]+\/(msg|srv|action)\/[A-Za-z0-9_]+$/;

export const clamp = (value: number, low: number, high: number) =>
  Math.min(high, Math.max(low, value));

export function snap(value: number, step: number): number {
  return step > 0 ? Math.round(value / step) * step : value;
}

export function round(value: number, digits = 3): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

export function nextModule(
  layout: CellLayout,
  catalog: LayoutCatalog,
  type: ModuleType,
): LayoutModule {
  const spec = catalog.module_types[type];
  const ids = new Set(layout.modules.map((module) => module.id));
  const names = new Set(layout.modules.map((module) => module.name.toLowerCase()));
  let n = 1;
  while (ids.has(`${type}_${n}`) || names.has(`${spec.label} ${n}`.toLowerCase())) n += 1;
  return {
    id: `${type}_${n}`,
    type,
    name: `${spec.label} ${n}`,
    x: round(layout.workspace.width_m / 2),
    y: round(layout.workspace.depth_m / 2),
    z: 0,
    yaw_deg: 0,
    width: spec.size[0],
    depth: spec.size[1],
    height: spec.height,
    parent: "",
    enabled: true,
    notes: "",
    namespace: "",
    properties: { ...spec.defaults },
    topics: [],
  };
}

export function duplicateModule(layout: CellLayout, source: LayoutModule): LayoutModule {
  const ids = new Set(layout.modules.map((module) => module.id));
  const names = new Set(layout.modules.map((module) => module.name.toLowerCase()));
  let n = 2;
  while (ids.has(`${source.type}_${n}`) || names.has(`${source.name} ${n}`.toLowerCase())) n += 1;
  return {
    ...structuredClone(source),
    id: `${source.type}_${n}`,
    name: `${source.name} ${n}`,
    x: round(clamp(source.x + 0.05, 0, layout.workspace.width_m)),
    y: round(clamp(source.y + 0.05, 0, layout.workspace.depth_m)),
    topics: [],
    namespace: "",
  };
}

/** Problems the server would reject, found early so Save can explain itself. */
export function layoutProblems(layout: CellLayout): string[] {
  const problems: string[] = [];
  const seen = new Map<string, string>();
  for (const module of layout.modules) {
    const name = module.name.trim();
    if (!name) problems.push("Every module needs a name.");
    else if (seen.has(name.toLowerCase()))
      problems.push(`Two modules are named “${name}”. Names must be unique.`);
    seen.set(name.toLowerCase(), module.id);
    const topics = new Set<string>();
    for (const topic of module.topics) {
      if (!TOPIC.test(topic.name))
        problems.push(`${name}: “${topic.name || "(empty)"}” is not a valid ROS topic name.`);
      else if (topics.has(topic.name.replace(/^\/?/, "/")))
        problems.push(`${name}: topic ${topic.name} is listed twice.`);
      topics.add(topic.name.replace(/^\/?/, "/"));
      if (topic.type && !MSG_TYPE.test(topic.type))
        problems.push(`${name}: “${topic.type}” is not a ROS type like sensor_msgs/msg/Image.`);
    }
  }
  return problems;
}

export const topOf = (module: LayoutModule) => round((module.z ?? 0) + (module.height ?? 0));

export function descendants(layout: CellLayout, id: string): Set<string> {
  const found = new Set<string>();
  let grew = true;
  while (grew) {
    grew = false;
    for (const module of layout.modules)
      if (
        module.parent &&
        (module.parent === id || found.has(module.parent)) &&
        !found.has(module.id)
      ) {
        found.add(module.id);
        grew = true;
      }
  }
  return found;
}

/** Move a module; everything placed on top of it travels with it. */
export function moveWithChildren(layout: CellLayout, id: string, x: number, y: number): CellLayout {
  const moved = layout.modules.find((module) => module.id === id);
  if (!moved) return layout;
  const dx = x - moved.x;
  const dy = y - moved.y;
  const riders = descendants(layout, id);
  const { width_m: W, depth_m: D } = layout.workspace;
  return {
    ...layout,
    modules: layout.modules.map((module) =>
      module.id === id
        ? { ...module, x, y }
        : riders.has(module.id)
          ? {
              ...module,
              x: round(clamp(module.x + dx, 0, W)),
              y: round(clamp(module.y + dy, 0, D)),
            }
          : module,
    ),
  };
}

/** Put a module on top of another (or back on the floor), updating its elevation. */
export function placeOn(layout: CellLayout, id: string, parentId: string): CellLayout {
  const parent = layout.modules.find((module) => module.id === parentId);
  return {
    ...layout,
    modules: layout.modules.map((module) =>
      module.id === id
        ? { ...module, parent: parent ? parent.id : "", z: parent ? topOf(parent) : 0 }
        : module,
    ),
  };
}

export const levelsOf = (layout: CellLayout): number[] =>
  [...new Set(layout.modules.map((module) => round(module.z ?? 0, 2)))].sort((a, b) => a - b);

export function sameLayout(a: CellLayout, b: CellLayout): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function topicRows(layout: CellLayout) {
  return layout.modules.flatMap((module) =>
    module.topics.map((topic) => ({ module, topic, key: `${module.id}:${topic.name}` })),
  );
}
