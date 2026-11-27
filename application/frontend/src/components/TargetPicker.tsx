import { Alert, MenuItem, Stack, TextField, Typography } from "@mui/material";
import { useCatalog } from "../api";
import type { PolicyRuntime, Settings } from "../types";

export type Choice = { runtime: string; target: string };

const NO_RUNTIMES: Record<string, PolicyRuntime> = {};

/** Where (local or a saved remote server) and which container a policy runs in. */
export function useRuntimes() {
  const catalog = useCatalog().data;
  return { runtimes: catalog?.runtimes ?? NO_RUNTIMES, hardware: catalog?.hardware };
}

export function TargetPicker({
  settings,
  value,
  onChange,
  purpose,
}: {
  settings: Settings;
  value: Choice;
  onChange: (next: Choice) => void;
  purpose: "train" | "serve";
}) {
  const { runtimes, hardware } = useRuntimes();
  const targets = settings.targets ?? [];
  const remote = value.target !== "local";
  const current = runtimes[value.runtime];
  const keys = Object.keys(runtimes).length ? Object.keys(runtimes) : ["lerobot_act"];
  const disabled = (key: string) => {
    const item = runtimes[key];
    if (!item) return false;
    if (remote) return false;
    if (purpose === "train" ? !item.local_train : !item.local_serve) return true;
    return item.local_available === false;
  };
  const reason = (key: string) => {
    const item = runtimes[key];
    if (!item || remote) return "";
    if (purpose === "train" && !item.local_train) return " (no local training)";
    return item.local_available === false ? " (needs NVIDIA GPU)" : "";
  };
  return (
    <Stack spacing={1.5}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
        <TextField
          select
          size="small"
          fullWidth
          label="Run on"
          value={value.target}
          onChange={(event) => {
            const target = event.target.value;
            const row = targets.find((t) => t.id === target);
            onChange({ target, runtime: row ? row.runtime : "lerobot_act" });
          }}
          helperText={
            hardware
              ? hardware.gpu
                ? `Local GPU: ${hardware.name} (${hardware.vram_gb} GB)`
                : "No local NVIDIA GPU detected."
              : undefined
          }
        >
          <MenuItem value="local">This machine (local container)</MenuItem>
          {targets.map((t) => (
            <MenuItem key={t.id} value={t.id}>
              {t.name} · {t.url}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          size="small"
          fullWidth
          label="Container"
          value={value.runtime}
          disabled={remote}
          onChange={(event) => onChange({ ...value, runtime: event.target.value })}
          helperText={current?.note}
        >
          {keys.map((key) => (
            <MenuItem key={key} value={key} disabled={disabled(key)}>
              {(runtimes[key]?.label ?? key) + reason(key)}
            </MenuItem>
          ))}
        </TextField>
      </Stack>
      {remote ? (
        <Alert severity="info">
          <Typography variant="body2">
            Remote servers are started by you; this app only connects to the URL. They download
            checkpoints from the Hub themselves, so large files never pass through here. Add targets
            in Settings.
          </Typography>
        </Alert>
      ) : (
        current?.local_available === false && (
          <Alert severity="warning">{current.local_reason}</Alert>
        )
      )}
    </Stack>
  );
}
