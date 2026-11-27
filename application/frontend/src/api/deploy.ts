import { post } from "./client";

export const startPolicy = (request: {
  project_id: string;
  runtime: string;
  target: string;
  model_id: string;
}) => post("/api/v1/policy", { request_id: crypto.randomUUID(), ...request, action: "start" });
export const stopPolicy = (projectId: string) =>
  post("/api/v1/policy", {
    request_id: crypto.randomUUID(),
    project_id: projectId,
    action: "stop",
  });
/** Registers a Hub model with the project; the weights stay on the Hub. */
export const registerHubModel = (request: {
  project_id: string;
  repo_id: string;
  runtime: string;
}) => post("/api/v1/models/hub-ref", { request_id: crypto.randomUUID(), ...request });
