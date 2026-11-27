import { TrainPage } from "../pages/TrainPage";
import { useWorkspace } from "../workspace/WorkspaceContext";

export function Component() {
  const { project, status, busy, run } = useWorkspace();
  return <TrainPage project={project} status={status} busy={busy} run={run} />;
}
