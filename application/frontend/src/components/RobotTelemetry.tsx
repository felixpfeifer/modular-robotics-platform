import { memo, useEffect, useId, useMemo, useState } from "react";
import {
  Box,
  Button,
  Chip,
  MenuItem,
  Slider,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { RobotSample, Runtime } from "../types";
import { useRobotTelemetry } from "./RobotTelemetryProvider";

type Frame = { time: number; data: Runtime["robot_data"] };
type ChartRow = { time: number; values: (number | null)[] };
type Metric = "positions" | "velocities";
const streams = [
  { key: "Follower", label: "Measured" },
  { key: "Action", label: "Command" },
  { key: "Leader", label: "Leader" },
] as const;
type Stream = (typeof streams)[number]["key"];
const windows = [3000, 6000, 12000];
const HISTORY_MS = windows[windows.length - 1];
const colors = [
  "#087f8c",
  "#bb3750",
  "#3b5cc4",
  "#906415",
  "#7750a3",
  "#007241",
  "#ad461b",
  "#3d6a9d",
  "#9b456d",
  "#3f6940",
  "#6e5140",
  "#5141a0",
];
const dashes = [undefined, "7 3", "2 3", "7 3 2 3"];

function jointLabel(name: string) {
  return name
    .replace(/_joint$/, "")
    .replace(/[_-]+/g, " ")
    .replace(/^./, (char) => char.toUpperCase());
}

function value(sample: RobotSample | undefined, joint: string, metric: Metric) {
  if (!sample?.fresh) return null;
  const index = sample.joint_names.indexOf(joint);
  const result = sample[metric][index];
  return typeof result === "number" && Number.isFinite(result) ? result : null;
}

const JointChart = memo(function JointChart({
  rows,
  joints,
  metric,
  start,
  end,
}: {
  rows: ChartRow[];
  joints: string[];
  metric: Metric;
  start: number;
  end: number;
}) {
  return (
    <Box
      sx={{ height: { xs: 220, sm: 300 }, width: "100%", minWidth: 0 }}
      role="img"
      aria-label={`All joints ${metric === "positions" ? "position" : "velocity"} history`}
    >
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <LineChart data={rows} margin={{ top: 12, right: 12, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="time"
            type="number"
            domain={[start, end]}
            allowDataOverflow
            tickFormatter={(time: number) =>
              new Date(time).toLocaleTimeString([], { hour12: false })
            }
            minTickGap={35}
          />
          <YAxis width={56} tickFormatter={(position: number) => position.toFixed(2)} />
          <Tooltip
            labelFormatter={(time) =>
              new Date(Number(time)).toLocaleTimeString([], { hour12: false })
            }
            contentStyle={{ fontSize: 13 }}
          />
          {joints.map((joint, index) => (
            <Line
              key={joint}
              dataKey={`values[${index}]`}
              name={jointLabel(joint)}
              stroke={colors[index % colors.length]}
              strokeDasharray={dashes[Math.floor(index / colors.length) % dashes.length]}
              strokeWidth={2}
              dot={rows.length === 1}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </Box>
  );
});

export function RobotTelemetry({ runtime }: { runtime: Runtime }) {
  const sourceId = useId();
  const telemetry = useRobotTelemetry() ?? runtime;
  const robotData = telemetry.robot_data;
  const simulated = telemetry.robot_data_simulated === true;
  const displayStreams = streams.map((stream) => ({
    ...stream,
    label: simulated && stream.key === "Follower" ? "Follower" : stream.label,
  }));
  const [frames, setFrames] = useState<Frame[]>([]);
  const [pausedFrames, setPausedFrames] = useState<Frame[] | null>(null);
  const [chartSource, setChartSource] = useState<Stream>("Follower");
  const [zoom, setZoom] = useState(windows.length - 1);
  const [lookback, setLookback] = useState(0);
  const [metric, setMetric] = useState<Metric>("positions");
  const quantity = metric === "positions" ? "position" : "velocity";
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  // TODO: collect this history where samples arrive (RobotTelemetryProvider) instead of
  // re-deriving it from props in an effect; kept as is while that component is reworked.
  useEffect(() => {
    if (!runtime.cell_running) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- see the TODO above
      setFrames([]);
      setPausedFrames(null);
      setLookback(0);
      return;
    }
    if (!robotData) return;
    setFrames((previous) => {
      const last = previous.at(-1)?.data;
      if (
        streams.every(
          ({ key }) =>
            last?.[key]?.stamp_ns === robotData[key]?.stamp_ns &&
            last?.[key]?.fresh === robotData[key]?.fresh,
        )
      )
        return previous;
      const time = Date.now();
      return [
        ...previous.filter((frame) => time - frame.time <= HISTORY_MS),
        { time, data: robotData },
      ].slice(-240);
    });
  }, [robotData, runtime.cell_running]);
  const latest = frames.at(-1);
  const connected = runtime.cell_running && latest !== undefined && now - latest.time < 5000;
  const data = connected ? robotData : undefined;
  const displayFrames = pausedFrames ?? frames;
  const newestFirst = useMemo(() => [...displayFrames].reverse(), [displayFrames]);
  const chartStreams = displayStreams
    .map((stream) => ({
      ...stream,
      joints: newestFirst.find(({ data }) => data?.[stream.key]?.joint_names.length)?.data?.[
        stream.key
      ]?.joint_names,
    }))
    .filter(({ joints }) => joints?.length);
  const source = chartStreams.find(({ key }) => key === chartSource)?.key ?? chartStreams[0]?.key;
  const chartJoints = chartStreams.find(({ key }) => key === source)?.joints;
  const joints = [
    ...new Set([
      ...streams.flatMap(({ key }) => robotData?.[key]?.joint_names ?? []),
      ...chartStreams.flatMap(({ joints }) => joints ?? []),
    ]),
  ];
  const unit = simulated
    ? metric === "positions"
      ? "rad"
      : "rad/s"
    : metric === "positions"
      ? "rad / m"
      : "rad/s / m/s";
  const duration = windows[zoom];
  const latestTime = displayFrames.at(-1)?.time ?? now;
  const maxLookback = Math.max(0, latestTime - (displayFrames[0]?.time ?? latestTime) - duration);
  const end = latestTime - Math.min(lookback, maxLookback);
  const start = end - duration;
  // `chartJoints` is a stable array from the frame data, which the compiler cannot prove.
  /* eslint-disable react-hooks/preserve-manual-memoization */
  const rows = useMemo(() => {
    if (!source || !chartJoints) return [];
    return displayFrames.map((frame) => ({
      time: frame.time,
      // Index-based keys also work for joint names that contain path separators or dots.
      values: chartJoints.map((joint) => value(frame.data?.[source], joint, metric)),
    }));
  }, [chartJoints, displayFrames, metric, source]);
  /* eslint-enable react-hooks/preserve-manual-memoization */
  const followLive = () => {
    setPausedFrames(null);
    setLookback(0);
  };
  const changeZoom = (step: number) => {
    if (!pausedFrames) setPausedFrames(frames);
    setZoom((current) => current + step);
  };
  const formatValue = (result: number | null) =>
    result === null ? "Unavailable" : result.toFixed(3);
  return (
    <Box component="section" aria-label="Joint motion" sx={{ py: 1, minWidth: 0 }}>
      <Stack
        direction="row"
        spacing={1}
        useFlexGap
        flexWrap="wrap"
        alignItems="center"
        sx={{ mb: 2 }}
      >
        <Typography variant="h6" sx={{ mr: "auto" }}>
          {simulated ? "Simulated joint motion" : "Joint motion"}
        </Typography>
        <Chip size="small" label={`Source: ${runtime.active_source}`} />
        {displayStreams.map(({ key, label }) => (
          <Chip
            key={key}
            size="small"
            label={`${label}: ${data?.[key]?.fresh ? (simulated ? "Simulated" : "Live") : simulated && connected && key === "Action" && runtime.active_source === "none" ? "Inactive" : "Unavailable / stale"}`}
            color={data?.[key]?.fresh ? (simulated ? "info" : "success") : "default"}
          />
        ))}
      </Stack>
      {!joints.length ? (
        <Typography color="text.secondary">
          {runtime.cell_running ? "Waiting for joint readings." : "Joint readings offline."}
        </Typography>
      ) : (
        <>
          {source && chartJoints?.length ? (
            <Box sx={{ mb: 2 }}>
              <Stack
                direction="row"
                spacing={1}
                useFlexGap
                flexWrap="wrap"
                alignItems="center"
                sx={{ mb: 1 }}
              >
                <TextField
                  id={sourceId}
                  select
                  size="small"
                  label="Plot source"
                  value={source}
                  onChange={(event) => setChartSource(event.target.value as Stream)}
                  sx={{ minWidth: 132 }}
                >
                  {chartStreams.map(({ key, label }) => (
                    <MenuItem key={key} value={key}>
                      {label}
                    </MenuItem>
                  ))}
                </TextField>
                <ToggleButtonGroup
                  exclusive
                  size="small"
                  value={metric}
                  aria-label="Joint metric"
                  onChange={(_, next: Metric | null) => next && setMetric(next)}
                >
                  <ToggleButton value="positions">Position</ToggleButton>
                  <ToggleButton value="velocities">Velocity</ToggleButton>
                </ToggleButtonGroup>
                <Stack
                  direction="row"
                  spacing={0.5}
                  sx={{
                    ml: { sm: "auto" },
                    "& .MuiButton-root": { whiteSpace: "nowrap", minWidth: 0 },
                  }}
                >
                  <Button size="small" onClick={() => changeZoom(-1)} disabled={zoom === 0}>
                    Zoom in
                  </Button>
                  <Button
                    size="small"
                    onClick={() => changeZoom(1)}
                    disabled={zoom === windows.length - 1}
                  >
                    Zoom out
                  </Button>
                  <Button
                    size="small"
                    variant="outlined"
                    onClick={pausedFrames ? followLive : () => setPausedFrames(frames)}
                  >
                    {pausedFrames ? "Go live" : "Pause chart"}
                  </Button>
                </Stack>
              </Stack>
              <Typography variant="caption" color="text.secondary">
                {pausedFrames ? "Paused" : data?.[source]?.fresh ? "Live" : "Last readings"} ·{" "}
                {duration / 1000} s window · {unit}
              </Typography>
              <JointChart
                rows={rows}
                joints={chartJoints}
                metric={metric}
                start={start}
                end={end}
              />
              {pausedFrames && maxLookback > 0 && (
                <Stack direction="row" spacing={1.5} alignItems="center" sx={{ px: 1 }}>
                  <Typography variant="caption" color="text.secondary">
                    Earlier
                  </Typography>
                  <Slider
                    aria-label="History position"
                    min={0}
                    max={maxLookback}
                    value={maxLookback - Math.min(lookback, maxLookback)}
                    onChange={(_, next) => setLookback(maxLookback - Number(next))}
                    size="small"
                  />
                  <Typography variant="caption" color="text.secondary">
                    Latest
                  </Typography>
                </Stack>
              )}
              <Stack
                component="ul"
                direction="row"
                flexWrap="wrap"
                useFlexGap
                gap={1.25}
                sx={{ listStyle: "none", pl: 0, mt: 0 }}
              >
                {chartJoints.map((joint, index) => (
                  <Stack
                    component="li"
                    key={joint}
                    direction="row"
                    alignItems="center"
                    spacing={0.5}
                  >
                    <Box
                      component="span"
                      aria-hidden="true"
                      sx={{
                        width: 14,
                        borderTop: `2px ${index < colors.length ? "solid" : "dashed"} ${colors[index % colors.length]}`,
                      }}
                    />
                    <Typography variant="caption">{jointLabel(joint)}</Typography>
                  </Stack>
                ))}
              </Stack>
            </Box>
          ) : null}
          <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
            Current joint readings
          </Typography>
          <Box sx={{ overflowX: "auto" }}>
            <Table size="small" aria-label="Current joint readings" sx={{ minWidth: 500 }}>
              <TableHead>
                <TableRow>
                  <TableCell>Joint name</TableCell>
                  <TableCell align="right">Actual robot {quantity}</TableCell>
                  <TableCell align="right">Requested {quantity}</TableCell>
                  <TableCell align="right">Leader arm {quantity}</TableCell>
                  <TableCell align="right">
                    Difference
                    <Typography component="span" variant="caption" sx={{ display: "block" }}>
                      Requested − actual
                    </Typography>
                  </TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {joints.map((name) => {
                  const measured = value(data?.Follower, name, metric);
                  const command = value(data?.Action, name, metric);
                  return (
                    <TableRow key={name}>
                      <TableCell component="th" scope="row">
                        {name}
                      </TableCell>
                      {streams.map(({ key }) => (
                        <TableCell key={key} align="right">
                          {formatValue(value(data?.[key], name, metric))}
                        </TableCell>
                      ))}
                      <TableCell align="right">
                        {formatValue(
                          measured !== null && command !== null ? command - measured : null,
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </Box>
          {robotData?.Action?.source && (
            <Typography variant="caption" color="text.secondary">
              Command source: {robotData.Action.source}
            </Typography>
          )}
        </>
      )}
    </Box>
  );
}
