import { createContext, useContext } from "react";
import type { Episode, Project, RunAction, Session, Status, Workflow } from "../types";
import type { WorkspaceDialog } from "./ProjectDialogs";
import type { RecordAction } from "./useRunAction";

/** What every page shares: live backend state, the active project and the action runner. */
export type Workspace = {
  status: Status;
  episodes: Episode[];
  workflow: Workflow | null;
  projectId: string;
  project?: Project;
  /** Sessions of the active project. */
  sessions: Session[];
  selectProject: (id: string) => void;
  run: RunAction;
  runRecord: (action: RecordAction, work: () => Promise<unknown>, message: string) => Promise<void>;
  busy: boolean;
  recordAction: RecordAction | null;
  refresh: () => Promise<void>;
  openDialog: (dialog: WorkspaceDialog) => void;
  /** The Components page reports unsaved edits so leaving it can be confirmed. */
  setCellDirty: (dirty: boolean) => void;
  /** Accepted episodes picked for the next dataset export, per project. */
  selectedEpisodes: Set<string>;
  toggleEpisode: (id: string) => void;
};

export const WorkspaceContext = createContext<Workspace | null>(null);

export function useWorkspace(): Workspace {
  const workspace = useContext(WorkspaceContext);
  if (!workspace) throw new Error("useWorkspace must be used inside the workspace layout");
  return workspace;
}
