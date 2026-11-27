import { useState } from "react";
import { Box, Button, LinearProgress, Stack, Typography } from "@mui/material";
import { abortTraining, errorMessage, useTrainingProgress } from "../api";
import type { RunAction } from "../types";

export function formatDuration(seconds?: number | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return "–";
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h ? `${h}h ${m}m` : m ? `${m}m ${s}s` : `${s}s`;
}

/** Live step, loss and ETA of a running local training, with an abort button. */
export function TrainingProgress({ id, busy, run }: { id: string; busy: boolean; run: RunAction }) {
  const query = useTrainingProgress(id);
  const progress = query.data;
  const error = query.error ? errorMessage(query.error, "Progress unavailable.") : "";
  const [showLog, setShowLog] = useState(false);

  const starting = !progress || !progress.steps || !progress.step;
  const percent = progress?.percent ?? 0;
  const approx = progress?.step_is_approximate ? "≈" : "";
  return (
    <Box sx={{ pb: 1.5 }}>
      <LinearProgress
        variant={starting ? "indeterminate" : "determinate"}
        value={percent}
        sx={{ height: 8, borderRadius: 4 }}
      />
      <Stack direction="row" spacing={2} alignItems="center" sx={{ mt: 1 }} flexWrap="wrap">
        <Typography variant="body2">
          {starting
            ? "Starting: loading dataset and model…"
            : `Step ${approx}${progress.step} / ${progress.steps} (${percent}%)`}
        </Typography>
        {!starting && (
          <>
            <Typography variant="body2" color="text.secondary">
              ETA {formatDuration(progress.eta_seconds)}
            </Typography>
            {progress.loss != null && (
              <Typography variant="body2" color="text.secondary">
                loss {progress.loss}
              </Typography>
            )}
            {progress.seconds_per_step != null && (
              <Typography variant="body2" color="text.secondary">
                {progress.seconds_per_step.toFixed(2)} s/step
              </Typography>
            )}
          </>
        )}
        <Typography variant="body2" color="text.secondary">
          elapsed {formatDuration(progress?.elapsed_seconds)}
        </Typography>
        <Box sx={{ flex: 1 }} />
        <Button size="small" onClick={() => setShowLog((v) => !v)}>
          {showLog ? "Hide log" : "Log"}
        </Button>
        <Button
          size="small"
          color="error"
          disabled={busy}
          onClick={() => {
            if (window.confirm("Abort this training? Progress is lost and no model is saved.")) {
              void run(() => abortTraining(id), "Abort requested; stopping training.");
            }
          }}
        >
          Abort
        </Button>
      </Stack>
      {error && (
        <Typography variant="caption" color="error">
          {error}
        </Typography>
      )}
      {showLog && (
        <Box
          component="pre"
          sx={{
            mt: 1,
            p: 1,
            fontSize: 11,
            overflow: "auto",
            bgcolor: "action.hover",
            borderRadius: 1,
          }}
        >
          {(progress?.log_tail ?? []).join("\n") || "No log output yet."}
        </Box>
      )}
    </Box>
  );
}
