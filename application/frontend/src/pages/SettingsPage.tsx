import { useState } from "react";
import {
  Button,
  Card,
  CardContent,
  Chip,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { clearHubToken, deleteTarget, saveHubSettings, saveTarget } from "../api";
import { ConfigBackupCard } from "../components/ConfigBackupCard";
import type { RunAction, Settings, Target } from "../types";
const SCHEMES: Record<string, string> = {
  groot: "tcp://host:5555",
  lerobot_async: "grpc://host:8080",
  lerobot_act: "http://host:8092",
};

function TargetsCard({ settings, run }: { settings: Settings; run: RunAction }) {
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [runtime, setRuntime] = useState("groot");
  const [url, setUrl] = useState("");
  const [mode, setMode] = useState<Target["token_mode"]>("saved");
  const [token, setToken] = useState("");
  return (
    <Card sx={{ mt: 2 }}>
      <CardContent>
        <Typography variant="h6">Remote policy servers</Typography>
        <Typography color="text.secondary" sx={{ mt: 1 }}>
          Servers you start yourself, for example GR00T on a GPU machine. The app connects to the
          URL; the container downloads its checkpoint from the Hub with the token chosen here. These
          servers have no authentication: use an SSH tunnel or VPN address.
        </Typography>
        <Stack sx={{ mt: 2 }}>
          {(settings.targets ?? []).map((t) => (
            <Stack
              key={t.id}
              direction="row"
              spacing={1.5}
              alignItems="center"
              sx={{ py: 1, borderTop: "1px solid", borderColor: "divider" }}
            >
              <Stack sx={{ flex: 1, minWidth: 0 }}>
                <Typography fontWeight={650} noWrap>
                  {t.name}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {t.runtime} · {t.url}
                </Typography>
              </Stack>
              <Chip
                size="small"
                label={
                  t.token_mode === "own"
                    ? "own token"
                    : t.token_mode === "saved"
                      ? "saved token"
                      : "no token"
                }
              />
              <Button
                color="error"
                size="small"
                onClick={() => void run(() => deleteTarget(t.id), "Target removed.")}
              >
                Remove
              </Button>
            </Stack>
          ))}
        </Stack>
        <Stack spacing={1.5} sx={{ mt: 2, maxWidth: 540 }}>
          <Stack direction="row" spacing={1.5}>
            <TextField
              size="small"
              label="Id"
              value={id}
              placeholder="gpu-box"
              onChange={(e) => setId(e.target.value.toLowerCase())}
            />
            <TextField
              size="small"
              fullWidth
              label="Name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Stack>
          <TextField
            select
            size="small"
            label="Container"
            value={runtime}
            onChange={(e) => setRuntime(e.target.value)}
          >
            <MenuItem value="groot">NVIDIA GR00T</MenuItem>
            <MenuItem value="lerobot_async">LeRobot async policy server</MenuItem>
            <MenuItem value="lerobot_act">LeRobot ACT (this app's image)</MenuItem>
          </TextField>
          <TextField
            size="small"
            label="Server URL"
            value={url}
            placeholder={SCHEMES[runtime]}
            onChange={(e) => setUrl(e.target.value)}
          />
          <TextField
            select
            size="small"
            label="Hugging Face token for this server"
            value={mode}
            onChange={(e) => setMode(e.target.value as Target["token_mode"])}
          >
            <MenuItem value="saved">Use the saved token</MenuItem>
            <MenuItem value="own">Use a token only for this server</MenuItem>
            <MenuItem value="none">No token (public models only)</MenuItem>
          </TextField>
          {mode === "own" && (
            <TextField
              size="small"
              type="password"
              autoComplete="off"
              label="Token for this server"
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
          )}
          <Button
            variant="contained"
            disabled={!id || !url}
            onClick={() =>
              void run(
                () =>
                  saveTarget({
                    id,
                    name: name || id,
                    runtime,
                    url,
                    token_mode: mode,
                    ...(mode === "own" && token ? { token } : {}),
                  }).then(() => {
                    setToken("");
                    setUrl("");
                    setId("");
                    setName("");
                  }),
                "Target saved.",
              )
            }
          >
            Save target
          </Button>
        </Stack>
      </CardContent>
    </Card>
  );
}

export function SettingsPage({ settings, run }: { settings: Settings; run: RunAction }) {
  const [token, setToken] = useState("");
  // Shows the saved namespace until the operator edits it; saving hands it back to the server.
  const [namespaceDraft, setNamespace] = useState<string | null>(null);
  const namespace = namespaceDraft ?? settings.hf_namespace;
  return (
    <>
      <Card>
        <CardContent>
          <Typography variant="h6">Hugging Face credentials</Typography>
          <Typography color="text.secondary" sx={{ mt: 1 }}>
            Tokens are write-only and encrypted by the backend before persistent storage.
          </Typography>
          <Stack spacing={2} sx={{ mt: 3, maxWidth: 540 }}>
            <TextField
              label="Access token"
              type="password"
              autoComplete="off"
              placeholder={
                settings.hf_token_set ? "A token is saved; leave blank to keep it" : "hf_…"
              }
              value={token}
              onChange={(event) => setToken(event.target.value)}
            />
            <TextField
              label="Default namespace"
              value={namespace}
              onChange={(event) => setNamespace(event.target.value)}
            />
            <Stack direction="row" spacing={1}>
              <Button
                variant="contained"
                onClick={() =>
                  void run(async () => {
                    await saveHubSettings({
                      hf_token: token || undefined,
                      hf_namespace: namespace,
                    });
                    setNamespace(null);
                  }, "Settings saved.")
                }
              >
                Save settings
              </Button>
              <Button
                color="error"
                onClick={() => void run(() => clearHubToken(), "Saved token removed.")}
              >
                Remove token
              </Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>
      <TargetsCard settings={settings} run={run} />
      <ConfigBackupCard run={run} />
    </>
  );
}
