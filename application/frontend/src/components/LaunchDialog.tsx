import { useRef, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { getLaunchCommand } from "../api";
import type { LaunchCommand, LaunchRequest } from "../types";

/** Shows the `docker run` for a remote host; the token is only included on explicit request. */
export function LaunchDialog({
  open,
  onClose,
  request,
}: {
  open: boolean;
  onClose: () => void;
  request: LaunchRequest;
}) {
  const [withToken, setWithToken] = useState(false);
  const [image, setImage] = useState("");
  const [result, setResult] = useState<LaunchCommand | undefined>();
  const [error, setError] = useState("");
  const requestId = useRef(0);
  const build = (include: boolean, imageName = image) => {
    const current = ++requestId.current;
    setError("");
    getLaunchCommand({
      ...request,
      image: imageName.trim() || undefined,
      target: request.target && request.target !== "local" ? request.target : undefined,
      include_token: include,
      confirm_token: include,
    })
      .then((response) => {
        if (current === requestId.current) setResult(response);
      })
      .catch((e: Error) => {
        if (current !== requestId.current) return;
        setResult(undefined);
        setError(e.message);
      });
  };
  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      slotProps={{
        transition: {
          onEnter: () => {
            setWithToken(false);
            setImage("");
            build(false, "");
          },
        },
      }}
    >
      <DialogTitle>Command for the remote host</DialogTitle>
      <DialogContent>
        <Stack spacing={1.5}>
          <TextField
            label="Docker Hub image"
            placeholder="namespace/image:tag"
            value={image}
            onChange={(event) => {
              requestId.current++;
              setImage(event.target.value);
              setResult(undefined);
            }}
            onBlur={() => build(withToken)}
            helperText="Optional. The image must support the selected runtime's command."
            size="small"
          />
          {error && <Alert severity="error">{error}</Alert>}
          {result && (
            <>
              <Typography
                component="pre"
                variant="body2"
                sx={{
                  p: 1.5,
                  bgcolor: "action.hover",
                  borderRadius: 1,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-all",
                }}
              >
                {result.command}
              </Typography>
              {result.notes.map((note) => (
                <Typography key={note} variant="caption" color="text.secondary">
                  {note}
                </Typography>
              ))}
            </>
          )}
          <FormControlLabel
            label="Write my token into the command (it will be visible in shell history)"
            control={
              <Checkbox
                checked={withToken}
                onChange={(_, on) => {
                  setWithToken(on);
                  build(on);
                }}
              />
            }
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button
          disabled={!result}
          onClick={() => result && void navigator.clipboard?.writeText(result.command)}
        >
          Copy
        </Button>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
