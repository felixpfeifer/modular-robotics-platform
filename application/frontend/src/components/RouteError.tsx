import { isRouteErrorResponse, useRouteError } from "react-router";
import { Alert, Button, Stack, Typography } from "@mui/material";

function describe(error: unknown) {
  if (isRouteErrorResponse(error)) return `${error.status} ${error.statusText}`;
  return error instanceof Error ? error.message : "Unknown error";
}

/** Shown in place of a page that crashed while rendering; the sidebar keeps working. */
export function PageError() {
  const error = useRouteError();
  return (
    <Alert
      severity="error"
      action={
        <Button color="inherit" size="small" onClick={() => window.location.reload()}>
          Reload
        </Button>
      }
    >
      This page failed to load: {describe(error)}
    </Alert>
  );
}

/** Last resort when the workspace shell itself crashed. */
export function AppError() {
  const error = useRouteError();
  return (
    <Stack alignItems="center" spacing={2} sx={{ py: 12, px: 2, textAlign: "center" }}>
      <Typography variant="h6">MRP Studio stopped working</Typography>
      <Typography color="text.secondary">{describe(error)}</Typography>
      <Button variant="outlined" onClick={() => window.location.reload()}>
        Reload
      </Button>
    </Stack>
  );
}
