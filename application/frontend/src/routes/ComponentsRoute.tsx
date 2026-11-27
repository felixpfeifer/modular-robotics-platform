import { CellSetupPage } from "../pages/CellSetupPage";
import { useWorkspace } from "../workspace/WorkspaceContext";

export function Component() {
  const { project, busy, run, setCellDirty } = useWorkspace();
  return <CellSetupPage project={project} busy={busy} run={run} onDirtyChange={setCellDirty} />;
}
