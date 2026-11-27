import { CellPage } from "../pages/CellPage";
import { useWorkspace } from "../workspace/WorkspaceContext";

export function Component() {
  const { project, busy, run } = useWorkspace();
  return <CellPage project={project} busy={busy} run={run} />;
}
