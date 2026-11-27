import type { DatasetValidation, HubRepo } from "../types";
import { get, path, post, upload, withQuery } from "./client";

export type Visibility = "public" | "private";

export const exportDataset = (request: {
  project_id: string;
  episode_ids: string[];
  repo_id: string;
  downsample_hz_ratio: number;
}) => post("/api/v1/exports", { request_id: crypto.randomUUID(), ...request });

export const uploadDataset = (request: {
  export_id: string;
  repo_id: string;
  visibility: Visibility;
  confirm_public: boolean;
}) =>
  post("/api/v1/uploads", {
    request_id: crypto.randomUUID(),
    ...request,
    use_saved_token: true,
    confirm_upload: true,
  });

export const validateHubDataset = (repoId: string) =>
  post<DatasetValidation>("/api/v1/datasets/validate-hub", { repo_id: repoId });
export const validateDatasetZip = (file: Blob) =>
  upload<DatasetValidation>("/api/v1/datasets/validate-zip", file, "application/zip");

/** The signed-in user's Hub repositories; models can be narrowed to one runtime. */
export const listHubRepos = (kind: "models" | "datasets", runtime?: string) =>
  get<{ items: HubRepo[] }>(
    withQuery(path`/api/v1/hub/${kind}`, { runtime: kind === "models" ? runtime : undefined }),
  );
