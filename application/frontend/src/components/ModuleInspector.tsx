import { useState } from "react";
import { Add, ContentCopy, DeleteOutline, Remove } from "@mui/icons-material";
import {
  Alert,
  Box,
  Button,
  FormControlLabel,
  IconButton,
  ListSubheader,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import { deleteCustomCamera, pullCameraImage } from "../api";
import { descendants } from "../lib/layout";
import type {
  CameraOrigin,
  CellLayout,
  LayoutCatalog,
  LayoutModule,
  ModelChoice,
  PropertyRule,
  Topic,
} from "../types";
import { CustomCameraDialog } from "./CustomCameraDialog";

type Props = {
  module: LayoutModule;
  layout: CellLayout;
  catalog: LayoutCatalog;
  onChange: (patch: Partial<LayoutModule>) => void;
  onPlaceOn: (parentId: string) => void;
  onDuplicate: () => void;
  onDelete: () => void;
  /** Reload the catalogue after a custom camera was added, removed or its image pulled. */
  onCatalogChange?: () => void;
};

function NumberField({
  label,
  value,
  step,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  step: number;
  min?: number;
  max?: number;
  onChange: (value: number) => void;
}) {
  return (
    <TextField
      size="small"
      type="number"
      label={label}
      value={Number.isFinite(value) ? value : ""}
      slotProps={{ htmlInput: { step, min, max } }}
      onChange={(event) => {
        const next = parseFloat(event.target.value);
        if (Number.isFinite(next)) onChange(next);
      }}
    />
  );
}

type ModelChoices = Record<string, ModelChoice>;

const ADD_CUSTOM = "__add_custom_camera__";
const ORIGIN_GROUPS: [CameraOrigin, string][] = [
  ["builtin", "Built-in"],
  ["discovered", "Found on this host"],
  ["custom", "Custom"],
];

function choiceLabel(id: string, choice: ModelChoice) {
  return (
    choice.label +
    (choice.status === "planned" && id !== "other" ? " (planned)" : "") +
    (choice.installed === false ? " · not on this host" : "")
  );
}

/** Camera types grouped by origin, then "Other" and the entry that opens the custom form. */
function cameraItems(models: ModelChoices) {
  const items = [];
  for (const [origin, title] of ORIGIN_GROUPS) {
    const group = Object.entries(models).filter(
      ([id, choice]) => id !== "other" && (choice.origin ?? "builtin") === origin,
    );
    if (!group.length) continue;
    items.push(<ListSubheader key={`group-${origin}`}>{title}</ListSubheader>);
    for (const [id, choice] of group)
      items.push(
        <MenuItem key={id} value={id}>
          {choiceLabel(id, choice)}
        </MenuItem>,
      );
  }
  if (models.other)
    items.push(
      <MenuItem key="other" value="other">
        {models.other.label}
      </MenuItem>,
    );
  items.push(
    <MenuItem key={ADD_CUSTOM} value={ADD_CUSTOM} sx={{ color: "primary.main" }}>
      + Add custom camera…
    </MenuItem>,
  );
  return items;
}

/** Pull the image of, or remove, the selected discovered/custom camera type. */
function CameraModelActions({
  id,
  choice,
  onCatalogChange,
}: {
  id: string;
  choice: ModelChoice;
  onCatalogChange?: () => void;
}) {
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const run = (action: "pull" | "delete") => {
    setBusy(action);
    setMessage(null);
    (action === "pull" ? pullCameraImage(id) : deleteCustomCamera(id))
      .then((reply) => {
        setMessage(
          action === "pull"
            ? { ok: reply.ok !== false, text: reply.detail || "Image pulled." }
            : { ok: true, text: "Custom camera removed." },
        );
        onCatalogChange?.();
      })
      .catch((e: Error) => setMessage({ ok: false, text: e.message }))
      .finally(() => setBusy(""));
  };
  return (
    <Stack spacing={1} sx={{ gridColumn: "1 / -1" }}>
      <Stack direction="row" spacing={1}>
        {choice.installed === false && (
          <Button size="small" variant="outlined" disabled={!!busy} onClick={() => run("pull")}>
            {busy === "pull" ? "Pulling…" : "Pull image"}
          </Button>
        )}
        {choice.origin === "custom" && (
          <Button size="small" color="error" disabled={!!busy} onClick={() => run("delete")}>
            Remove custom camera
          </Button>
        )}
      </Stack>
      {message && (
        <Alert severity={message.ok ? "success" : "error"} sx={{ py: 0 }}>
          {message.text}
        </Alert>
      )}
    </Stack>
  );
}

/** Arm/camera type and variant: catalogue names, and only the variants of the chosen type. */
function ModelFields({
  models,
  model,
  variant,
  onChange,
  camera = false,
  onCatalogChange,
}: {
  models: ModelChoices;
  model: string | undefined;
  variant: string | undefined;
  onChange: (model: string, variant: string | undefined) => void;
  /** Camera modules: group the types by origin and offer custom cameras. */
  camera?: boolean;
  onCatalogChange?: () => void;
}) {
  const [adding, setAdding] = useState(false);
  const variants = Object.entries(models[model ?? ""]?.variants ?? {});
  const selected = model ? models[model] : undefined;
  // "installed" is only known when a deployment agent reports the images.
  const agent = Object.values(models).some((choice) => choice.installed !== undefined);
  return (
    <>
      <TextField
        select
        size="small"
        label="type"
        value={model && models[model] ? model : ""}
        onChange={(event) =>
          event.target.value === ADD_CUSTOM
            ? setAdding(true)
            : onChange(event.target.value, undefined)
        }
      >
        {camera
          ? cameraItems(models)
          : Object.entries(models).map(([id, choice]) => (
              <MenuItem key={id} value={id}>
                {choiceLabel(id, choice)}
              </MenuItem>
            ))}
      </TextField>
      <TextField
        select
        size="small"
        label="variant"
        disabled={variants.length === 0}
        value={variants.some(([id]) => id === variant) ? variant : ""}
        onChange={(event) => onChange(model ?? "", event.target.value || undefined)}
      >
        <MenuItem value="">{variants.length ? "Not set" : "No variants"}</MenuItem>
        {variants.map(([id, name]) => (
          <MenuItem key={id} value={id}>
            {name}
          </MenuItem>
        ))}
      </TextField>
      {camera && model && selected && (selected.origin ?? "builtin") !== "builtin" && (
        <CameraModelActions id={model} choice={selected} onCatalogChange={onCatalogChange} />
      )}
      {camera && (
        <CustomCameraDialog
          open={adding}
          agent={agent}
          onClose={() => setAdding(false)}
          onSaved={(id) => {
            onCatalogChange?.();
            onChange(id, undefined);
          }}
        />
      )}
    </>
  );
}

function PropertyField({
  name,
  rule,
  value,
  onChange,
}: {
  name: string;
  rule: PropertyRule;
  value: string | number | boolean | undefined;
  onChange: (value: string | number | boolean | undefined) => void;
}) {
  const label = name.replaceAll("_", " ");
  if (rule.kind === "bool")
    return (
      <FormControlLabel
        label={label}
        control={<Switch checked={value === true} onChange={(_, on) => onChange(on)} />}
      />
    );
  if (rule.kind === "enum")
    return (
      <TextField
        select
        size="small"
        label={label}
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value)}
      >
        {rule.options.map((option) => (
          <MenuItem key={option} value={option}>
            {option.replaceAll("_", " ")}
          </MenuItem>
        ))}
      </TextField>
    );
  if (rule.kind === "text")
    return (
      <TextField
        size="small"
        label={label}
        value={value ?? ""}
        slotProps={{ htmlInput: { maxLength: rule.max_length } }}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  return (
    <TextField
      size="small"
      type="number"
      label={label}
      value={value ?? ""}
      slotProps={{
        htmlInput: { min: rule.min, max: rule.max, step: rule.kind === "int" ? 1 : "any" },
      }}
      onChange={(event) => {
        const raw = parseFloat(event.target.value);
        onChange(Number.isFinite(raw) ? (rule.kind === "int" ? Math.round(raw) : raw) : undefined);
      }}
    />
  );
}

export function ModuleInspector({
  module,
  layout,
  catalog,
  onChange,
  onPlaceOn,
  onDuplicate,
  onDelete,
  onCatalogChange,
}: Props) {
  const spec = catalog.module_types[module.type];
  const { width_m: W, depth_m: D } = layout.workspace;
  const blocked = descendants(layout, module.id);
  const candidates = layout.modules.filter((m) => m.id !== module.id && !blocked.has(m.id));
  const setTopic = (index: number, patch: Partial<Topic>) =>
    onChange({
      topics: module.topics.map((topic, i) => (i === index ? { ...topic, ...patch } : topic)),
    });
  const setProperty = (key: string, value: string | number | boolean | undefined) => {
    const next = { ...module.properties };
    if (value === undefined) delete next[key];
    else next[key] = value;
    onChange({ properties: next });
  };
  return (
    <Stack spacing={2} aria-label={`Settings for ${module.name}`}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Box>
          <Typography variant="overline" sx={{ color: spec.color }}>
            {spec.label}
          </Typography>
          <Typography variant="h6">{module.name || "Unnamed"}</Typography>
        </Box>
        <Stack direction="row">
          <IconButton aria-label="Duplicate module" onClick={onDuplicate}>
            <ContentCopy fontSize="small" />
          </IconButton>
          <IconButton aria-label="Delete module" color="error" onClick={onDelete}>
            <DeleteOutline fontSize="small" />
          </IconButton>
        </Stack>
      </Stack>
      <TextField
        size="small"
        label="Name"
        value={module.name}
        slotProps={{ htmlInput: { maxLength: 60 } }}
        error={!module.name.trim()}
        onChange={(event) => onChange({ name: event.target.value })}
      />
      <FormControlLabel
        label="Enabled in this cell"
        control={
          <Switch
            checked={module.enabled}
            onChange={(_, enabled) => onChange({ enabled })}
            slotProps={{ input: { "aria-label": "Enabled" } }}
          />
        }
      />
      <TextField
        select
        size="small"
        label="Placed on top of"
        value={module.parent || ""}
        helperText={
          module.parent
            ? "Moves with its base; elevation follows the base's top."
            : "On the floor, or mounted at the elevation below."
        }
        onChange={(event) => onPlaceOn(event.target.value)}
      >
        <MenuItem value="">Nothing (floor / free-standing)</MenuItem>
        {candidates.map((m) => (
          <MenuItem key={m.id} value={m.id}>
            {m.name}
          </MenuItem>
        ))}
      </TextField>
      <Typography variant="subtitle2">Pose (metres, degrees)</Typography>
      <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1.5 }}>
        <NumberField
          label="X"
          value={module.x}
          step={0.01}
          min={0}
          max={W}
          onChange={(x) => onChange({ x })}
        />
        <NumberField
          label="Y"
          value={module.y}
          step={0.01}
          min={0}
          max={D}
          onChange={(y) => onChange({ y })}
        />
        <NumberField
          label="Elevation Z"
          value={module.z}
          step={0.01}
          min={0}
          max={10}
          onChange={(z) => onChange({ z })}
        />
        <NumberField
          label="Height"
          value={module.height ?? 0}
          step={0.01}
          min={0}
          max={10}
          onChange={(height) => onChange({ height })}
        />
        <NumberField
          label="Yaw"
          value={module.yaw_deg}
          step={5}
          min={-360}
          max={360}
          onChange={(yaw_deg) => onChange({ yaw_deg })}
        />
        <NumberField
          label="Width"
          value={module.width}
          step={0.01}
          min={0.005}
          max={50}
          onChange={(width) => onChange({ width })}
        />
        <NumberField
          label="Depth"
          value={module.depth}
          step={0.01}
          min={0.005}
          max={50}
          onChange={(depth) => onChange({ depth })}
        />
      </Box>
      <Typography variant="caption" color="text.secondary">
        Yaw 0° faces right, 90° faces away from the operator, −90° faces the operator.
      </Typography>
      {Object.keys(spec.properties).length > 0 && (
        <>
          <Typography variant="subtitle2">Properties</Typography>
          <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1.5 }}>
            {spec.models && (
              <ModelFields
                camera={module.type === "camera"}
                onCatalogChange={onCatalogChange}
                models={spec.models}
                model={module.properties.model as string | undefined}
                variant={module.properties.variant as string | undefined}
                onChange={(model, variant) => {
                  const next: LayoutModule["properties"] = { ...module.properties, model };
                  if (variant) next.variant = variant;
                  else delete next.variant;
                  onChange({ properties: next });
                }}
              />
            )}
            {Object.entries(spec.properties)
              .filter(([key]) => !(spec.models && (key === "model" || key === "variant")))
              .map(([key, rule]) => (
                <PropertyField
                  key={key}
                  name={key}
                  rule={rule}
                  value={module.properties[key]}
                  onChange={(value) => setProperty(key, value)}
                />
              ))}
          </Box>
        </>
      )}
      <Typography variant="subtitle2">ROS interface</Typography>
      <TextField
        size="small"
        label="Namespace"
        placeholder="/follower"
        value={module.namespace}
        onChange={(event) => onChange({ namespace: event.target.value })}
      />
      {module.topics.map((topic, index) => (
        <Stack key={index} spacing={1} sx={{ p: 1.5, bgcolor: "surface.subtle", borderRadius: 2 }}>
          <Stack direction="row" spacing={1}>
            <TextField
              size="small"
              fullWidth
              label="Topic"
              placeholder="/top_camera/image/compressed"
              value={topic.name}
              onChange={(event) => setTopic(index, { name: event.target.value })}
            />
            <IconButton
              aria-label={`Remove topic ${topic.name || index + 1}`}
              onClick={() => onChange({ topics: module.topics.filter((_, i) => i !== index) })}
            >
              <Remove fontSize="small" />
            </IconButton>
          </Stack>
          <Stack direction="row" spacing={1}>
            <TextField
              size="small"
              fullWidth
              label="Message type"
              placeholder="sensor_msgs/msg/CompressedImage"
              value={topic.type}
              onChange={(event) => setTopic(index, { type: event.target.value })}
            />
            <TextField
              size="small"
              fullWidth
              label="Role"
              placeholder="observation.images.top"
              value={topic.role}
              onChange={(event) => setTopic(index, { role: event.target.value })}
            />
          </Stack>
        </Stack>
      ))}
      <Button
        size="small"
        startIcon={<Add />}
        disabled={module.topics.length >= 32}
        onClick={() => onChange({ topics: [...module.topics, { name: "", type: "", role: "" }] })}
      >
        Add topic
      </Button>
      <TextField
        size="small"
        multiline
        minRows={2}
        label="Notes"
        value={module.notes}
        slotProps={{ htmlInput: { maxLength: 280 } }}
        onChange={(event) => onChange({ notes: event.target.value })}
      />
    </Stack>
  );
}
