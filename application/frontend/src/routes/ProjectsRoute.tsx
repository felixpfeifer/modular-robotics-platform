import { ProjectsPage } from "../pages/ProjectsPage";
import { useWorkspace } from "../workspace/WorkspaceContext";

export function Component() {
  const { status, projectId, selectProject, openDialog } = useWorkspace();
  return (
    <ProjectsPage
      projects={status.projects}
      projectId={projectId}
      selectProject={selectProject}
      createProject={() => openDialog({ kind: "create-project" })}
      renameProject={(project) => openDialog({ kind: "rename-project", project })}
      deleteProject={(project) => openDialog({ kind: "delete-project", project })}
    />
  );
}
