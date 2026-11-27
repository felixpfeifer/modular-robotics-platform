import { RobotTelemetryProvider } from "../components/RobotTelemetryProvider";
import { DeployPage } from "../pages/DeployPage";
import { useWorkspace } from "../workspace/WorkspaceContext";

export function Component() {
  const { project, status, busy, run } = useWorkspace();
  return (
    <RobotTelemetryProvider>
      <DeployPage project={project} status={status} busy={busy} run={run} />
    </RobotTelemetryProvider>
  );
}
