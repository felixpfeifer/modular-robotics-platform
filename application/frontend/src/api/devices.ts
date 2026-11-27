import type { DeviceScan, IdentifyResult } from "../types";
import { get, post } from "./client";

export type CalibrationStep =
  | { step: "zero" | "save" }
  /** Records joint ranges for `seconds`; call repeatedly while the operator moves the arm. */
  | { step: "range"; seconds: number };

export const scanDevices = () => get<DeviceScan>("/api/v1/devices/scan");
export const calibrateArm = (
  request: { role: string; port?: string; serial?: string; name?: string } & CalibrationStep,
) => post("/api/v1/devices/calibrate", request);
export const importCalibration = (name: string, content: string) =>
  post("/api/v1/devices/import-calibration", { name, content });
export const takeSnapshot = (device: string, serial?: string) =>
  post<{ jpeg_base64?: string }>("/api/v1/devices/snapshot", { device, serial });
/** The operator moves only the leader for `seconds`; the backend reports which port moved. */
export const identifyLeader = (ports: (string | undefined)[], seconds: number) =>
  post<IdentifyResult>("/api/v1/devices/identify", { ports, seconds });
