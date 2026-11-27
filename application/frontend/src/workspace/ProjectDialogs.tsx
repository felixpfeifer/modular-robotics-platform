import { useState } from "react";
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Typography,
} from "@mui/material";
import { createProject, deleteEpisode, deleteProject, renameProject } from "../api";
import { formatBytes } from "../lib/format";
import type { Episode, Project, RunAction } from "../types";

export type WorkspaceDialog =
  | { kind: "create-project" }
  | { kind: "rename-project"; project: Project }
  | { kind: "delete-project"; project: Project }
  | { kind: "delete-episode"; episode: Episode };

type Common = { busy: boolean; run: RunAction; onClose: () => void };

/** The one open workspace dialog, if any. Each dialog keeps its own input state. */
export function ProjectDialogs({
  dialog,
  onCreated,
  ...common
}: Common & { dialog: WorkspaceDialog | null; onCreated: (project: Project) => void }) {
  switch (dialog?.kind) {
    case "create-project":
      return <CreateProjectDialog {...common} onCreated={onCreated} />;
    case "rename-project":
      return <RenameProjectDialog {...common} project={dialog.project} />;
    case "delete-project":
      return <DeleteProjectDialog {...common} project={dialog.project} />;
    case "delete-episode":
      return <DeleteEpisodeDialog {...common} episode={dialog.episode} />;
    default:
      return null;
  }
}

function CreateProjectDialog({
  busy,
  run,
  onClose,
  onCreated,
}: Common & { onCreated: (project: Project) => void }) {
  const [name, setName] = useState("");
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Create project</DialogTitle>
      <DialogContent>
        <TextField
          autoFocus
          fullWidth
          sx={{ mt: 1 }}
          label="Project name"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          disabled={!name.trim() || busy}
          onClick={() =>
            void run(async () => {
              onCreated(await createProject(name));
              onClose();
            }, "Project created.")
          }
        >
          Create
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function RenameProjectDialog({ busy, run, onClose, project }: Common & { project: Project }) {
  const [name, setName] = useState(project.name);
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Rename project</DialogTitle>
      <DialogContent>
        <TextField
          autoFocus
          fullWidth
          sx={{ mt: 1 }}
          label="Project name"
          value={name}
          slotProps={{ htmlInput: { maxLength: 80 } }}
          onChange={(event) => setName(event.target.value)}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          disabled={!name.trim() || name.trim() === project.name || busy}
          onClick={() =>
            void run(async () => {
              await renameProject(project.id, name.trim());
              onClose();
            }, "Project renamed.")
          }
        >
          Rename
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function DeleteProjectDialog({ busy, run, onClose, project }: Common & { project: Project }) {
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Delete “{project.name}”?</DialogTitle>
      <DialogContent>
        <Typography>
          This removes the project’s sessions, dataset exports, trained models and cell layout. Raw
          MCAP recordings stay on disk and remain in the Episodes library. This cannot be undone.
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          color="error"
          variant="contained"
          disabled={busy}
          onClick={() =>
            void run(async () => {
              await deleteProject(project.id);
              onClose();
            }, "Project deleted.")
          }
        >
          Delete project
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function DeleteEpisodeDialog({ busy, run, onClose, episode }: Common & { episode: Episode }) {
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Delete recording {episode.id.slice(0, 8)}?</DialogTitle>
      <DialogContent>
        <Typography>
          The episode folder, including its MCAP ({formatBytes(episode.size_bytes)}) and validation
          report, is deleted from disk. Datasets already exported from it are not affected. This
          cannot be undone.
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          color="error"
          variant="contained"
          disabled={busy}
          onClick={() =>
            void run(async () => {
              await deleteEpisode(episode.id);
              onClose();
            }, "Recording deleted.")
          }
        >
          Delete recording
        </Button>
      </DialogActions>
    </Dialog>
  );
}
