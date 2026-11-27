import type { Target } from "../types";
import { post } from "./client";

export type TargetInput = Pick<Target, "id" | "name" | "runtime" | "url" | "token_mode"> & {
  token?: string;
};

export const saveHubSettings = (settings: { hf_token?: string; hf_namespace: string }) =>
  post("/api/v1/settings", settings);
export const clearHubToken = () => post("/api/v1/settings", { clear_hf_token: true });
export const saveTarget = (target: TargetInput) =>
  post("/api/v1/settings", { target_upsert: target });
export const deleteTarget = (id: string) => post("/api/v1/settings", { target_delete: id });
