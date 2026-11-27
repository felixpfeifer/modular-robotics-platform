import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  CardContent,
  Chip,
  FormControlLabel,
  Stack,
  Switch,
  Typography,
} from "@mui/material";
import {
  createBackup,
  deleteBackup,
  errorMessage,
  importBundle,
  queryKeys,
  useBackups,
  urls,
  validateBundle,
} from "../api";
import { formatBytes } from "../lib/format";
import type { Backup, BundleReport, RunAction } from "../types";

const STATUS_COLOR = { new: "success", identical: "default", conflict: "warning" } as const;

export function ConfigBackupCard({ run }: { run: RunAction }) {
  const backups: Backup[] = useBackups().data ?? [];
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.backups });
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<BundleReport | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const check = async (chosen: File) => {
    setFile(chosen);
    setReport(null);
    setError("");
    setOverwrite(false);
    setBusy(true);
    try {
      setReport(await validateBundle(chosen));
    } catch (e) {
      setError(errorMessage(e, "Validation failed."));
    } finally {
      setBusy(false);
    }
  };
  const apply = async () => {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      setReport(await importBundle(file, overwrite));
      void refresh();
    } catch (e) {
      setError(errorMessage(e, "Import failed."));
    } finally {
      setBusy(false);
    }
  };
  const conflicts = report?.items.calibrations.filter((c) => c.status === "conflict") ?? [];

  return (
    <Card sx={{ mt: 2 }}>
      <CardContent>
        <Typography variant="h6">Configuration backup and sharing</Typography>
        <Typography color="text.secondary" sx={{ mt: 1 }}>
          A backup is one <code>.tar.gz</code> with your arm calibration files, robot profiles, the
          components your cells use and each project&apos;s cell configuration. It contains no
          tokens, recordings or models. Backups are kept in the <code>user_data</code> volume; send
          the file to someone else to share a setup. Imports are checked first and only add: your
          existing projects are never replaced.
        </Typography>
        <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
          <Button
            variant="contained"
            onClick={() =>
              void run(() => createBackup().finally(() => void refresh()), "Backup saved.")
            }
          >
            Create backup
          </Button>
        </Stack>
        <Stack sx={{ mt: 2 }}>
          {backups.length === 0 && (
            <Typography color="text.secondary" variant="body2">
              No backups yet.
            </Typography>
          )}
          {backups.map((b) => (
            <Stack
              key={b.name}
              direction="row"
              spacing={1.5}
              alignItems="center"
              sx={{ py: 1, borderTop: "1px solid", borderColor: "divider" }}
            >
              <Stack sx={{ flex: 1, minWidth: 0 }}>
                <Typography fontWeight={650} noWrap>
                  {b.name}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {formatBytes(b.bytes)} · {new Date(b.created * 1000).toLocaleString()}
                </Typography>
              </Stack>
              <Button size="small" component="a" href={urls.backup(b.name)}>
                Download
              </Button>
              <Button
                size="small"
                color="error"
                onClick={() =>
                  void run(
                    () => deleteBackup(b.name).finally(() => void refresh()),
                    "Backup deleted.",
                  )
                }
              >
                Delete
              </Button>
            </Stack>
          ))}
        </Stack>

        <Typography variant="subtitle1" fontWeight={650} sx={{ mt: 3 }}>
          Import a bundle
        </Typography>
        <input
          ref={input}
          type="file"
          hidden
          data-testid="bundle-input"
          accept=".gz,.tgz,application/gzip"
          onChange={(e) => {
            const chosen = e.target.files?.[0];
            if (chosen) void check(chosen);
            e.target.value = "";
          }}
        />
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mt: 1 }}>
          <Button variant="outlined" disabled={busy} onClick={() => input.current?.click()}>
            Choose bundle…
          </Button>
          {file && (
            <Typography variant="body2" color="text.secondary">
              {file.name}
            </Typography>
          )}
        </Stack>
        {error && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {error}
          </Alert>
        )}
        {report && (
          <Stack spacing={1.5} sx={{ mt: 2 }}>
            {report.applied ? (
              <Alert severity="success">
                Imported {report.result?.projects_created.length ?? 0} project(s) and stored{" "}
                {report.result?.calibrations_stored.length ?? 0} calibration file(s).
                {(report.result?.calibrations_kept.length ?? 0) > 0 &&
                  ` Kept your existing ${report.result?.calibrations_kept.join(", ")}.`}
              </Alert>
            ) : report.valid ? (
              <Alert severity="success">All checks passed. Nothing has been imported yet.</Alert>
            ) : (
              <Alert severity="error">
                This bundle did not pass validation and cannot be imported.
              </Alert>
            )}
            {report.errors.map((message) => (
              <Alert key={message} severity="error" variant="outlined">
                {message}
              </Alert>
            ))}
            {report.warnings.map((message) => (
              <Alert key={message} severity="warning" variant="outlined">
                {message}
              </Alert>
            ))}
            <Stack spacing={0.5}>
              {report.items.calibrations.map((c) => (
                <Stack key={c.name} direction="row" spacing={1} alignItems="center">
                  <Chip size="small" label={c.status} color={STATUS_COLOR[c.status]} />
                  <Typography variant="body2">Calibration {c.name}</Typography>
                </Stack>
              ))}
              {report.items.robots.map((r) => (
                <Stack key={r.id} direction="row" spacing={1} alignItems="center">
                  <Chip
                    size="small"
                    label={r.status}
                    color={r.status === "known" ? "success" : "warning"}
                  />
                  <Typography variant="body2">Robot {r.label}</Typography>
                </Stack>
              ))}
              {report.items.projects.map((p) => (
                <Stack key={p.name} direction="row" spacing={1} alignItems="center">
                  <Chip size="small" label="new project" color="success" />
                  <Typography variant="body2">
                    {p.name} <span style={{ opacity: 0.6 }}>({p.preset})</span>
                  </Typography>
                </Stack>
              ))}
            </Stack>
            {!report.applied && report.valid && (
              <>
                {conflicts.length > 0 && (
                  <FormControlLabel
                    control={
                      <Switch
                        checked={overwrite}
                        onChange={(e) => setOverwrite(e.target.checked)}
                      />
                    }
                    label={`Replace my existing ${conflicts.map((c) => c.name).join(", ")} with the bundle's version`}
                  />
                )}
                <Stack direction="row">
                  <Button variant="contained" disabled={busy} onClick={() => void apply()}>
                    Import
                  </Button>
                </Stack>
              </>
            )}
          </Stack>
        )}
      </CardContent>
    </Card>
  );
}
