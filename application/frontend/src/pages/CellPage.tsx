import { useCallback, useMemo, useRef, useState } from "react";
import {
  Add,
  FileDownloadOutlined,
  FileUploadOutlined,
  RestartAlt,
  Save,
} from "@mui/icons-material";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { errorMessage, saveLayout, useCatalog, useInvalidateCatalog } from "../api";
import { ModuleInspector } from "../components/ModuleInspector";
import { ElevationView } from "../components/ElevationView";
import { WorkspaceCanvas } from "../components/WorkspaceCanvas";
import {
  clamp,
  duplicateModule,
  layoutProblems,
  levelsOf,
  moveWithChildren,
  nextModule,
  placeOn,
  round,
  sameLayout,
  topicRows,
} from "../lib/layout";
import type { CellLayout, LayoutModule, ModuleType, Project, RunAction } from "../types";

export function CellPage({
  project,
  busy,
  run,
}: {
  project?: Project;
  busy: boolean;
  run: RunAction;
}) {
  const catalogQuery = useCatalog();
  const catalog = catalogQuery.data?.layout;
  const loadError = catalogQuery.error && errorMessage(catalogQuery.error, "Catalog unavailable");
  // Reloaded after a custom camera type is added or removed, or its driver image pulled.
  const reloadCatalog = useInvalidateCatalog();
  const [draft, setDraft] = useState<CellLayout | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [snapStep, setSnapStep] = useState(0.01);
  const [level, setLevel] = useState<number | null>(null);
  const [importError, setImportError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  const saved = project?.cell_layout ?? null;
  const dirty = Boolean(draft && saved && !sameLayout(draft, saved));
  // A new project starts with nothing selected, at all heights.
  const [shownProject, setShownProject] = useState(project?.id);
  if (shownProject !== project?.id) {
    setShownProject(project?.id);
    setSelectedId(null);
    setLevel(null);
  }
  // Adopt the server's layout when the project changes or after a save, never over unsaved edits.
  const savedKey = JSON.stringify(saved);
  const [adopted, setAdopted] = useState<{ projectId: string; savedKey: string } | null>(null);
  if (saved && project && (adopted?.projectId !== project.id || adopted.savedKey !== savedKey)) {
    const otherProject = adopted?.projectId !== project.id;
    setAdopted({ projectId: project.id, savedKey });
    if (otherProject || !dirty)
      setDraft((old) => (old && sameLayout(old, saved) ? old : structuredClone(saved)));
  }

  const update = useCallback(
    (change: (layout: CellLayout) => CellLayout) => setDraft((old) => (old ? change(old) : old)),
    [],
  );
  const patchModule = (id: string, patch: Partial<LayoutModule>) =>
    update((layout) => ({
      ...layout,
      modules: layout.modules.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    }));
  const problems = useMemo(() => (draft ? layoutProblems(draft) : []), [draft]);
  const selected = draft?.modules.find((module) => module.id === selectedId);

  if (!project)
    return (
      <Card>
        <CardContent>
          <Typography variant="h6">Select a project first</Typography>
          <Typography color="text.secondary">
            Each project keeps its own workspace layout.
          </Typography>
        </CardContent>
      </Card>
    );
  if (loadError) return <Alert severity="error">{loadError}</Alert>;
  if (!catalog || !draft)
    return (
      <Stack alignItems="center" sx={{ py: 10 }}>
        <CircularProgress />
      </Stack>
    );

  const addModule = (type: ModuleType) => {
    if (draft.modules.length >= catalog.max_modules) return;
    const module = nextModule(draft, catalog, type);
    update((layout) => ({ ...layout, modules: [...layout.modules, module] }));
    setSelectedId(module.id);
  };
  const removeModule = (id: string) => {
    // Whatever stood on the removed module stays where it is, at its current elevation.
    update((layout) => ({
      ...layout,
      modules: layout.modules
        .filter((m) => m.id !== id)
        .map((m) => (m.parent === id ? { ...m, parent: "" } : m)),
    }));
    setSelectedId(null);
  };
  const exportJson = () => {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(draft, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `${project.name.replace(/[^A-Za-z0-9_-]+/g, "_") || "cell"}-layout.json`;
    link.click();
    URL.revokeObjectURL(url);
  };
  const importJson = async (file: File) => {
    setImportError("");
    try {
      const parsed = JSON.parse(await file.text()) as CellLayout;
      if (!parsed || !Array.isArray(parsed.modules) || !parsed.workspace)
        throw new Error("Not a cell layout file.");
      setDraft(parsed);
      setSelectedId(null);
    } catch (error) {
      setImportError(error instanceof Error ? error.message : "Could not read the file.");
    }
  };
  const { workspace } = draft;
  const rows = topicRows(draft);
  return (
    <Stack spacing={2}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "flex-start", sm: "center" }}
        spacing={2}
      >
        <Box>
          <Typography variant="overline" color="primary">
            WORKSPACE
          </Typography>
          <Typography variant="h4">Cell configuration</Typography>
          <Typography color="text.secondary" sx={{ mt: 1, maxWidth: 680 }}>
            Describe where robots, cameras, sensors and fixtures sit and which ROS topics they use.
            The layout is saved with the project and attached to every episode you record. It does
            not change which cell the deployment agent starts.
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} alignItems="center">
          {dirty && <Chip size="small" color="warning" label="Unsaved changes" />}
          {!project.layout_saved && !dirty && (
            <Chip size="small" label="Template default, not saved yet" />
          )}
          <Button
            startIcon={<RestartAlt />}
            disabled={!dirty || busy}
            onClick={() => {
              if (saved) setDraft(structuredClone(saved));
              setSelectedId(null);
            }}
          >
            Revert
          </Button>
          <Button
            variant="contained"
            startIcon={<Save />}
            disabled={busy || problems.length > 0 || (!dirty && Boolean(project.layout_saved))}
            onClick={() => void run(() => saveLayout(project.id, draft), "Cell layout saved.")}
          >
            Save layout
          </Button>
        </Stack>
      </Stack>
      {problems.length > 0 && (
        <Alert severity="warning">
          {problems.map((problem) => (
            <div key={problem}>{problem}</div>
          ))}
        </Alert>
      )}
      {importError && (
        <Alert severity="error" onClose={() => setImportError("")}>
          {importError}
        </Alert>
      )}
      <Stack direction={{ xs: "column", lg: "row" }} spacing={2} alignItems="flex-start">
        <Stack spacing={2} sx={{ flex: 1, minWidth: 0, width: "100%" }}>
          <Card>
            <CardContent>
              <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mb: 2 }} alignItems="center">
                <Typography variant="subtitle2" sx={{ mr: 1 }}>
                  Add module
                </Typography>
                {(Object.keys(catalog.module_types) as ModuleType[]).map((type) => (
                  <Button
                    key={type}
                    size="small"
                    variant="outlined"
                    startIcon={<Add />}
                    disabled={draft.modules.length >= catalog.max_modules}
                    onClick={() => addModule(type)}
                    sx={{ borderColor: catalog.module_types[type].color, color: "text.primary" }}
                  >
                    {catalog.module_types[type].label}
                  </Button>
                ))}
                <Box sx={{ flex: 1 }} />
                <TextField
                  select
                  size="small"
                  label="Snap"
                  value={snapStep}
                  sx={{ minWidth: 100 }}
                  onChange={(event) => setSnapStep(Number(event.target.value))}
                >
                  <MenuItem value={0}>Off</MenuItem>
                  <MenuItem value={0.01}>1 cm</MenuItem>
                  <MenuItem value={0.05}>5 cm</MenuItem>
                  <MenuItem value={0.1}>10 cm</MenuItem>
                </TextField>
              </Stack>
              <Stack direction="row" gap={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1.5 }}>
                <Typography variant="subtitle2" sx={{ mr: 1 }}>
                  Level
                </Typography>
                <Chip
                  size="small"
                  label="All"
                  color={level === null ? "primary" : "default"}
                  onClick={() => setLevel(null)}
                />
                {levelsOf(draft).map((z) => (
                  <Chip
                    key={z}
                    size="small"
                    label={z === 0 ? "Floor · 0 m" : `${z.toFixed(2)} m`}
                    color={level === z ? "primary" : "default"}
                    onClick={() => setLevel(z)}
                  />
                ))}
              </Stack>
              <WorkspaceCanvas
                layout={draft}
                catalog={catalog}
                selectedId={selectedId}
                snapStep={snapStep}
                level={level}
                onSelect={setSelectedId}
                onMove={(id, x, y) => update((layout) => moveWithChildren(layout, id, x, y))}
                onNudge={(id, dx, dy) => {
                  const m = draft.modules.find((item) => item.id === id);
                  if (m)
                    update((layout) =>
                      moveWithChildren(
                        layout,
                        id,
                        round(clamp(m.x + dx, 0, workspace.width_m)),
                        round(clamp(m.y + dy, 0, workspace.depth_m)),
                      ),
                    );
                }}
                onDelete={removeModule}
              />
              <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
                Drag modules to place them. With the canvas focused, arrow keys nudge the selection
                (Shift for 10 cm) and Delete removes it. Dashed circles show arm reach; wedges show
                camera field of view. Pick a level to highlight what sits at that elevation.
              </Typography>
            </CardContent>
          </Card>
          <Card>
            <CardContent>
              <Typography variant="h6">Side view</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                Heights at a glance. Use “Placed on top of” in a module’s settings to stack it, for
                example the cube and target zone on the table. Stacked modules move with their base.
              </Typography>
              <ElevationView
                layout={draft}
                catalog={catalog}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
            </CardContent>
          </Card>
          <Card>
            <CardContent>
              <Typography variant="h6">Topic map</Typography>
              <Typography variant="body2" color="text.secondary">
                Every ROS topic declared in this layout; disabled modules are dimmed. Roles name how
                a topic feeds the dataset, for example <code>observation.images.top</code> or{" "}
                <code>action</code>.
              </Typography>
              {rows.length ? (
                <TableContainer>
                  <Table size="small" sx={{ mt: 1, minWidth: 520 }}>
                    <TableHead>
                      <TableRow>
                        <TableCell>MODULE</TableCell>
                        <TableCell>TOPIC</TableCell>
                        <TableCell>TYPE</TableCell>
                        <TableCell>ROLE</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {rows.map(({ module, topic, key }) => (
                        <TableRow key={key} sx={{ opacity: module.enabled ? 1 : 0.5 }}>
                          <TableCell>{module.name}</TableCell>
                          <TableCell sx={{ fontFamily: "monospace" }}>{topic.name}</TableCell>
                          <TableCell sx={{ fontFamily: "monospace" }}>
                            {topic.type || "—"}
                          </TableCell>
                          <TableCell>{topic.role || "—"}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              ) : (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
                  No topics declared yet. Select a module and add its topics.
                </Typography>
              )}
            </CardContent>
          </Card>
        </Stack>
        <Stack spacing={2} sx={{ width: { xs: "100%", lg: 380 }, flexShrink: 0 }}>
          <Card>
            <CardContent>
              {selected ? (
                <ModuleInspector
                  module={selected}
                  layout={draft}
                  catalog={catalog}
                  onChange={(patch) => patchModule(selected.id, patch)}
                  onCatalogChange={() => void reloadCatalog()}
                  onPlaceOn={(parentId) =>
                    update((layout) => placeOn(layout, selected.id, parentId))
                  }
                  onDuplicate={() => {
                    const copy = duplicateModule(draft, selected);
                    update((layout) => ({ ...layout, modules: [...layout.modules, copy] }));
                    setSelectedId(copy.id);
                  }}
                  onDelete={() => removeModule(selected.id)}
                />
              ) : (
                <Stack spacing={2}>
                  <Typography variant="h6">Workspace</Typography>
                  <TextField
                    size="small"
                    label="Name"
                    value={workspace.name}
                    onChange={(event) =>
                      update((l) => ({
                        ...l,
                        workspace: { ...l.workspace, name: event.target.value },
                      }))
                    }
                  />
                  <Stack direction="row" spacing={1.5}>
                    {(["width_m", "depth_m"] as const).map((key) => (
                      <TextField
                        key={key}
                        size="small"
                        type="number"
                        label={key === "width_m" ? "Width (m)" : "Depth (m)"}
                        value={workspace[key]}
                        slotProps={{ htmlInput: { min: 0.2, max: 20, step: 0.1 } }}
                        onChange={(event) => {
                          const value = parseFloat(event.target.value);
                          if (Number.isFinite(value) && value >= 0.2 && value <= 20)
                            update((l) => ({ ...l, workspace: { ...l.workspace, [key]: value } }));
                        }}
                      />
                    ))}
                  </Stack>
                  <TextField
                    size="small"
                    label="Frame ID"
                    value={workspace.frame_id}
                    helperText="TF frame of the workspace origin (front-left corner)."
                    error={!/^[A-Za-z0-9_]{1,40}$/.test(workspace.frame_id)}
                    onChange={(event) =>
                      update((l) => ({
                        ...l,
                        workspace: { ...l.workspace, frame_id: event.target.value },
                      }))
                    }
                  />
                  <Typography variant="body2" color="text.secondary">
                    Select a module on the canvas to edit its pose, properties and ROS topics.
                  </Typography>
                </Stack>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardContent>
              <Typography variant="h6">Templates and files</Typography>
              <Stack spacing={1.5} sx={{ mt: 1.5 }}>
                <TextField
                  select
                  size="small"
                  label="Start from a template"
                  value=""
                  onChange={(event) => {
                    const template = catalog.templates[event.target.value];
                    if (template) {
                      setDraft(structuredClone(template.layout));
                      setSelectedId(null);
                    }
                  }}
                  helperText="Replaces the current draft. Nothing is saved until you press Save."
                >
                  {Object.entries(catalog.templates).map(([key, template]) => (
                    <MenuItem key={key} value={key}>
                      <Box>
                        <Typography variant="body2">{template.label}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          {template.description}
                        </Typography>
                      </Box>
                    </MenuItem>
                  ))}
                </TextField>
                <Stack direction="row" spacing={1}>
                  <Button size="small" startIcon={<FileDownloadOutlined />} onClick={exportJson}>
                    Export JSON
                  </Button>
                  <Button
                    size="small"
                    startIcon={<FileUploadOutlined />}
                    onClick={() => fileInput.current?.click()}
                  >
                    Import JSON
                  </Button>
                  <input
                    ref={fileInput}
                    type="file"
                    accept="application/json,.json"
                    hidden
                    aria-label="Import layout file"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) void importJson(file);
                      event.target.value = "";
                    }}
                  />
                </Stack>
                <Typography variant="caption" color="text.secondary">
                  {draft.modules.length} of {catalog.max_modules} modules.
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </Stack>
      </Stack>
    </Stack>
  );
}
