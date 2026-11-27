import type { CellLayout, CellSpec, Project, TestResult, Workflow } from "../types";
import { get, path, post } from "./client";

export const createProject = (name: string) => post<Project>("/api/v1/projects", { name });
export const renameProject = (id: string, name: string) =>
  post(path`/api/v1/projects/${id}/rename`, { name });
export const deleteProject = (id: string) =>
  post(path`/api/v1/projects/${id}/delete`, { confirm: true });
export const getWorkflow = (id: string) => get<Workflow>(path`/api/v1/projects/${id}/workflow`);
export const saveLayout = (id: string, layout: CellLayout) =>
  post(path`/api/v1/projects/${id}/layout`, { layout });
export const saveCell = (id: string, cell: CellSpec) =>
  post(path`/api/v1/projects/${id}/cell`, { cell });
export const testCell = (id: string) => post<TestResult>(path`/api/v1/projects/${id}/cell/test`);
