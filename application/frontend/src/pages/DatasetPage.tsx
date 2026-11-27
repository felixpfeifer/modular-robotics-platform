import { useState } from "react";
import { Dataset } from "@mui/icons-material";
import {
  Button,
  Card,
  CardContent,
  Chip,
  Checkbox,
  Box,
  TableContainer,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
  Stack,
  Alert,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  FormControlLabel,
} from "@mui/material";
import { HubBrowser } from "../components/HubBrowser";
import { errorMessage, uploadDataset, urls, validateDatasetZip, validateHubDataset } from "../api";
import type { DatasetValidation, Episode, Job, Upload } from "../types";
export function DatasetPage({
  episodes,
  jobs = [],
  tokenSet = false,
  namespace = "",
  uploads = [],
  refresh,
  selected,
  toggle,
  exportData,
  enabled,
  busy,
}: {
  episodes: Episode[];
  jobs?: Job[];
  tokenSet?: boolean;
  namespace?: string;
  uploads?: Upload[];
  refresh?: () => Promise<void>;
  selected: Set<string>;
  toggle: (id: string) => void;
  exportData: (downsampleRatio: number) => void;
  enabled: boolean;
  busy: boolean;
}) {
  const [uploadId, setUploadId] = useState("");
  const [downsampleRatio, setDownsampleRatio] = useState("1");
  const [repo, setRepo] = useState("");
  const [isPublic, setPublic] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [validation, setValidation] = useState<DatasetValidation | null>(null);
  const [validating, setValidating] = useState(false);
  const validateHub = async (repoId: string) => {
    setValidating(true);
    setValidation(null);
    try {
      setValidation(await validateHubDataset(repoId));
    } catch (error) {
      setValidation({ error: errorMessage(error, "Validation failed.") });
    } finally {
      setValidating(false);
    }
  };
  const validateZip = async (file: File) => {
    setValidating(true);
    setValidation(null);
    try {
      setValidation(await validateDatasetZip(file));
    } catch (error) {
      setValidation({ error: errorMessage(error, "Validation failed.") });
    } finally {
      setValidating(false);
    }
  };
  const upload = async () => {
    setUploading(true);
    setUploadError("");
    try {
      await uploadDataset({
        export_id: uploadId,
        repo_id: repo.trim(),
        visibility: isPublic ? "public" : "private",
        confirm_public: isPublic && confirmed,
      });
      setUploadId("");
      await refresh?.();
    } catch (error) {
      setUploadError(errorMessage(error, "Upload could not be started."));
    } finally {
      setUploading(false);
    }
  };
  return (
    <Stack spacing={2}>
      <Card>
        <CardContent>
          <Typography variant="overline" color="primary">
            DATASET
          </Typography>
          <Typography variant="h4">Accepted recordings</Typography>
          <Typography color="text.secondary">
            Only validated recordings can become a dataset.
          </Typography>
          <TableContainer>
            <Table sx={{ mt: 2, minWidth: 500 }}>
              <TableHead>
                <TableRow>
                  <TableCell>SELECT</TableCell>
                  <TableCell>EPISODE</TableCell>
                  <TableCell>TASK</TableCell>
                  <TableCell>STATUS</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {episodes.map((episode) => (
                  <TableRow key={episode.id}>
                    <TableCell>
                      <Checkbox
                        size="small"
                        inputProps={{ "aria-label": `Select episode ${episode.id}` }}
                        checked={selected.has(episode.id)}
                        onChange={() => toggle(episode.id)}
                      />
                    </TableCell>
                    <TableCell>{episode.id.slice(0, 8)}</TableCell>
                    <TableCell>{episode.manifest.task_id?.replaceAll("_", " ")}</TableCell>
                    <TableCell>
                      <Chip size="small" color="success" label="accepted" />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
          {!episodes.length && (
            <Box
              sx={{ textAlign: "center", py: 5, bgcolor: "surface.subtle", borderRadius: 2, mt: 2 }}
            >
              <Typography fontWeight={650}>No accepted recordings yet</Typography>
              <Typography variant="body2" color="text.secondary">
                Validated recordings will appear here when they are ready to export.
              </Typography>
            </Box>
          )}
          {!enabled && (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
              Export is currently unavailable. Connect an export-enabled runtime to create a
              dataset.
            </Typography>
          )}
          <TextField
            label="Frame stride"
            type="number"
            size="small"
            value={downsampleRatio}
            onChange={(event) => setDownsampleRatio(event.target.value)}
            slotProps={{ htmlInput: { min: 1, max: 120, step: 1 } }}
            helperText="Must divide camera FPS"
            sx={{ mt: 2, mr: 2, width: 130 }}
          />
          <Button
            sx={{ mt: 2 }}
            variant="contained"
            startIcon={<Dataset />}
            disabled={
              !selected.size ||
              !enabled ||
              busy ||
              !Number.isInteger(Number(downsampleRatio)) ||
              Number(downsampleRatio) < 1 ||
              Number(downsampleRatio) > 120
            }
            onClick={() => exportData(Number(downsampleRatio))}
          >
            Export selected recordings ({selected.size})
          </Button>
          <Typography variant="caption" color="text.secondary" display="block">
            Camera slowdowns and gaps are compressed in playback.
          </Typography>
        </CardContent>
      </Card>
      <Card>
        <CardContent>
          <Typography variant="h6">Local datasets and export jobs</Typography>
          <Typography variant="body2" color="text.secondary">
            Exports for the selected project and older unassigned exports. Completed datasets can be
            downloaded.
          </Typography>
          {jobs.length === 0 ? (
            <Typography color="text.secondary" sx={{ mt: 2 }}>
              No export jobs yet.
            </Typography>
          ) : (
            <TableContainer>
              <Table sx={{ mt: 1, minWidth: 600 }}>
                <TableHead>
                  <TableRow>
                    <TableCell>DATASET</TableCell>
                    <TableCell>CREATED</TableCell>
                    <TableCell>STATUS</TableCell>
                    <TableCell>ACTION</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {jobs.map((job) => (
                    <TableRow key={job.id}>
                      <TableCell>
                        <Typography fontWeight={600}>
                          {job.payload?.repo_id || `Export ${job.id.slice(0, 8)}`}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {job.id}
                          {!job.project_id ? " · Unassigned project" : ""}
                          {job.payload?.episode_ids
                            ? ` · ${job.payload.episode_ids.length} recordings`
                            : ""}
                          {job.payload?.downsample_hz_ratio
                            ? ` · stride ${job.payload.downsample_hz_ratio}`
                            : ""}
                          {job.detail ? ` · ${job.detail}` : ""}
                        </Typography>
                      </TableCell>
                      <TableCell>{new Date(job.created * 1000).toLocaleString()}</TableCell>
                      <TableCell>
                        <Chip
                          size="small"
                          label={job.state}
                          color={
                            job.state === "complete"
                              ? "success"
                              : job.state === "failed" || job.state === "interrupted"
                                ? "error"
                                : "default"
                          }
                        />
                      </TableCell>
                      <TableCell>
                        {job.state === "complete" && (
                          <Stack direction="row">
                            <Button size="small" href={urls.datasetZip(job.id)}>
                              Download ZIP
                            </Button>
                            <Button
                              size="small"
                              disabled={!enabled || !tokenSet}
                              onClick={() => {
                                setUploadId(job.id);
                                setRepo(namespace ? `${namespace}/` : "");
                                setPublic(false);
                                setConfirmed(false);
                                setUploadError("");
                              }}
                            >
                              Push to Hub
                            </Button>
                          </Stack>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
          {!tokenSet && (
            <Typography variant="body2" color="text.secondary">
              Save a Hugging Face token in Settings to upload datasets.
            </Typography>
          )}
          {uploads
            .filter((item) => jobs.some((job) => job.id === item.payload.export_id))
            .map((item) => (
              <Typography key={item.id} variant="body2" sx={{ mt: 1 }}>
                Upload to {item.payload.repo_id}: {item.state}
                {item.detail ? ` · ${item.detail}` : ""}
                {item.revision ? ` · ${item.revision.slice(0, 8)}` : ""}
              </Typography>
            ))}
        </CardContent>
      </Card>
      <Dialog
        open={Boolean(uploadId)}
        onClose={() => !uploading && setUploadId("")}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>Push dataset to Hugging Face</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 2 }}>
            The saved token must have permission to write to this repository.
          </Typography>
          <TextField
            autoFocus
            fullWidth
            label="Repository"
            placeholder="account/dataset"
            value={repo}
            onChange={(event) => setRepo(event.target.value)}
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={isPublic}
                onChange={(event) => {
                  setPublic(event.target.checked);
                  setConfirmed(false);
                }}
              />
            }
            label="Public dataset"
          />
          {isPublic && (
            <FormControlLabel
              control={
                <Checkbox
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
              }
              label="I understand this dataset will be public"
            />
          )}
          {uploadError && <Alert severity="error">{uploadError}</Alert>}
        </DialogContent>
        <DialogActions>
          <Button disabled={uploading} onClick={() => setUploadId("")}>
            Cancel
          </Button>
          <Button
            variant="contained"
            disabled={uploading || !repo.trim() || (isPublic && !confirmed)}
            onClick={() => void upload()}
          >
            Push dataset
          </Button>
        </DialogActions>
      </Dialog>
      <Card>
        <CardContent>
          <Typography variant="h6">Hugging Face datasets</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Browse datasets in your account or configured namespace.
          </Typography>
          <HubBrowser
            kind="datasets"
            tokenSet={tokenSet}
            action={{
              label: "Validate",
              disabled: validating,
              run: (repo) => void validateHub(repo.repo_id),
            }}
          />
        </CardContent>
      </Card>
      <Card>
        <CardContent>
          <Typography variant="h6">Validate an imported dataset</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ my: 1 }}>
            Check a LeRobot v3 dataset ZIP from your computer, or select Validate on a Hub dataset
            above. This structural check does not read frames.
          </Typography>
          <Button component="label" variant="outlined" disabled={validating}>
            Choose dataset ZIP
            <input
              hidden
              type="file"
              accept=".zip,application/zip"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void validateZip(file);
                event.target.value = "";
              }}
            />
          </Button>
          {validating && <Typography>Checking dataset…</Typography>}
          {validation && (
            <Alert sx={{ mt: 2 }} severity={validation.error ? "error" : "success"}>
              {validation.error ||
                `Structure passed. ${validation.scope} ${validation.episodes ?? "?"} episodes, ${validation.frames ?? "?"} frames reported.`}
            </Alert>
          )}
        </CardContent>
      </Card>
    </Stack>
  );
}
