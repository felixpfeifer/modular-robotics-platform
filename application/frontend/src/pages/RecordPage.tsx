import { useEffect, useEffectEvent, useState } from "react";
import {
  CheckCircleOutlined,
  ErrorOutline,
  FiberManualRecord,
  VideocamOffOutlined,
} from "@mui/icons-material";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { CameraPreview, cameraViewport } from "../components/CameraPreview";
import { DemoCellView } from "../components/DemoCellView";
import { RobotTelemetry } from "../components/RobotTelemetry";
import { ValidationVerdict } from "../components/ValidationVerdict";
import { formatDuration } from "../lib/format";
import type { CameraEntry, CellLayout, Episode, Runtime, Session } from "../types";

export function RecordPage({
  runtime,
  busy,
  projectId,
  start,
  mark,
  cell,
  realHardware = false,
  mockHandover = false,
  recordAction = null,
  teleop,
  mode,
  layout,
  cameras,
  sessions = [],
  episodes = [],
  note,
}: {
  runtime: Runtime;
  busy: boolean;
  projectId: string;
  start: () => void;
  mark: (kind: "success" | "failure" | "cancel") => void;
  cell: (confirmed?: boolean) => void;
  realHardware?: boolean;
  mockHandover?: boolean;
  recordAction?:
    "starting-cell" | "stopping-cell" | "starting-episode" | "finishing-episode" | null;
  teleop: () => void;
  mode?: "demo" | "ros";
  layout?: CellLayout;
  cameras?: CameraEntry[];
  sessions?: Session[];
  episodes?: Episode[];
  note?: (text: string) => void;
}) {
  const demo = mode === "demo";
  const cameraIds = runtime.camera_previews?.length ? runtime.camera_previews : [""];
  const active = sessions.find((item) => item.id === runtime.active_episode_id);
  const starting = active?.state === "starting" || recordAction === "starting-episode";
  const saving = active?.state === "finalizing" || recordAction === "finishing-episode";
  const validating = active?.state === "recorded";
  const episodePending = starting || saving || validating;
  const marking = Boolean(runtime.active_episode_id) && !episodePending;
  const timing = marking && Boolean(active);
  const [now, setNow] = useState(() => Date.now() / 1000);
  const [text, setText] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [countdown, setCountdown] = useState<number | null>(null);
  const handOver = useEffectEvent(() => {
    if (runtime.cell_running && runtime.active_source !== "teleop") teleop();
  });
  useEffect(() => {
    if (countdown === null) return;
    const timer = window.setTimeout(() => {
      if (countdown === 1) {
        setCountdown(null);
        handOver();
      } else setCountdown(countdown - 1);
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [countdown]);
  // Stopping the cell cancels a running countdown.
  const [cellWasRunning, setCellWasRunning] = useState(runtime.cell_running);
  if (cellWasRunning !== runtime.cell_running) {
    setCellWasRunning(runtime.cell_running);
    if (!runtime.cell_running) setCountdown(null);
  }
  useEffect(() => {
    if (!timing) return;
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 500);
    return () => window.clearInterval(timer);
  }, [timing]);
  // The newest finished session of this project, and the recorder's verdict on it.
  const last = sessions.find(
    (item) => item.id !== runtime.active_episode_id || item.state === "recorded",
  );
  const lastEpisode = last ? episodes.find((item) => item.id === last.id) : undefined;
  const elapsed = timing && active?.started ? Math.max(0, now - active.started) : null;
  return (
    <Stack spacing={2}>
      <Box>
        <Typography variant="overline" color="primary">
          CAPTURE
        </Typography>
        <Typography variant="h4">Recording studio</Typography>
        <Typography color="text.secondary" sx={{ mt: 1 }}>
          Prepare your cell and capture a new demonstration.
        </Typography>
      </Box>
      {demo && (
        <Alert severity="info">
          Demo runtime: this shows the workflow without hardware. Recordings are simulated, so no
          MCAP is written and nothing appears in Episodes. Run the ROS runtime to capture real data.
        </Alert>
      )}
      <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ md: "flex-start" }}>
        <Card sx={{ flex: 1, minWidth: 0 }}>
          <CardContent>
            <Typography variant="h6" sx={{ mb: 2 }}>
              {demo ? "Simulated cell" : "Camera feeds"}
            </Typography>
            {runtime.cell_running && !demo ? (
              <Box
                sx={{
                  display: "grid",
                  gap: 1.5,
                  gridTemplateColumns: {
                    xs: "minmax(0, 1fr)",
                    sm: `repeat(${Math.min(cameraIds.length, 2)}, minmax(0, 1fr))`,
                    xl: `repeat(${Math.min(cameraIds.length, 3)}, minmax(0, 1fr))`,
                  },
                }}
              >
                {cameraIds.map((id, index) => {
                  const label =
                    cameras?.find((camera) => camera.id === id)?.name ||
                    (id
                      ? id.replace(/[_-]+/g, " ").replace(/^./, (char) => char.toUpperCase())
                      : "Robot camera");
                  return (
                    <Box key={`${index === 0 ? "primary" : "secondary"}:${id}`}>
                      {id && (
                        <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
                          {label}
                        </Typography>
                      )}
                      <CameraPreview
                        label={label}
                        camera={id || undefined}
                        snapshot={index === 0}
                      />
                    </Box>
                  );
                })}
              </Box>
            ) : (
              <Box sx={cameraViewport}>
                {runtime.cell_running && layout ? (
                  <Box sx={{ width: "100%", p: 1, bgcolor: "#fff" }}>
                    <DemoCellView
                      layout={layout}
                      robotData={runtime.robot_data}
                      recording={Boolean(runtime.active_episode_id)}
                    />
                  </Box>
                ) : runtime.cell_running ? (
                  <Typography sx={{ color: "media.text" }}>Demo cell running</Typography>
                ) : (
                  <Stack
                    alignItems="center"
                    spacing={1}
                    sx={{ color: "media.text", textAlign: "center", p: 1 }}
                  >
                    <VideocamOffOutlined sx={{ fontSize: 36 }} />
                    <Typography fontWeight={600}>Camera is offline</Typography>
                    <Typography variant="body2">Start the cell to view camera feeds.</Typography>
                  </Stack>
                )}
              </Box>
            )}
            <Chip
              sx={{ mt: 2 }}
              size="small"
              label={runtime.cell_running ? "Cell running" : "Cell stopped"}
              color={runtime.cell_running ? "success" : "default"}
            />
          </CardContent>
        </Card>
        <Card sx={{ width: { md: 360 }, flexShrink: 0 }}>
          <CardContent>
            <Typography variant="h6">Capture controls</Typography>
            <Chip
              size="small"
              sx={{ mt: 1 }}
              color={
                saving || validating ? "warning" : runtime.active_episode_id ? "error" : "default"
              }
              label={
                starting
                  ? "Starting episode…"
                  : saving
                    ? "Saving recording…"
                    : validating
                      ? "Checking recording…"
                      : runtime.active_episode_id
                        ? `Recording${elapsed != null ? ` · ${formatDuration(elapsed)}` : " in progress"}`
                        : "Ready to record"
              }
            />
            <Typography color="text.secondary" sx={{ my: 2 }}>
              {!projectId && !runtime.cell_running
                ? "Create or select a project before starting the cell."
                : runtime.message}
            </Typography>
            <Stack spacing={1.5}>
              <Button
                variant="contained"
                startIcon={<FiberManualRecord />}
                disabled={
                  busy || episodePending || !projectId || Boolean(runtime.active_episode_id)
                }
                onClick={start}
              >
                {starting ? "Starting episode…" : "Start episode"}
              </Button>
              <Stack direction="row" spacing={1}>
                <Button
                  fullWidth
                  color="success"
                  variant="outlined"
                  disabled={!marking || busy}
                  onClick={() => mark("success")}
                >
                  Success
                </Button>
                <Button
                  fullWidth
                  color="error"
                  variant="outlined"
                  disabled={!marking || busy}
                  onClick={() => mark("failure")}
                >
                  Failure
                </Button>
              </Stack>
              <Button color="error" disabled={!marking || busy} onClick={() => mark("cancel")}>
                Cancel
              </Button>
              {note && (
                <Stack direction="row" spacing={1}>
                  <TextField
                    size="small"
                    fullWidth
                    label="Quick note"
                    value={text}
                    disabled={!marking}
                    slotProps={{ htmlInput: { maxLength: 256 } }}
                    onChange={(event) => setText(event.target.value)}
                  />
                  <Button
                    disabled={!marking || busy || !text.trim()}
                    onClick={() => {
                      note(text.trim());
                      setText("");
                    }}
                  >
                    Add
                  </Button>
                </Stack>
              )}
            </Stack>
          </CardContent>
        </Card>
      </Stack>
      <Card>
        <CardContent>
          <RobotTelemetry runtime={runtime} />
        </CardContent>
      </Card>
      <Card>
        <CardContent>
          <Stack
            direction={{ xs: "column", sm: "row" }}
            spacing={2}
            justifyContent="space-between"
            alignItems={{ xs: "flex-start", sm: "center" }}
          >
            <Box>
              <Typography variant="h6">Cell readiness</Typography>
              <Typography variant="body2" color="text.secondary">
                {runtime.active_source === "teleop"
                  ? "Teleoperation enabled"
                  : "Teleoperation is disabled"}
              </Typography>
            </Box>
            <Stack direction="row" spacing={1}>
              <Button
                variant="outlined"
                onClick={() =>
                  realHardware && !runtime.cell_running ? setConfirming(true) : cell()
                }
                disabled={
                  busy ||
                  episodePending ||
                  Boolean(runtime.active_episode_id) ||
                  (!runtime.cell_running && !projectId)
                }
              >
                {recordAction === "starting-cell"
                  ? "Starting cell…"
                  : recordAction === "stopping-cell"
                    ? "Stopping cell…"
                    : runtime.cell_running
                      ? "Stop cell"
                      : "Start cell"}
              </Button>
              <Button
                variant="contained"
                onClick={() => {
                  if (countdown !== null) setCountdown(null);
                  else if (mockHandover && runtime.active_source !== "teleop") setCountdown(3);
                  else teleop();
                }}
                disabled={!runtime.cell_running || busy}
              >
                {countdown !== null
                  ? `Cancel start (${countdown})`
                  : runtime.active_source === "teleop"
                    ? "Disable teleop"
                    : "Enable teleop"}
              </Button>
            </Stack>
          </Stack>
          <Divider sx={{ my: 2 }} />
          <Stack direction="row" flexWrap="wrap" gap={1}>
            {runtime.checks.map((check) => (
              <Chip
                key={check.name}
                icon={check.ready ? <CheckCircleOutlined /> : <ErrorOutline />}
                color={check.ready ? "success" : "default"}
                label={`${check.name}: ${check.ready ? "ready" : check.detail}`}
              />
            ))}
          </Stack>
        </CardContent>
      </Card>
      {!demo && last && (
        <Card>
          <CardContent>
            <Typography variant="h6">Last episode</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              {last.started ? new Date(last.started * 1000).toLocaleTimeString() : ""} · what the
              recorder concluded about it.
            </Typography>
            {last.state === "finalizing" ? (
              <Alert severity="info">Saving recording…</Alert>
            ) : last.state === "recorded" ? (
              lastEpisode && lastEpisode.status !== "pending_validation" ? (
                <ValidationVerdict
                  status={lastEpisode.status}
                  validation={lastEpisode.validation}
                />
              ) : (
                <Alert severity="info">Recording saved. Waiting for the validation result…</Alert>
              )
            ) : (
              <Alert severity="error">
                <strong>Not recorded ({last.state}).</strong>{" "}
                {last.detail || "No reason was given."}
                {last.detail?.includes("rejected the episode") &&
                  " Common causes: a stream is not fresh yet (wait until every readiness check is green), too little free disk space, or the recording settings do not match the cell."}
              </Alert>
            )}
          </CardContent>
        </Card>
      )}
      {sessions.length > 0 && (
        <Card>
          <CardContent>
            <Typography variant="h6">Session history</Typography>
            <Typography variant="body2" color="text.secondary">
              {demo
                ? "Demo sessions are kept as history only; they contain no recorded data."
                : "Newest first. Finished recordings continue to the Episodes library."}
            </Typography>
            <Stack sx={{ mt: 1 }}>
              {sessions.slice(0, 8).map((session) => (
                <Stack
                  key={session.id}
                  direction="row"
                  spacing={2}
                  alignItems="center"
                  sx={{ py: 1, borderTop: "1px solid", borderColor: "divider" }}
                >
                  <Typography variant="body2" sx={{ fontFamily: "monospace" }}>
                    {session.id.slice(0, 8)}
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
                    {session.started ? new Date(session.started * 1000).toLocaleTimeString() : ""}
                    {session.started && session.ended
                      ? ` · ${formatDuration(session.ended - session.started)}`
                      : ""}
                    {session.annotations?.length ? ` · ${session.annotations.length} note(s)` : ""}
                    {session.detail ? ` · ${session.detail}` : ""}
                  </Typography>
                  <Chip size="small" label={session.state.replaceAll("_", " ")} />
                </Stack>
              ))}
            </Stack>
          </CardContent>
        </Card>
      )}
      <Dialog open={confirming} onClose={() => setConfirming(false)}>
        <DialogTitle>Start the real robot cell?</DialogTitle>
        <DialogContent>
          <Typography>
            Real arms will be connected and the follower&apos;s motors powered. Check that the
            workspace is clear, the power switch is within reach and the connection test passed in
            the last 10 minutes.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirming(false)}>Cancel</Button>
          <Button
            variant="contained"
            color="warning"
            onClick={() => {
              setConfirming(false);
              cell(true);
            }}
          >
            Start with real hardware
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
