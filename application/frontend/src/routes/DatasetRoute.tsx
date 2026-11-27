import { exportDataset } from "../api";
import { DatasetPage } from "../pages/DatasetPage";
import { useWorkspace } from "../workspace/WorkspaceContext";

export function Component() {
  const { status, episodes, projectId, busy, run, refresh, selectedEpisodes, toggleEpisode } =
    useWorkspace();
  const accepted = episodes.filter(
    (item) => item.project_id === projectId && item.status === "accepted" && item.validation,
  );
  return (
    <DatasetPage
      episodes={accepted}
      jobs={(status.jobs ?? []).filter((job) => job.project_id === projectId || !job.project_id)}
      tokenSet={status.settings.hf_token_set}
      namespace={status.settings.hf_namespace}
      uploads={status.uploads ?? []}
      refresh={refresh}
      selected={selectedEpisodes}
      toggle={toggleEpisode}
      enabled={status.export_enabled}
      busy={busy}
      exportData={(downsampleRatio) =>
        void run(
          () =>
            exportDataset({
              project_id: projectId,
              episode_ids: [...selectedEpisodes],
              repo_id: "local/mrp-dataset",
              downsample_hz_ratio: downsampleRatio,
            }),
          "Dataset export queued.",
        )
      }
    />
  );
}
