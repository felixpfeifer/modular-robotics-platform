import { useEffect, useState } from "react";
import { Outlet, useBlocker } from "react-router";
import {
  Alert,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Snackbar,
  Stack,
  Typography,
} from "@mui/material";
import { errorMessage, useEpisodes, useRefreshLive, useStatus, useWorkflow } from "../api";
import { AppShell } from "../components/AppShell";
import { ProjectDialogs, type WorkspaceDialog } from "./ProjectDialogs";
import { useRunAction } from "./useRunAction";
import { WorkspaceContext, type Workspace } from "./WorkspaceContext";

const PROJECT_KEY = "mrp-project";
const NO_EPISODES = new Set<string>();

/** Root route: loads live state, provides it to every page and guards unsaved cell edits. */
export function WorkspaceLayout() {
  const statusQuery = useStatus();
  const episodesQuery = useEpisodes();
  const status = statusQuery.data;
  const refreshLive = useRefreshLive();
  const actions = useRunAction();

  // The stored project wins while it exists; otherwise fall back to the first project.
  const [storedProjectId, setStoredProjectId] = useState(
    () => localStorage.getItem(PROJECT_KEY) || "",
  );
  const projectId = !status
    ? storedProjectId
    : status.projects.some((item) => item.id === storedProjectId)
      ? storedProjectId
      : (status.projects[0]?.id ?? "");
  useEffect(() => {
    if (status) localStorage.setItem(PROJECT_KEY, projectId);
  }, [status, projectId]);
  const workflow = useWorkflow(status ? projectId : "").data ?? null;

  const [cellDirty, setCellDirty] = useState(false);
  const [pendingProjectId, setPendingProjectId] = useState<string | null>(null);
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      cellDirty && currentLocation.pathname !== nextLocation.pathname,
  );
  useEffect(() => {
    if (!cellDirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [cellDirty]);

  const [dialog, setDialog] = useState<WorkspaceDialog | null>(null);
  const [selection, setSelection] = useState({ projectId, ids: NO_EPISODES });
  const selectedEpisodes = selection.projectId === projectId ? selection.ids : NO_EPISODES;

  // The export selection belongs to one project; switching always starts a fresh one.
  const changeProject = (next: string) => {
    setStoredProjectId(next);
    setSelection({ projectId: next, ids: NO_EPISODES });
  };
  const selectProject = (next: string) => {
    if (next === projectId) return;
    if (cellDirty) setPendingProjectId(next);
    else changeProject(next);
  };

  // Rebuilt on every render: the status poll changes it every two seconds anyway.
  const workspace: Workspace | undefined = status && {
    status,
    episodes: episodesQuery.data ?? [],
    workflow,
    projectId,
    project: status.projects.find((item) => item.id === projectId),
    sessions: status.sessions.filter((item) => item.project_id === projectId),
    selectProject,
    run: actions.run,
    runRecord: actions.runRecord,
    busy: actions.busy,
    recordAction: actions.recordAction,
    refresh: refreshLive,
    openDialog: setDialog,
    setCellDirty,
    selectedEpisodes,
    toggleEpisode: (id) => {
      const ids = new Set(selectedEpisodes);
      if (ids.has(id)) ids.delete(id);
      else ids.add(id);
      setSelection({ projectId, ids });
    },
  };

  const connectionError = statusQuery.error ?? episodesQuery.error;
  const leaving = blocker.state === "blocked" || pendingProjectId !== null;
  const stay = () => {
    blocker.reset?.();
    setPendingProjectId(null);
  };
  const leave = () => {
    if (pendingProjectId !== null) changeProject(pendingProjectId);
    setPendingProjectId(null);
    blocker.proceed?.();
  };

  return (
    <AppShell
      status={status ?? null}
      projectId={projectId}
      setProjectId={selectProject}
      connected={!connectionError}
    >
      {!workspace ? (
        <Stack alignItems="center" sx={{ py: 12 }}>
          {connectionError ? (
            <>
              <Typography variant="h6">Unable to connect to MRP</Typography>
              <Typography color="text.secondary" sx={{ mt: 1 }}>
                {errorMessage(connectionError, "API unavailable")}
              </Typography>
              <Button variant="outlined" sx={{ mt: 2 }} onClick={() => void statusQuery.refetch()}>
                Retry connection
              </Button>
            </>
          ) : (
            <>
              <CircularProgress />
              <Typography sx={{ mt: 2 }}>Connecting to MRP…</Typography>
            </>
          )}
        </Stack>
      ) : (
        <WorkspaceContext.Provider value={workspace}>
          {connectionError && (
            <Alert severity="warning" sx={{ mb: 2 }}>
              Connection lost. Showing the last available data; retrying automatically.
            </Alert>
          )}
          {/* Errors stay above the page until dismissed; successes confirm briefly and go. */}
          {actions.notice?.error && (
            <Alert severity="error" onClose={actions.clearNotice} sx={{ mb: 2 }}>
              {actions.notice.text}
            </Alert>
          )}
          <Snackbar
            open={Boolean(actions.notice && !actions.notice.error)}
            autoHideDuration={5000}
            onClose={(_, reason) => reason !== "clickaway" && actions.clearNotice()}
            anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
          >
            <Alert severity="success" variant="filled" onClose={actions.clearNotice}>
              {actions.notice?.text}
            </Alert>
          </Snackbar>
          <Outlet />
          <ProjectDialogs
            dialog={dialog}
            busy={actions.busy}
            run={actions.run}
            onClose={() => setDialog(null)}
            onCreated={(created) => changeProject(created.id)}
          />
        </WorkspaceContext.Provider>
      )}
      <Dialog open={leaving} onClose={stay} fullWidth maxWidth="xs">
        <DialogTitle>Leave without saving?</DialogTitle>
        <DialogContent>
          <Typography>You have unsaved cell changes. They are lost if you leave now.</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={stay}>Stay</Button>
          <Button color="warning" variant="contained" onClick={leave}>
            Leave without saving
          </Button>
        </DialogActions>
      </Dialog>
    </AppShell>
  );
}
