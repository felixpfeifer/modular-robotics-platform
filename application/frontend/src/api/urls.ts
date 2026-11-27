import { apiUrl, path, withQuery } from "./client";

/** Links the browser opens directly: downloads, previews and the API docs. */
export const urls = {
  docs: () => apiUrl("/docs"),
  episodeRecording: (id: string) => apiUrl(path`/api/v1/episodes/${id}/recording.mcap`),
  datasetZip: (exportId: string) => apiUrl(path`/api/v1/exports/${exportId}/dataset.zip`),
  backup: (name: string) => apiUrl(path`/api/v1/config/backups/${name}`),
  trainingNotebook: (
    projectId: string,
    settings: { steps: number; batch_size: number; chunk_size: number },
  ) =>
    apiUrl(
      withQuery(path`/api/v1/projects/${projectId}/notebook.ipynb`, { source: "zip", ...settings }),
    ),
  /** `t` busts the browser cache so each poll fetches a new frame. */
  cameraSnapshot: (t: number, camera?: string) =>
    apiUrl(withQuery("/api/v1/preview.jpg", { t, camera: camera || undefined })),
};
