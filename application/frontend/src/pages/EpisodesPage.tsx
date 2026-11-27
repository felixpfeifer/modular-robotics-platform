import { useMemo, useState } from "react";
import {
  CloseOutlined,
  DeleteOutline,
  FileDownloadOutlined,
  VideocamOutlined,
} from "@mui/icons-material";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Drawer,
  IconButton,
  InputAdornment,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { errorMessage, urls, useEpisode } from "../api";
import { ValidationVerdict } from "../components/ValidationVerdict";
import { formatBytes, formatDuration, formatStarted } from "../lib/format";
import type { Episode, EpisodeDetail, Project } from "../types";

const statusColor = (status: string) =>
  status === "accepted"
    ? "success"
    : status === "rejected" || status === "failed"
      ? "error"
      : "default";

function Detail({
  id,
  busy,
  onClose,
  onDelete,
}: {
  id: string;
  busy: boolean;
  onClose: () => void;
  onDelete: (episode: EpisodeDetail) => void;
}) {
  const query = useEpisode(id);
  const detail = query.data;
  const error = query.error && errorMessage(query.error, "Could not load episode");
  return (
    <Box sx={{ width: { xs: "100vw", sm: 520 }, p: 3 }} role="region" aria-label="Episode details">
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Box>
          <Typography variant="overline" color="primary">
            EPISODE
          </Typography>
          <Typography variant="h6" sx={{ fontFamily: "monospace", fontSize: 16 }}>
            {id}
          </Typography>
        </Box>
        <IconButton aria-label="Close details" onClick={onClose}>
          <CloseOutlined />
        </IconButton>
      </Stack>
      {error && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {error}
        </Alert>
      )}
      {!detail && !error && (
        <Stack alignItems="center" sx={{ py: 6 }}>
          <CircularProgress />
        </Stack>
      )}
      {detail && (
        <Stack spacing={2.5} sx={{ mt: 2 }}>
          <Stack direction="row" gap={1} flexWrap="wrap">
            <Chip size="small" color={statusColor(detail.status)} label={detail.status} />
            {detail.project_name && (
              <Chip size="small" variant="outlined" label={detail.project_name} />
            )}
            {detail.manifest.task_id && (
              <Chip
                size="small"
                variant="outlined"
                label={detail.manifest.task_id.replaceAll("_", " ")}
              />
            )}
          </Stack>
          <ValidationVerdict status={detail.status} validation={detail.validation} />
          <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 2 }}>
            {[
              ["Started", formatStarted(detail.manifest.started_ns)],
              ["Duration", formatDuration(detail.mcap?.duration_s)],
              ["Messages", detail.mcap?.message_count?.toLocaleString() ?? "—"],
              ["Size on disk", formatBytes(detail.size_bytes)],
            ].map(([label, value]) => (
              <Box key={label}>
                <Typography variant="caption" color="text.secondary">
                  {label}
                </Typography>
                <Typography fontWeight={650}>{value}</Typography>
              </Box>
            ))}
          </Box>
          <Stack direction="row" spacing={1}>
            <Button
              component="a"
              variant="outlined"
              startIcon={<FileDownloadOutlined />}
              href={urls.episodeRecording(id)}
              disabled={!detail.mcap}
            >
              Download MCAP
            </Button>
            <Button
              color="error"
              startIcon={<DeleteOutline />}
              disabled={busy}
              onClick={() => onDelete(detail)}
            >
              Delete recording
            </Button>
          </Stack>
          <Box>
            <Typography variant="subtitle2">Recorded topics</Typography>
            {detail.mcap_error && (
              <Alert severity="warning" sx={{ mt: 1 }}>
                {detail.mcap_error}
              </Alert>
            )}
            {detail.mcap && !detail.mcap.has_summary && (
              <Alert severity="info" sx={{ mt: 1 }}>
                This MCAP has no summary index, so topics cannot be listed without scanning the
                whole file.
              </Alert>
            )}
            {detail.mcap && detail.mcap.topics.length > 0 && (
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>TOPIC</TableCell>
                      <TableCell>TYPE</TableCell>
                      <TableCell align="right">MSGS</TableCell>
                      <TableCell align="right">HZ</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {detail.mcap.topics.map((topic) => (
                      <TableRow key={topic.topic}>
                        <TableCell sx={{ fontFamily: "monospace", fontSize: 12 }}>
                          {topic.topic}
                        </TableCell>
                        <TableCell sx={{ fontFamily: "monospace", fontSize: 11 }}>
                          {topic.type || "—"}
                        </TableCell>
                        <TableCell align="right">
                          {topic.messages?.toLocaleString() ?? "—"}
                        </TableCell>
                        <TableCell align="right">
                          {topic.messages != null && detail.mcap?.duration_s
                            ? (topic.messages / detail.mcap.duration_s).toFixed(1)
                            : "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </Box>
          {detail.annotations && detail.annotations.length > 0 && (
            <Box>
              <Typography variant="subtitle2">Annotations</Typography>
              {detail.annotations.map((note) => (
                <Typography key={note.time} variant="body2" sx={{ mt: 0.5 }}>
                  {new Date(note.time * 1000).toLocaleTimeString()} · {note.text}
                </Typography>
              ))}
            </Box>
          )}
          <Box>
            <Typography variant="subtitle2">Validation</Typography>
            {detail.validation ? (
              <Box
                component="pre"
                sx={{
                  mt: 1,
                  p: 1.5,
                  bgcolor: "surface.subtle",
                  borderRadius: 2,
                  fontSize: 12,
                  overflow: "auto",
                  maxHeight: 280,
                }}
              >
                {JSON.stringify(detail.validation, null, 2)}
              </Box>
            ) : (
              <Typography variant="body2" color="text.secondary">
                No validation report yet.
              </Typography>
            )}
          </Box>
        </Stack>
      )}
    </Box>
  );
}

export function EpisodesPage({
  episodes,
  projects,
  projectId,
  busy,
  deleteEpisode,
  mode,
}: {
  episodes: Episode[];
  projects: Project[];
  projectId: string;
  busy: boolean;
  deleteEpisode: (episode: Episode) => void;
  mode?: "demo" | "ros";
}) {
  const [scope, setScope] = useState<"project" | "all">("project");
  const [status, setStatus] = useState("all");
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const statuses = useMemo(() => [...new Set(episodes.map((e) => e.status))].sort(), [episodes]);
  const visible = episodes.filter(
    (episode) =>
      (scope === "all" || episode.project_id === projectId) &&
      (status === "all" || episode.status === status) &&
      (!query ||
        episode.id.includes(query.trim().toLowerCase()) ||
        (episode.manifest.task_id || "").includes(query.trim().toLowerCase())),
  );
  const total = visible.reduce((sum, episode) => sum + (episode.size_bytes || 0), 0);
  const nameOf = (episode: Episode) =>
    episode.project_name || projects.find((p) => p.id === episode.project_id)?.name || "No project";
  return (
    <Stack spacing={2}>
      <Box>
        <Typography variant="overline" color="primary">
          LIBRARY
        </Typography>
        <Typography variant="h4">Recorded episodes</Typography>
        <Typography color="text.secondary" sx={{ mt: 1 }}>
          MCAP episodes written by the ROS 2 recorder. Open one to see its topics, message rates and
          validation, download the raw file, or delete it.
        </Typography>
      </Box>
      <Card>
        <CardContent>
          <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} sx={{ mb: 2 }}>
            <TextField
              select
              size="small"
              label="Show"
              value={scope}
              sx={{ minWidth: 170 }}
              onChange={(event) => setScope(event.target.value as "project" | "all")}
            >
              <MenuItem value="project">Active project</MenuItem>
              <MenuItem value="all">All projects</MenuItem>
            </TextField>
            <TextField
              select
              size="small"
              label="Status"
              value={status}
              sx={{ minWidth: 150 }}
              onChange={(event) => setStatus(event.target.value)}
            >
              <MenuItem value="all">Any status</MenuItem>
              {statuses.map((value) => (
                <MenuItem key={value} value={value}>
                  {value}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              size="small"
              label="Search ID or task"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              sx={{ flex: 1 }}
              slotProps={{
                input: {
                  endAdornment: <InputAdornment position="end">{visible.length}</InputAdornment>,
                },
              }}
            />
          </Stack>
          <TableContainer>
            <Table sx={{ minWidth: 640 }}>
              <TableHead>
                <TableRow>
                  <TableCell>EPISODE</TableCell>
                  <TableCell>STARTED</TableCell>
                  <TableCell>PROJECT</TableCell>
                  <TableCell>TASK</TableCell>
                  <TableCell>STATUS</TableCell>
                  <TableCell align="right">SIZE</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {visible.map((episode) => (
                  <TableRow
                    key={episode.id}
                    hover
                    selected={episode.id === openId}
                    sx={{ cursor: "pointer" }}
                    onClick={() => setOpenId(episode.id)}
                  >
                    <TableCell>
                      <Button
                        size="small"
                        sx={{ fontFamily: "monospace", p: 0, minWidth: 0 }}
                        aria-label={`Open episode ${episode.id}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          setOpenId(episode.id);
                        }}
                      >
                        {episode.id.slice(0, 8)}
                      </Button>
                    </TableCell>
                    <TableCell>{formatStarted(episode.manifest.started_ns)}</TableCell>
                    <TableCell>{nameOf(episode)}</TableCell>
                    <TableCell>{episode.manifest.task_id?.replaceAll("_", " ") || "—"}</TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        color={statusColor(episode.status)}
                        label={episode.status}
                      />
                    </TableCell>
                    <TableCell align="right">{formatBytes(episode.size_bytes)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
          {!visible.length && (
            <Box
              sx={{ textAlign: "center", py: 5, bgcolor: "surface.subtle", borderRadius: 2, mt: 2 }}
            >
              <VideocamOutlined sx={{ color: "surface.placeholder", fontSize: 32 }} />
              <Typography fontWeight={650} sx={{ mt: 1 }}>
                No recorded episodes here
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {episodes.length
                  ? "Change the filters to see other episodes."
                  : mode === "demo"
                    ? "Demo runtime writes no recordings. Episodes appear here when the ROS recorder writes an MCAP."
                    : "Episodes appear once the recorder has written an MCAP to its dataset folder."}
              </Typography>
            </Box>
          )}
          {visible.length > 0 && (
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1.5, display: "block" }}>
              {visible.length} episode(s) · {formatBytes(total)} on disk
            </Typography>
          )}
        </CardContent>
      </Card>
      <Drawer anchor="right" open={Boolean(openId)} onClose={() => setOpenId(null)}>
        {openId && (
          <Detail
            id={openId}
            busy={busy}
            onClose={() => setOpenId(null)}
            onDelete={(episode) => {
              setOpenId(null);
              deleteEpisode(episode);
            }}
          />
        )}
      </Drawer>
    </Stack>
  );
}
