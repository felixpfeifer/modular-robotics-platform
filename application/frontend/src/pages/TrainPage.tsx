import { useState } from "react";
import { FileDownloadOutlined, ModelTraining } from "@mui/icons-material";
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
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
} from "@mui/material";
import {
  errorMessage,
  useCatalog,
  startTraining,
  uploadModel as pushModelToHub,
  urls,
} from "../api";
import { HubBrowser } from "../components/HubBrowser";
import { LaunchDialog } from "../components/LaunchDialog";
import { TrainingProgress } from "../components/TrainingProgress";
import { TargetPicker, useRuntimes, type Choice } from "../components/TargetPicker";
import type { Catalog, Project, RunAction, Status } from "../types";

type Policies = NonNullable<Catalog["policies"]>;
const NO_POLICIES: Policies = {};

export function TrainPage({
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
  const policies: Policies = useCatalog().data?.policies ?? NO_POLICIES;
  const [policy, setPolicy] = useState("act");
  const [exportId, setExportId] = useState("");
  const [base, setBase] = useState("");
  const [steps, setSteps] = useState(1000);
  const [batch, setBatch] = useState(8);
  const [chunk, setChunk] = useState(100);
  const [smoke, setSmoke] = useState(false);
  const [device, setDevice] = useState("auto");
  const [confirmCpu, setConfirmCpu] = useState(false);
  const { hardware } = useRuntimes();
  const gpu = hardware?.gpu === true;
  // Without a usable GPU the run is CPU-only, which can take hours: the user must say they want that.
  const needsCpuConfirmation = !gpu && !smoke && device !== "cuda";
  const [label, setLabel] = useState("");
  const [choice, setChoice] = useState<Choice>({ runtime: "lerobot_act", target: "local" });
  const [hubDataset, setHubDataset] = useState("");
  const [launch, setLaunch] = useState(false);
  const [uploadModel, setUploadModel] = useState("");
  const [uploadRepo, setUploadRepo] = useState("");
  const [publicModel, setPublicModel] = useState(false);
  const [confirmPublic, setConfirmPublic] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [uploading, setUploading] = useState(false);
  const pushModel = async () => {
    setUploading(true);
    setUploadError("");
    try {
      await pushModelToHub({
        model_id: uploadModel,
        repo_id: uploadRepo.trim(),
        visibility: publicModel ? "public" : "private",
        confirm_public: publicModel && confirmPublic,
      });
      setUploadModel("");
    } catch (error) {
      setUploadError(errorMessage(error, "Model upload could not be started."));
    } finally {
      setUploading(false);
    }
  };
  const mine = (row: { project_id?: string | null }) => row.project_id === project?.id;
  const exports = (status.jobs ?? []).filter((job) => mine(job) && job.state === "complete");
  const trainings = (status.trainings ?? []).filter(mine);
  // A finished run is listed once, as its model.
  const unfinished = trainings.filter((t) => t.state !== "complete");
  const models = (status.models ?? []).filter((model) => mine(model));
  const ready = models.filter((model) => model.state === "complete");
  const exportValue = exportId || exports[0]?.id || "";
  const info = policies[policy];
  const agent = Boolean(status.agent_configured) && status.mode === "ros";
  const running = trainings.some((t) => t.state === "queued" || t.state === "running");
  const wired = choice.target === "local" && choice.runtime === "lerobot_act";
  if (!project) return <Alert severity="info">Select a project to train a policy.</Alert>;
  return (
    <Stack spacing={2}>
      <Box>
        <Typography variant="overline" color="primary">
          LEARN
        </Typography>
        <Typography variant="h4">Train a policy</Typography>
        <Typography color="text.secondary" sx={{ mt: 1 }}>
          Fit a policy to the datasets exported from this project. You can train here on CPU, train
          on a GPU server with a generated notebook, or bring a checkpoint you trained elsewhere.
        </Typography>
      </Box>
      {!agent && (
        <Alert severity="info">
          Training runs through the deployment agent, which only exists with the ROS runtime
          {status.mode === "demo" ? " (you are in demo mode)" : ""}. You can still download a
          notebook below.
        </Alert>
      )}
      <Card>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 1.5 }}>
            Where and with what
          </Typography>
          <TargetPicker
            settings={status.settings}
            value={choice}
            onChange={setChoice}
            purpose="train"
          />
        </CardContent>
      </Card>
      <Card>
        <CardContent>
          <Stack spacing={2}>
            {!wired && (
              <Alert severity="info">
                Only local ACT training runs inside this app. For this choice, use{" "}
                <b>Get launch command</b>: the container trains from the Hub dataset below and
                pushes the model back to your Hub, where you can register it on the Deploy page.
              </Alert>
            )}
            <TextField
              select
              size="small"
              label="Policy"
              value={policy}
              onChange={(event) => setPolicy(event.target.value)}
              helperText={info?.note}
            >
              {Object.entries(policies).map(([key, item]) => (
                <MenuItem key={key} value={key} disabled={item.status !== "available"}>
                  {item.label}
                  {item.status !== "available" ? " (planned)" : ""}
                </MenuItem>
              ))}
              {!Object.keys(policies).length && <MenuItem value="act">ACT (LeRobot)</MenuItem>}
            </TextField>
            {info?.status === "planned" && <Alert severity="warning">{info.note}</Alert>}
            <TextField
              select
              size="small"
              label="Dataset export"
              value={exportValue}
              disabled={!exports.length}
              helperText={
                exports.length
                  ? "Completed LeRobot exports of this project."
                  : "Export accepted episodes on the Dataset page first."
              }
              onChange={(event) => setExportId(event.target.value)}
            >
              {exports.map((job) => (
                <MenuItem key={job.id} value={job.id}>
                  {new Date(job.created * 1000).toLocaleString()} · {job.id.slice(0, 8)}
                </MenuItem>
              ))}
            </TextField>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
              {(
                [
                  ["Steps", steps, setSteps, 200000],
                  ["Batch size", batch, setBatch, 256],
                  ["Chunk size", chunk, setChunk, 200],
                ] as const
              ).map(([name, value, set, max]) => (
                <TextField
                  key={name}
                  size="small"
                  type="number"
                  label={name}
                  value={value}
                  fullWidth
                  slotProps={{ htmlInput: { min: 1, max } }}
                  onChange={(event) => {
                    const next = parseInt(event.target.value, 10);
                    if (Number.isFinite(next)) set(Math.min(max, Math.max(1, next)));
                  }}
                />
              ))}
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
              <TextField
                size="small"
                fullWidth
                label="Model label"
                value={label}
                slotProps={{ htmlInput: { maxLength: 80 } }}
                onChange={(event) => setLabel(event.target.value)}
              />
              <TextField
                select
                size="small"
                fullWidth
                label="Fine-tune from"
                value={base}
                disabled={smoke}
                onChange={(event) => setBase(event.target.value)}
              >
                <MenuItem value="">Train from scratch</MenuItem>
                {ready.map((model) => (
                  <MenuItem key={model.id} value={model.path}>
                    {model.label || model.id.slice(0, 8)}
                  </MenuItem>
                ))}
              </TextField>
            </Stack>
            <TextField
              select
              size="small"
              fullWidth
              label="Train on"
              value={device}
              onChange={(event) => setDevice(event.target.value)}
            >
              <MenuItem value="auto">
                {gpu ? `Automatic (GPU: ${hardware?.name})` : "Automatic (CPU, no GPU found)"}
              </MenuItem>
              <MenuItem value="cuda" disabled={!gpu}>
                NVIDIA GPU
                {gpu ? ` (${hardware?.name}, ${hardware?.vram_gb} GB)` : " (not available)"}
              </MenuItem>
              <MenuItem value="cpu">CPU</MenuItem>
            </TextField>
            {!gpu && !smoke && (
              <Alert severity="warning">
                <Typography variant="body2">
                  {hardware
                    ? `No usable NVIDIA GPU was detected${hardware.detail ? `: ${hardware.detail}` : "."}`
                    : "The GPU check did not finish, so no GPU can be used."}{" "}
                  Training on the CPU is very slow and can take many hours. You can also train on a
                  GPU machine with the notebook below.
                </Typography>
                <FormControlLabel
                  label="Train on the CPU anyway"
                  control={
                    <Checkbox checked={confirmCpu} onChange={(_, on) => setConfirmCpu(on)} />
                  }
                />
              </Alert>
            )}
            <FormControlLabel
              label="Smoke test (tiny model, checks the pipeline only)"
              control={
                <Checkbox
                  checked={smoke}
                  onChange={(_, on) => {
                    setSmoke(on);
                    if (on) setBase("");
                  }}
                />
              }
            />
            <Stack direction="row" spacing={1} flexWrap="wrap">
              <Button
                variant="contained"
                startIcon={<ModelTraining />}
                disabled={
                  busy ||
                  !wired ||
                  !agent ||
                  !exportValue ||
                  running ||
                  info?.status === "planned" ||
                  (needsCpuConfirmation && !confirmCpu)
                }
                onClick={() =>
                  void run(
                    () =>
                      startTraining({
                        project_id: project.id,
                        runtime: choice.runtime,
                        target: choice.target,
                        export_id: exportValue,
                        settings: { steps, batch_size: batch, chunk_size: chunk, smoke },
                        label,
                        device,
                        confirm_cpu: needsCpuConfirmation && confirmCpu,
                        ...(base ? { base_model: base } : {}),
                      }),
                    "Training started.",
                  )
                }
              >
                Start training
              </Button>
              {!wired && (
                <Button variant="contained" onClick={() => setLaunch(true)}>
                  Get launch command
                </Button>
              )}
              <Button
                component="a"
                startIcon={<FileDownloadOutlined />}
                href={urls.trainingNotebook(project.id, {
                  steps,
                  batch_size: batch,
                  chunk_size: chunk,
                })}
              >
                GPU notebook
              </Button>
              {exportValue && (
                <Button
                  component="a"
                  startIcon={<FileDownloadOutlined />}
                  href={urls.datasetZip(exportValue)}
                >
                  Dataset ZIP
                </Button>
              )}
            </Stack>
          </Stack>
        </CardContent>
      </Card>
      <Card>
        <CardContent>
          <Typography variant="h6">Datasets on your Hub</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {hubDataset
              ? `Selected for the launch command: ${hubDataset}`
              : "Pick a dataset a remote or GPU container should train on."}
          </Typography>
          <HubBrowser
            kind="datasets"
            tokenSet={status.settings.hf_token_set}
            action={{ label: "Use", run: (repo) => setHubDataset(repo.repo_id) }}
          />
        </CardContent>
      </Card>
      <LaunchDialog
        open={launch}
        onClose={() => setLaunch(false)}
        request={{
          purpose: "train",
          runtime: choice.runtime,
          target: choice.target,
          repo_id: hubDataset || undefined,
          steps,
          batch_size: batch,
        }}
      />
      <Card>
        <CardContent>
          <Typography variant="h6">Runs and models</Typography>
          {unfinished.length + models.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              Nothing yet. Trained and imported models appear here and can be deployed.
            </Typography>
          ) : (
            <Stack sx={{ mt: 1 }}>
              {unfinished.map((t) => (
                <Stack key={t.id}>
                  <Row
                    id={t.id}
                    title={t.payload?.label || "Training run"}
                    sub={`training · ${t.detail}`}
                    state={t.state}
                  />
                  {(t.state === "running" || t.state === "queued") && (
                    <TrainingProgress id={t.id} busy={busy} run={run} />
                  )}
                </Stack>
              ))}
              {models.map((m) => (
                <Stack key={m.id}>
                  <Row
                    id={m.id}
                    title={m.label || "Model"}
                    sub={`${m.source.replaceAll("_", " ")} · ${m.detail}`}
                    state={m.state}
                  />
                  {m.kind !== "hub" && m.state === "complete" && (
                    <Button
                      size="small"
                      sx={{ alignSelf: "flex-end" }}
                      disabled={!status.settings.hf_token_set || !status.agent_configured}
                      onClick={() => {
                        setUploadModel(m.id);
                        setUploadRepo(
                          status.settings.hf_namespace ? `${status.settings.hf_namespace}/` : "",
                        );
                        setPublicModel(false);
                        setConfirmPublic(false);
                        setUploadError("");
                      }}
                    >
                      Push model to Hub
                    </Button>
                  )}
                  {(status.uploads ?? [])
                    .filter((item) => item.payload.model_id === m.id)
                    .map((item) => (
                      <Typography key={item.id} variant="body2">
                        Upload to {item.payload.repo_id}: {item.state} · {item.detail}
                      </Typography>
                    ))}
                </Stack>
              ))}
            </Stack>
          )}
        </CardContent>
      </Card>
      <Dialog
        open={Boolean(uploadModel)}
        onClose={() => !uploading && setUploadModel("")}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>Push model to Hugging Face</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 2 }}>
            The saved token must have write access to this repository.
          </Typography>
          <TextField
            autoFocus
            fullWidth
            label="Model repository"
            placeholder="account/model"
            value={uploadRepo}
            onChange={(event) => setUploadRepo(event.target.value)}
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={publicModel}
                onChange={(event) => {
                  setPublicModel(event.target.checked);
                  setConfirmPublic(false);
                }}
              />
            }
            label="Public model"
          />
          {publicModel && (
            <FormControlLabel
              control={
                <Checkbox
                  checked={confirmPublic}
                  onChange={(event) => setConfirmPublic(event.target.checked)}
                />
              }
              label="I understand this model will be public"
            />
          )}
          {uploadError && <Alert severity="error">{uploadError}</Alert>}
        </DialogContent>
        <DialogActions>
          <Button disabled={uploading} onClick={() => setUploadModel("")}>
            Cancel
          </Button>
          <Button
            variant="contained"
            disabled={uploading || !uploadRepo.trim() || (publicModel && !confirmPublic)}
            onClick={() => void pushModel()}
          >
            Push model
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

function Row({ id, title, sub, state }: { id: string; title: string; sub: string; state: string }) {
  return (
    <Stack
      direction="row"
      spacing={2}
      alignItems="center"
      sx={{ py: 1.25, borderTop: "1px solid", borderColor: "divider" }}
    >
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography fontWeight={650} noWrap>
          {title}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {id.slice(0, 8)} · {sub}
        </Typography>
      </Box>
      <Chip
        size="small"
        label={state}
        color={
          state === "complete"
            ? "success"
            : state === "failed"
              ? "error"
              : state === "aborted"
                ? "warning"
                : "default"
        }
      />
    </Stack>
  );
}
