import { path, post } from "./client";

/** Who drives the follower arm. Switching to a policy needs explicit confirmation. */
export type ControlSource = "none" | "teleop" | "policy";

export const startCell = (projectId: string, operatorConfirmed = false) =>
  post("/api/v1/cell/up", {
    project_id: projectId,
    ...(operatorConfirmed && { operator_confirmed: true }),
  });
export const stopCell = (projectId: string) => post("/api/v1/cell/down", { project_id: projectId });
export const setControlSource = (source: ControlSource) =>
  post("/api/v1/control", { source, ...(source === "policy" && { confirm_policy: true }) });

export const startEpisode = (projectId: string) =>
  post("/api/v1/sessions", { project_id: projectId, request_id: crypto.randomUUID() });
export const markEpisode = (sessionId: string, kind: string) =>
  post(path`/api/v1/sessions/${sessionId}/mark`, { kind });
export const annotateEpisode = (sessionId: string, annotation: string) =>
  post(path`/api/v1/sessions/${sessionId}/mark`, { kind: "annotation", annotation });
