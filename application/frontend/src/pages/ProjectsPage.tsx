import { Add, DeleteOutline, EditOutlined } from "@mui/icons-material";
import { Box, Button, Card, CardContent, Chip, IconButton, Stack, Typography } from "@mui/material";
import type { Project } from "../types";
export function ProjectsPage({
  projects,
  projectId,
  selectProject,
  createProject,
  renameProject,
  deleteProject,
}: {
  projects: Project[];
  projectId: string;
  selectProject: (id: string) => void;
  createProject: () => void;
  renameProject: (project: Project) => void;
  deleteProject: (project: Project) => void;
}) {
  return (
    <Card>
      <CardContent>
        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={2}
          justifyContent="space-between"
          alignItems={{ xs: "flex-start", sm: "center" }}
        >
          <Box>
            <Typography variant="overline" color="primary">
              WORKSPACES
            </Typography>
            <Typography variant="h4">Projects</Typography>
            <Typography color="text.secondary">Choose the task workspace to operate.</Typography>
          </Box>
          <Button variant="contained" startIcon={<Add />} onClick={createProject}>
            New project
          </Button>
        </Stack>
        <Stack spacing={1.5} sx={{ mt: 3 }}>
          {projects.map((project) => (
            <Stack
              key={project.id}
              direction="row"
              alignItems="center"
              sx={{
                bgcolor: project.id === projectId ? "surface.active" : "white",
                border: "1px solid",
                borderRadius: 2,
                borderColor: project.id === projectId ? "primary.main" : "divider",
              }}
            >
              <Box
                component="button"
                type="button"
                sx={{
                  p: 2,
                  flex: 1,
                  minWidth: 0,
                  textAlign: "left",
                  bgcolor: "transparent",
                  border: 0,
                  font: "inherit",
                  color: "inherit",
                  cursor: "pointer",
                }}
                onClick={() => selectProject(project.id)}
              >
                <Stack direction="row" spacing={1} alignItems="center">
                  <Typography fontWeight={700} noWrap>
                    {project.name}
                  </Typography>
                  {project.id === projectId && <Chip size="small" color="success" label="Active" />}
                </Stack>
                <Typography variant="body2" color="text.secondary">
                  {project.cell_spec?.task_id?.replaceAll("_", " ") || "No task selected"} ·{" "}
                  {project.preset || "Unconfigured"}
                </Typography>
              </Box>
              <IconButton
                aria-label={`Rename ${project.name}`}
                onClick={() => renameProject(project)}
              >
                <EditOutlined fontSize="small" />
              </IconButton>
              <IconButton
                aria-label={`Delete ${project.name}`}
                color="error"
                sx={{ mr: 1 }}
                onClick={() => deleteProject(project)}
              >
                <DeleteOutline fontSize="small" />
              </IconButton>
            </Stack>
          ))}
          {!projects.length && (
            <Typography color="text.secondary" sx={{ py: 3, textAlign: "center" }}>
              No projects yet. Create one to get started.
            </Typography>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}
