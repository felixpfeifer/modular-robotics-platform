import type { CameraActionReply, CustomCameraReply, CustomCameraRequest } from "../types";
import { path, post } from "./client";

export const saveCustomCamera = (request: CustomCameraRequest) =>
  post<CustomCameraReply>("/api/v1/cameras", request);
export const pullCameraImage = (id: string) =>
  post<CameraActionReply>(path`/api/v1/cameras/${id}/pull`);
export const deleteCustomCamera = (id: string) =>
  post<CameraActionReply>(path`/api/v1/cameras/${id}/delete`);
