import { useNavigate } from "react-router";
import { pagePath } from "../navigation";
import { OverviewPage } from "../pages/OverviewPage";
import { useWorkspace } from "../workspace/WorkspaceContext";

export function Component() {
  const { project, sessions, workflow, status } = useWorkspace();
  const navigate = useNavigate();
  return (
    <OverviewPage
      project={project}
      sessions={sessions}
      go={(page) => void navigate(pagePath(page))}
      workflow={workflow}
      demo={status.mode === "demo"}
    />
  );
}
