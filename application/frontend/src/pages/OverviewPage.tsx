import {
  ArrowForward,
  CheckCircleOutline,
  FolderOpenOutlined,
  PlayArrow,
  VideocamOutlined,
} from "@mui/icons-material";
import { Box, Button, Card, CardContent, Chip, Stack, Typography } from "@mui/material";
import { PipelineStepper } from "../components/PipelineStepper";
import type { Page, Project, Session, Workflow } from "../types";
export function OverviewPage({
  project,
  sessions,
  go,
  workflow,
  demo,
}: {
  project?: Project;
  sessions: Session[];
  go: (page: Page) => void;
  workflow?: Workflow | null;
  demo?: boolean;
}) {
  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="overline" color="primary">
          YOUR WORKSPACE
        </Typography>
        <Typography variant="h4" sx={{ mt: 0.5 }}>
          Welcome to MRP Studio
        </Typography>
        <Typography color="text.secondary" sx={{ mt: 1 }}>
          Your workspace for collecting robot demonstrations.
        </Typography>
      </Box>
      <Card
        sx={{
          bgcolor: "hero.background",
          color: "white",
          position: "relative",
          overflow: "hidden",
          "&:after": {
            content: '""',
            position: "absolute",
            width: 330,
            height: 330,
            border: "1px solid rgba(255,255,255,.12)",
            borderRadius: "50%",
            right: -50,
            top: -140,
            boxShadow: "0 0 0 45px rgba(255,255,255,.025), 0 0 0 90px rgba(255,255,255,.025)",
          },
        }}
      >
        <CardContent sx={{ position: "relative", zIndex: 1, py: 4 }}>
          <Typography variant="overline" sx={{ color: "hero.overline" }}>
            ACTIVE PROJECT
          </Typography>
          <Typography variant="h4" sx={{ mt: 1 }}>
            {project?.name || "Start with a project"}
          </Typography>
          <Typography sx={{ color: "hero.text", mt: 1, maxWidth: 480 }}>
            {project
              ? "Capture demonstrations, review your recordings, and build datasets from one place."
              : "Create a project to organize your demonstrations and get started."}
          </Typography>
          <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mt: 3 }}>
            <Button
              variant="contained"
              startIcon={project ? <PlayArrow /> : <FolderOpenOutlined />}
              onClick={() => go(project ? "record" : "projects")}
              sx={{
                bgcolor: "hero.action",
                color: "hero.actionText",
                "&:hover": { bgcolor: "hero.actionHover" },
              }}
            >
              {project ? "Open recording studio" : "Go to projects"}
            </Button>
            <Button onClick={() => go("projects")} sx={{ color: "white" }}>
              Manage projects <ArrowForward sx={{ ml: 1, fontSize: 16 }} />
            </Button>
          </Stack>
        </CardContent>
      </Card>
      {workflow?.stages?.length ? (
        <PipelineStepper stages={workflow.stages} go={go} demo={demo} />
      ) : null}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
        {[
          {
            icon: <VideocamOutlined />,
            label: "TOTAL SESSIONS",
            value: sessions.length,
            detail: "In this project",
          },
          {
            icon: <CheckCircleOutline />,
            label: "PROJECT TASK",
            value: project?.cell_spec?.task_id?.replaceAll("_", " ") || "Not configured",
            detail: project?.preset || "No preset selected",
          },
        ].map((item) => (
          <Card key={item.label} sx={{ flex: 1 }}>
            <CardContent>
              <Stack direction="row" justifyContent="space-between">
                <Typography variant="overline" color="text.secondary" sx={{ fontSize: 10 }}>
                  {item.label}
                </Typography>
                <Box sx={{ color: "primary.main" }}>{item.icon}</Box>
              </Stack>
              <Typography variant="h6" sx={{ mt: 1, textTransform: "capitalize" }}>
                {item.value}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {item.detail}
              </Typography>
            </CardContent>
          </Card>
        ))}
      </Stack>
      <Card>
        <CardContent>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Box>
              <Typography variant="h6">Recent sessions</Typography>
              <Typography variant="body2" color="text.secondary">
                Recording activity for your active project
              </Typography>
            </Box>
            <Button size="small" endIcon={<ArrowForward />} onClick={() => go("record")}>
              Record
            </Button>
          </Stack>
          {sessions.length ? (
            <Stack sx={{ mt: 2 }}>
              {sessions.slice(0, 5).map((session) => (
                <Stack
                  key={session.id}
                  direction="row"
                  alignItems="center"
                  spacing={2}
                  sx={{ py: 1.5, borderTop: "1px solid", borderColor: "divider" }}
                >
                  <Box
                    sx={{
                      width: 40,
                      height: 40,
                      borderRadius: 2,
                      bgcolor: "primary.light",
                      display: "grid",
                      placeItems: "center",
                      color: "primary.main",
                    }}
                  >
                    <VideocamOutlined fontSize="small" />
                  </Box>
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography fontWeight={650} sx={{ textTransform: "capitalize" }}>
                      {session.snapshot.task_id?.replaceAll("_", " ") || "Episode"}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {session.id}
                    </Typography>
                  </Box>
                  <Chip label={session.state.replaceAll("_", " ")} size="small" />
                </Stack>
              ))}
            </Stack>
          ) : (
            <Box
              sx={{ textAlign: "center", py: 5, mt: 2, bgcolor: "surface.subtle", borderRadius: 2 }}
            >
              <VideocamOutlined sx={{ color: "surface.placeholder", fontSize: 32 }} />
              <Typography fontWeight={650} sx={{ mt: 1 }}>
                No sessions yet
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Your recordings will appear here once you get started.
              </Typography>
            </Box>
          )}
        </CardContent>
      </Card>
    </Stack>
  );
}
