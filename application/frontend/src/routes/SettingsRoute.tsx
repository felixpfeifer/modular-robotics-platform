import { SettingsPage } from "../pages/SettingsPage";
import { useWorkspace } from "../workspace/WorkspaceContext";

export function Component() {
  const { status, run } = useWorkspace();
  return <SettingsPage settings={status.settings} run={run} />;
}
