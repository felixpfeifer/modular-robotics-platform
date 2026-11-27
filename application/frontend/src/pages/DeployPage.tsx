import { useState } from "react";
import { PlayArrow, Stop } from "@mui/icons-material";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  FormControlLabel,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { registerHubModel, setControlSource, startPolicy, stopPolicy } from "../api";
import { HubBrowser } from "../components/HubBrowser";
import { RobotTelemetry } from "../components/RobotTelemetry";
import { LaunchDialog } from "../components/LaunchDialog";
import { TargetPicker, type Choice } from "../components/TargetPicker";
import type { Project, RunAction, Status } from "../types";

export function DeployPage({
  project,
  status,
  busy,
  run,
}: {
  project?: Project;
  status: Status;
  busy: boolean;
  run: RunAction;
}) {
  const [modelId, setModelId] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [choice, setChoice] = useState<Choice>({ runtime: "lerobot_act", target: "local" });
  const [launch, setLaunch] = useState(false);
  if (!project) return <Alert severity="info">Select a project to deploy a policy.</Alert>;
  const models = (status.models ?? []).filter(
    (model) =>
      model.project_id === project.id &&
      model.state === "complete" &&
      (model.runtime ?? "lerobot_act") === choice.runtime &&
      (model.kind !== "hub" || choice.target !== "local" || choice.runtime !== "lerobot_act"),
  );
  const selected = models.some((m) => m.id === modelId) ? modelId : models[0]?.id || "";
  const chosen = models.find((m) => m.id === selected);
  const wired = choice.target === "local" && choice.runtime === "lerobot_act";
  const deployment = (status.deployments ?? []).find(
    (d) => d.project_id === project.id && (d.state === "starting" || d.state === "running"),
  );
  const source = status.runtime.active_source;
  const live = status.mode === "ros" && Boolean(status.agent_configured);
  const control = (next: "teleop" | "none" | "policy", message: string) =>
    void run(() => setControlSource(next), message);
  return (
    <Stack spacing={2}>
      <Box>
        <Typography variant="overline" color="primary">
          RUN
        </Typography>
        <Typography variant="h4">Deploy and run inference</Typography>
        <Typography color="text.secondary" sx={{ mt: 1 }}>
          Start the policy server for a trained model, then hand control to it. Control starts with
          you and can be taken back at any time.
        </Typography>
      </Box>
      {!live && (
        <Alert severity="info">
          Deployment needs the ROS runtime and deployment agent
          {status.mode === "demo" ? " (you are in demo mode)" : ""}. Mock and simulated cells only;
          physical robots are not supported yet.
        </Alert>
      )}
      <Card>
        <CardContent>
          <Typography variant="h6">1 · Policy server</Typography>
          <Box sx={{ mt: 1.5 }}>
            <TargetPicker
              settings={status.settings}
              value={choice}
              onChange={setChoice}
              purpose="serve"
            />
          </Box>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ mt: 2 }}>
            <TextField
              select
              size="small"
              fullWidth
              label="Model"
              value={selected}
              disabled={!models.length || Boolean(deployment)}
              helperText={models.length ? undefined : "Train or import a model first."}
              onChange={(event) => setModelId(event.target.value)}
            >
              {models.map((model) => (
                <MenuItem key={model.id} value={model.id}>
                  {model.label || model.id.slice(0, 8)} · {model.source.replaceAll("_", " ")}
                </MenuItem>
              ))}
            </TextField>
            {deployment ? (
              <Button
                color="error"
                variant="outlined"
                startIcon={<Stop />}
                disabled={busy || !live}
                onClick={() => void run(() => stopPolicy(project.id), "Policy stopped.")}
              >
                Stop
              </Button>
            ) : (
              <Button
                variant="contained"
                startIcon={<PlayArrow />}
                disabled={busy || !live || !selected || source !== "none" || !wired}
                onClick={() =>
                  void run(
                    () =>
                      startPolicy({
                        project_id: project.id,
                        runtime: choice.runtime,
                        target: choice.target,
                        model_id: selected,
                      }),
                    "Policy server started.",
                  )
                }
              >
                Start
              </Button>
            )}
          </Stack>
          {!wired && !deployment && (
            <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mt: 1.5 }}>
              <Button variant="outlined" onClick={() => setLaunch(true)}>
                Get launch command
              </Button>
              <Typography variant="caption" color="text.secondary">
                The policy source adapter for this container is not built yet, so Start is disabled.
                The command runs its server on the remote host.
              </Typography>
            </Stack>
          )}
          <Box sx={{ mt: 2 }}>
            <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
              Models on your Hub
            </Typography>
            <HubBrowser
              kind="models"
              runtime={choice.runtime}
              tokenSet={status.settings.hf_token_set}
              action={{
                label: "Register",
                run: (repo) =>
                  void run(
                    () =>
                      registerHubModel({
                        project_id: project.id,
                        repo_id: repo.repo_id,
                        runtime: choice.runtime,
                      }),
                    `${repo.repo_id} registered. It stays on the Hub.`,
                  ),
              }}
            />
          </Box>
          <LaunchDialog
            open={launch}
            onClose={() => setLaunch(false)}
            request={{
              purpose: "serve",
              runtime: choice.runtime,
              target: choice.target,
              repo_id: chosen?.repo_id ?? undefined,
            }}
          />
          {!deployment && source !== "none" && live && (
            <Typography variant="caption" color="text.secondary">
              Set the control source to none before starting a policy.
            </Typography>
          )}
          {deployment && (
            <Chip
              size="small"
              color="success"
              sx={{ mt: 1.5 }}
              label={`Policy ${deployment.state}`}
            />
          )}
        </CardContent>
      </Card>
      <Card>
        <CardContent>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Typography variant="h6">2 · Control</Typography>
            <Chip
              size="small"
              color={source === "policy" ? "warning" : "default"}
              label={`Source: ${source}`}
            />
          </Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            Handing control to the policy makes the follower arm move on its own. Keep the workspace
            clear.
          </Typography>
          <FormControlLabel
            sx={{ mt: 1 }}
            label="I understand the robot will move on its own"
            control={<Checkbox checked={confirm} onChange={(_, on) => setConfirm(on)} />}
          />
          <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
            <Button
              variant="contained"
              color="warning"
              disabled={busy || !live || !deployment || !confirm || source === "policy"}
              onClick={() => control("policy", "Policy has control.")}
            >
              Give control to policy
            </Button>
            <Button
              variant="outlined"
              disabled={busy || !live || source === "teleop"}
              onClick={() => {
                setConfirm(false);
                control("teleop", "Teleoperation has control.");
              }}
            >
              Take back (teleop)
            </Button>
            <Button
              color="error"
              disabled={busy || !live || source === "none"}
              onClick={() => {
                setConfirm(false);
                control("none", "Control released.");
              }}
            >
              Release
            </Button>
          </Stack>
        </CardContent>
      </Card>
      <RobotTelemetry runtime={status.runtime} />
    </Stack>
  );
}
