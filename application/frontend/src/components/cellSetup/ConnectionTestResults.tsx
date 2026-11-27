import { Alert, Box, Button, Chip, Stack } from "@mui/material";
import type { TestCheck, TestResult } from "../../types";

const CHIP_COLOR = { ok: "success", warn: "warning", error: "error" } as const;

/** Outcome of the cell connection test, with a one-click fix for cameras below their target fps. */
export function ConnectionTestResults({
  test,
  onUseFps,
}: {
  test: TestResult;
  onUseFps: (check: TestCheck, fps: number) => void;
}) {
  return (
    <Stack spacing={1}>
      <Alert severity={test.passed ? "success" : "error"}>
        {test.passed
          ? "All checks passed. You can start the cell from the Record page within 10 minutes."
          : "Some checks failed. Fix them and run the test again."}
      </Alert>
      <Stack direction="row" flexWrap="wrap" gap={1}>
        {test.checks.map((check) => (
          <Chip
            key={check.name}
            color={CHIP_COLOR[check.level]}
            label={`${check.name}: ${check.detail}`}
          />
        ))}
      </Stack>
      {test.checks
        .filter((check) => !check.ok && check.measured_fps && check.role)
        .map((check) => (
          <Alert
            key={check.name}
            severity="warning"
            action={
              <Button
                color="inherit"
                size="small"
                onClick={() => onUseFps(check, Math.floor(check.measured_fps as number))}
              >
                Use {Math.floor(check.measured_fps as number)} fps
              </Button>
            }
          >
            {check.name}: the camera delivers {check.measured_fps} fps, below the configured{" "}
            {check.target_fps}. Brighter light often helps; otherwise record at the rate it can
            hold.
          </Alert>
        ))}
      {test.checks.map(
        (check) =>
          check.jpeg_base64 && (
            <Box
              key={check.name}
              component="img"
              alt="Camera test snapshot"
              src={`data:image/jpeg;base64,${check.jpeg_base64}`}
              sx={{ maxWidth: 320, borderRadius: 1 }}
            />
          ),
      )}
    </Stack>
  );
}
