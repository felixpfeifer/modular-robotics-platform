import { EpisodesPage } from "../pages/EpisodesPage";
import { useWorkspace } from "../workspace/WorkspaceContext";

export function Component() {
  const { episodes, status, projectId, busy, openDialog } = useWorkspace();
  return (
    <EpisodesPage
      episodes={episodes}
      projects={status.projects}
      projectId={projectId}
      busy={busy}
      deleteEpisode={(episode) => openDialog({ kind: "delete-episode", episode })}
      mode={status.mode}
    />
  );
}
