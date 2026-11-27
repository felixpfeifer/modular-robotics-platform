import { useState } from "react";
import { Alert, Button, Chip, Link, Stack, Typography } from "@mui/material";
import { listHubRepos } from "../api";
import type { HubRepo } from "../types";

export const formatSize = (bytes: number) =>
  bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(bytes / 1e6))} MB`;

/** Lists the signed-in user's Hub models or datasets (needs the token saved in Settings). */
export function HubBrowser({
  kind,
  runtime,
  tokenSet,
  action,
}: {
  kind: "models" | "datasets";
  runtime?: string;
  tokenSet: boolean;
  action?: { label: string; run: (repo: HubRepo) => void; disabled?: boolean };
}) {
  const [items, setItems] = useState<HubRepo[] | undefined>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const load = () => {
    setLoading(true);
    setError("");
    listHubRepos(kind, runtime)
      .then((result) => setItems(result.items))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  };
  return (
    <Stack spacing={1}>
      <Stack direction="row" spacing={1} alignItems="center">
        <Button size="small" variant="outlined" disabled={!tokenSet || loading} onClick={load}>
          {items ? "Refresh" : `Browse my Hub ${kind}`}
        </Button>
        {!tokenSet && (
          <Typography variant="caption" color="text.secondary">
            Save a Hugging Face token in Settings first.
          </Typography>
        )}
      </Stack>
      {error && <Alert severity="error">{error}</Alert>}
      {items && !items.length && (
        <Typography variant="body2" color="text.secondary">
          Nothing found for this account.
        </Typography>
      )}
      {items?.map((repo) => (
        <Stack
          key={repo.repo_id}
          direction="row"
          spacing={1.5}
          alignItems="center"
          sx={{ py: 0.75, borderTop: "1px solid", borderColor: "divider" }}
        >
          <Stack sx={{ flex: 1, minWidth: 0 }}>
            <Link
              href={`https://huggingface.co/${kind === "datasets" ? "datasets/" : ""}${repo.repo_id}`}
              target="_blank"
              rel="noopener noreferrer"
              fontWeight={650}
              noWrap
            >
              {repo.repo_id}
            </Link>
            <Typography variant="caption" color="text.secondary">
              {repo.size ? formatSize(repo.size) : "size unknown"}
              {repo.updated ? ` · ${new Date(repo.updated).toLocaleDateString()}` : ""}
            </Typography>
          </Stack>
          {repo.private && <Chip size="small" label="private" />}
          {repo.runtime && repo.runtime !== "other" && <Chip size="small" label={repo.runtime} />}
          {action && (
            <Button size="small" disabled={action.disabled} onClick={() => action.run(repo)}>
              {action.label}
            </Button>
          )}
        </Stack>
      ))}
    </Stack>
  );
}
