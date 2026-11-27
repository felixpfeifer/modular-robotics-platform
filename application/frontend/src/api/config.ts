import type { Backup, BundleReport } from "../types";
import { get, path, post, upload, withQuery } from "./client";

const GZIP = "application/gzip";

export const listBackups = () => get<{ backups?: Backup[] }>("/api/v1/config/backups");
export const createBackup = () => post("/api/v1/config/export");
export const deleteBackup = (name: string) => post(path`/api/v1/config/backups/${name}/delete`);
/** Checks a bundle without changing anything. */
export const validateBundle = (file: Blob) =>
  upload<BundleReport>("/api/v1/config/validate", file, GZIP);
export const importBundle = (file: Blob, overwriteCalibrations: boolean) =>
  upload<BundleReport>(
    withQuery("/api/v1/config/import", { overwrite_calibrations: overwriteCalibrations }),
    file,
    GZIP,
  );
