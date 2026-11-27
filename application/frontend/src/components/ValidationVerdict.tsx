import { Alert, AlertTitle, Box, Stack, Typography } from "@mui/material";
import { explain, parseVerdict } from "../lib/validation";

/** Why an episode was rejected, in plain language, with what to do about it. */
export function ValidationVerdict({ status, validation }: { status: string; validation: unknown }) {
  const verdict = parseVerdict(validation);
  if (status === "accepted")
    return (
      <Alert severity="success">
        Accepted: all checks passed
        {verdict.warnings.length > 0 ? ` (${verdict.warnings.length} advisory notes)` : ""}.
      </Alert>
    );
  if (!verdict.checked)
    return <Alert severity="info">Validation results are not available yet.</Alert>;
  if (verdict.errors.length === 0)
    return (
      <Alert severity={status === "rejected" ? "warning" : "info"}>
        {status === "rejected"
          ? "Rejected, but no failing check was recorded. Open the validation report for details."
          : `Status: ${status}.`}
      </Alert>
    );
  return (
    <Alert severity="error">
      <AlertTitle>
        Rejected: {verdict.errors.length} check{verdict.errors.length === 1 ? "" : "s"} failed
      </AlertTitle>
      <Stack spacing={1.5}>
        {verdict.errors.map((finding) => {
          const hint = explain(finding.rule_id, finding.summary);
          return (
            <Box key={finding.rule_id}>
              <Typography fontWeight={700}>{hint.title}</Typography>
              <Typography variant="body2">{hint.why}</Typography>
              {hint.showDetail && (
                <Typography variant="body2" sx={{ fontFamily: "monospace" }}>
                  {finding.summary}
                </Typography>
              )}
              <Typography variant="body2" sx={{ mt: 0.5 }}>
                <strong>What to do:</strong> {hint.fix}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {finding.rule_id}
              </Typography>
            </Box>
          );
        })}
      </Stack>
    </Alert>
  );
}
