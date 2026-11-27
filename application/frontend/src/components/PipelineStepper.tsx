import { ArrowForward, Check, Lock } from "@mui/icons-material";
import { Box, Button, Card, CardContent, Stack, Typography } from "@mui/material";
import type { Page, Stage } from "../types";

const target: Record<string, Page> = {
  setup: "cell",
  record: "record",
  dataset: "dataset",
  train: "train",
  deploy: "deploy",
};
const hint: Record<string, string> = {
  setup: "Describe the workspace",
  record: "Capture demonstrations",
  dataset: "Export accepted episodes",
  train: "Fit a policy (ACT)",
  deploy: "Run it on the cell",
};

export function PipelineStepper({
  stages,
  go,
  demo,
}: {
  stages: Stage[];
  go: (page: Page) => void;
  demo?: boolean;
}) {
  const next = stages.find((stage) => stage.state === "todo" || stage.state === "active");
  return (
    <Card>
      <CardContent>
        <Typography variant="h6">Pipeline</Typography>
        <Typography variant="body2" color="text.secondary">
          Configure the cell, record demonstrations, build a dataset, train a policy and run it.
          {demo && " The demo runtime covers the first two steps; the rest need the ROS runtime."}
        </Typography>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} sx={{ mt: 2 }}>
          {stages.map((stage, index) => {
            const blocked = stage.state === "blocked";
            const done = stage.state === "done";
            return (
              <Box
                key={stage.id}
                sx={{
                  flex: 1,
                  p: 2,
                  borderRadius: 2,
                  border: "1px solid",
                  borderColor: next?.id === stage.id ? "primary.main" : "divider",
                  bgcolor: done ? "surface.active" : blocked ? "surface.inactive" : "white",
                  opacity: blocked ? 0.75 : 1,
                }}
              >
                <Stack direction="row" alignItems="center" spacing={1}>
                  <Box
                    sx={{
                      width: 24,
                      height: 24,
                      borderRadius: "50%",
                      display: "grid",
                      placeItems: "center",
                      fontSize: 12,
                      fontWeight: 700,
                      bgcolor: done ? "primary.main" : "divider",
                      color: done ? "white" : "text.secondary",
                    }}
                  >
                    {done ? (
                      <Check sx={{ fontSize: 15 }} />
                    ) : blocked ? (
                      <Lock sx={{ fontSize: 13 }} />
                    ) : (
                      index + 1
                    )}
                  </Box>
                  <Typography fontWeight={700}>{stage.label}</Typography>
                </Stack>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1, minHeight: 20 }}>
                  {blocked ? stage.blocked_reason : stage.summary}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {hint[stage.id]}
                </Typography>
                <Box sx={{ mt: 1 }}>
                  <Button
                    size="small"
                    endIcon={<ArrowForward />}
                    variant={next?.id === stage.id ? "contained" : "text"}
                    onClick={() => go(target[stage.id] ?? "overview")}
                  >
                    {done ? "Open" : blocked ? "Preview" : "Go"}
                  </Button>
                </Box>
              </Box>
            );
          })}
        </Stack>
      </CardContent>
    </Card>
  );
}
