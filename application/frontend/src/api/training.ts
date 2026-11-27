import type { TrainingProgress } from "../types";
import type { Visibility } from "./datasets";
import { get, path, post } from "./client";

export const startTraining = (request: {
  project_id: string;
  runtime: string;
  target: string;
  export_id: string;
  settings: { steps: number; batch_size: number; chunk_size: number; smoke: boolean };
  label: string;
  device: string;
  confirm_cpu: boolean;
  base_model?: string;
}) => post("/api/v1/trainings", { request_id: crypto.randomUUID(), ...request });
export const getTrainingProgress = (id: string) =>
  get<TrainingProgress>(path`/api/v1/trainings/${id}/progress`);
export const abortTraining = (id: string) => post(path`/api/v1/trainings/${id}/abort`);

export const uploadModel = (request: {
  model_id: string;
  repo_id: string;
  visibility: Visibility;
  confirm_public: boolean;
}) =>
  post("/api/v1/model-uploads", {
    request_id: crypto.randomUUID(),
    ...request,
    confirm_upload: true,
  });
