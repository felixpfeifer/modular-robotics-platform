import {
  Alert,
  Card,
  CardContent,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import { inRange, limits, setJointMapping } from "../lib/cellSpec";
import type { CameraSettings, CellSettings, JointMappingEntry, TeleopSettings } from "../types";

export function NumberInput({
  label,
  value,
  field,
  onChange,
  step = 1,
  width = 130,
}: {
  label: string;
  value: number;
  field: keyof typeof limits;
  onChange: (value: number) => void;
  step?: number;
  width?: number;
}) {
  const [low, high] = limits[field];
  const bad = !inRange(value, field);
  return (
    <TextField
      size="small"
      type="number"
      label={label}
      value={Number.isFinite(value) ? value : ""}
      error={bad}
      helperText={bad ? `${low}–${high}` : " "}
      sx={{ width }}
      slotProps={{ htmlInput: { min: low, max: high, step } }}
      onChange={(event) => onChange(event.target.value === "" ? NaN : Number(event.target.value))}
    />
  );
}

export function CameraFields({
  title,
  value,
  onChange,
}: {
  title: string;
  value: CameraSettings;
  onChange: (value: CameraSettings) => void;
}) {
  return (
    <Stack direction="row" spacing={1.5} alignItems="flex-start">
      <Typography sx={{ width: 110, pt: 1 }}>{title}</Typography>
      <NumberInput
        label="Width"
        field="width"
        value={value.width}
        onChange={(width) => onChange({ ...value, width })}
      />
      <NumberInput
        label="Height"
        field="height"
        value={value.height}
        onChange={(height) => onChange({ ...value, height })}
      />
      <NumberInput
        label="FPS"
        field="fps"
        value={value.fps}
        onChange={(fps) => onChange({ ...value, fps })}
        width={100}
      />
    </Stack>
  );
}

/** A number that may be left empty (= unset, the default applies). */
function OptionalNumber({
  label,
  value,
  field,
  placeholder,
  onChange,
}: {
  label: string;
  value?: number;
  field: keyof typeof limits;
  placeholder: string;
  onChange: (value: number | undefined) => void;
}) {
  const [low, high] = limits[field];
  const bad = value !== undefined && !inRange(value, field);
  return (
    <TextField
      size="small"
      type="number"
      label={label}
      placeholder={placeholder}
      value={value ?? ""}
      error={bad}
      sx={{ width: 130 }}
      slotProps={{ htmlInput: { min: low, max: high, step: 0.01 }, inputLabel: { shrink: true } }}
      onChange={(event) =>
        onChange(event.target.value === "" ? undefined : Number(event.target.value))
      }
    />
  );
}

/** Control arbiter timing and the leader-to-follower joint mapping (generated control/*.yaml). */
/** Leader-to-follower joint mapping of one follower; empty fields keep the defaults. */
export function JointMappingFields({
  mapping,
  joints,
  onChange,
}: {
  mapping: Record<string, JointMappingEntry>;
  joints?: string[];
  onChange: (mapping: Record<string, JointMappingEntry>) => void;
}) {
  const setMapping = (joint: string, key: keyof JointMappingEntry, item?: string | number) =>
    onChange(setJointMapping(mapping, joint, key, item));
  return (
    <>
      {joints ? (
        <Stack spacing={1}>
          <Typography variant="body2" color="text.secondary">
            Joint mapping per follower joint. Empty fields keep the default: the same-named leader
            joint, scale 1, no offset. Use scale −1 for a joint that turns the other way, and the
            references from a matched leader/follower pose.
          </Typography>
          {joints.map((joint) => {
            const entry = mapping[joint] ?? {};
            return (
              <Stack
                key={joint}
                direction="row"
                spacing={1.5}
                alignItems="center"
                flexWrap="wrap"
                useFlexGap
              >
                <Typography sx={{ width: 170 }} variant="body2">
                  {joint}
                </Typography>
                <TextField
                  size="small"
                  label="Leader joint"
                  placeholder={joint}
                  value={entry.leader_joint ?? ""}
                  sx={{ width: 190 }}
                  slotProps={{ inputLabel: { shrink: true } }}
                  onChange={(event) => setMapping(joint, "leader_joint", event.target.value.trim())}
                />
                <OptionalNumber
                  label="Scale"
                  field="scale"
                  placeholder="1"
                  value={entry.scale}
                  onChange={(item) => setMapping(joint, "scale", item)}
                />
                <OptionalNumber
                  label="Leader ref (rad)"
                  field="reference_rad"
                  placeholder="0"
                  value={entry.leader_reference_rad}
                  onChange={(item) => setMapping(joint, "leader_reference_rad", item)}
                />
                <OptionalNumber
                  label="Follower ref (rad)"
                  field="reference_rad"
                  placeholder="0"
                  value={entry.follower_reference_rad}
                  onChange={(item) => setMapping(joint, "follower_reference_rad", item)}
                />
              </Stack>
            );
          })}
        </Stack>
      ) : (
        <Typography variant="body2" color="text.secondary">
          The joint mapping appears once the deployment agent reports this robot&apos;s profile.
        </Typography>
      )}
    </>
  );
}

function TeleopFields({
  value,
  joints,
  onChange,
  hideMapping,
}: {
  value: TeleopSettings;
  joints?: string[];
  onChange: (value: TeleopSettings) => void;
  hideMapping?: boolean;
}) {
  return (
    <>
      <Typography variant="subtitle2" sx={{ pt: 1 }}>
        Teleoperation and control
      </Typography>
      <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap alignItems="flex-start">
        <NumberInput
          label="Intent validity (ms)"
          field="validity_ms"
          value={value.validity_ms}
          width={170}
          onChange={(validity_ms) => onChange({ ...value, validity_ms })}
        />
        <NumberInput
          label="Max leader age (ms)"
          field="max_leader_age_ms"
          value={value.max_leader_age_ms}
          width={170}
          onChange={(max_leader_age_ms) => onChange({ ...value, max_leader_age_ms })}
        />
        <NumberInput
          label="Source timeout (ms)"
          field="source_timeout_ms"
          value={value.source_timeout_ms}
          width={170}
          onChange={(source_timeout_ms) => onChange({ ...value, source_timeout_ms })}
        />
        <NumberInput
          label="Max handover jump (rad)"
          field="max_handover_jump_rad"
          value={value.max_handover_jump_rad}
          width={190}
          step={0.01}
          onChange={(max_handover_jump_rad) => onChange({ ...value, max_handover_jump_rad })}
        />
      </Stack>
      {!hideMapping && (
        <JointMappingFields
          mapping={value.joint_mapping}
          joints={joints}
          onChange={(joint_mapping) => onChange({ ...value, joint_mapping })}
        />
      )}
    </>
  );
}

/** Cameras, recording rules, mock motion and teleop: everything that used to live in YAML files. */
export function SettingsCard({
  settings,
  onChange,
  mockLeader,
  mockMotion,
  joints,
  listedCameras,
  listedArms,
}: {
  settings: CellSettings;
  onChange: (settings: CellSettings) => void;
  mockLeader: boolean;
  mockMotion: boolean;
  /** The robot profile's joint names; undefined while unknown. */
  joints?: string[];
  /** Cameras are configured one by one in the Cameras card (from the workspace layout). */
  listedCameras?: boolean;
  /** Each follower keeps its own joint mapping in the Arms card. */
  listedArms?: boolean;
}) {
  const side = settings.side_camera;
  return (
    <Card>
      <CardContent>
        <Typography variant="h6">Settings</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Applied every time the cell starts. The recording configuration is generated from these
          values, so there are no files to edit.
        </Typography>
        <Stack spacing={1}>
          {listedCameras ? (
            <Typography variant="body2" color="text.secondary">
              Cameras come from the workspace layout; set each one in the Cameras card.
            </Typography>
          ) : (
            <>
              <Typography variant="subtitle2">Cameras</Typography>
              <CameraFields
                title="Main camera"
                value={settings.camera}
                onChange={(camera) => onChange({ ...settings, camera })}
              />
              <FormControlLabel
                control={
                  <Switch
                    checked={side.enabled}
                    onChange={(event) =>
                      onChange({
                        ...settings,
                        side_camera: { ...side, enabled: event.target.checked },
                      })
                    }
                  />
                }
                label="Second camera (e.g. a bird's-eye side view)"
              />
              {side.enabled && (
                <Stack direction="row" spacing={1.5} alignItems="flex-start">
                  <TextField
                    select
                    size="small"
                    label="Source"
                    value={side.source}
                    sx={{ width: 110 }}
                    onChange={(event) =>
                      onChange({
                        ...settings,
                        side_camera: { ...side, source: event.target.value as typeof side.source },
                      })
                    }
                  >
                    <MenuItem value="synthetic">Mock</MenuItem>
                    <MenuItem value="opencv_usb">USB</MenuItem>
                  </TextField>
                  <NumberInput
                    label="Width"
                    field="width"
                    value={side.width}
                    onChange={(width) => onChange({ ...settings, side_camera: { ...side, width } })}
                  />
                  <NumberInput
                    label="Height"
                    field="height"
                    value={side.height}
                    onChange={(height) =>
                      onChange({ ...settings, side_camera: { ...side, height } })
                    }
                  />
                  <NumberInput
                    label="FPS"
                    field="fps"
                    value={side.fps}
                    onChange={(fps) => onChange({ ...settings, side_camera: { ...side, fps } })}
                    width={100}
                  />
                </Stack>
              )}
            </>
          )}
          <Typography variant="subtitle2" sx={{ pt: 1 }}>
            Recording
          </Typography>
          <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap alignItems="flex-start">
            <NumberInput
              label="Min. duration (s)"
              field="minimum_duration_seconds"
              value={settings.recording.minimum_duration_seconds}
              width={160}
              onChange={(minimum_duration_seconds) =>
                onChange({
                  ...settings,
                  recording: { ...settings.recording, minimum_duration_seconds },
                })
              }
            />
            <NumberInput
              label="Free disk needed (GiB)"
              field="preflight_min_free_gib"
              value={settings.recording.preflight_min_free_gib}
              width={190}
              step={0.5}
              onChange={(preflight_min_free_gib) =>
                onChange({
                  ...settings,
                  recording: { ...settings.recording, preflight_min_free_gib },
                })
              }
            />
            <NumberInput
              label="Max camera gap (ms)"
              field="maximum_camera_gap_ms"
              value={settings.recording.maximum_camera_gap_ms}
              width={190}
              onChange={(maximum_camera_gap_ms) =>
                onChange({
                  ...settings,
                  recording: { ...settings.recording, maximum_camera_gap_ms },
                })
              }
            />
            <TextField
              size="small"
              label="Task instruction"
              placeholder="Default for this task"
              value={settings.recording.instruction}
              error={settings.recording.instruction.length > 200}
              sx={{ minWidth: 320, flex: 1 }}
              onChange={(event) =>
                onChange({
                  ...settings,
                  recording: { ...settings.recording, instruction: event.target.value },
                })
              }
            />
          </Stack>
          {mockLeader && mockMotion && (
            <>
              <Typography variant="subtitle2" sx={{ pt: 1 }}>
                Mock leader motion
              </Typography>
              <Stack direction="row" spacing={1.5} alignItems="flex-start">
                <TextField
                  select
                  size="small"
                  label="Style"
                  value={settings.mock_motion.mode}
                  sx={{ width: 150 }}
                  onChange={(event) =>
                    onChange({
                      ...settings,
                      mock_motion: {
                        ...settings.mock_motion,
                        mode: event.target.value as "waypoints" | "sine",
                      },
                    })
                  }
                >
                  <MenuItem value="waypoints">Random waypoints</MenuItem>
                  <MenuItem value="sine">Sine waves</MenuItem>
                </TextField>
                <NumberInput
                  label="Speed"
                  field="speed"
                  step={0.1}
                  value={settings.mock_motion.speed}
                  onChange={(speed) =>
                    onChange({ ...settings, mock_motion: { ...settings.mock_motion, speed } })
                  }
                />
                <NumberInput
                  label="Seed"
                  field="seed"
                  value={settings.mock_motion.seed}
                  onChange={(seed) =>
                    onChange({ ...settings, mock_motion: { ...settings.mock_motion, seed } })
                  }
                />
              </Stack>
            </>
          )}
          <TeleopFields
            value={settings.teleop}
            joints={joints}
            hideMapping={listedArms}
            onChange={(teleop) => onChange({ ...settings, teleop })}
          />
          {listedArms && (
            <Typography variant="body2" color="text.secondary">
              Each follower&apos;s joint mapping is set with that follower in the Arms card.
            </Typography>
          )}
          <Typography variant="caption" color="text.secondary">
            Max camera gap: the longest pause between camera frames an episode may contain. 0 =
            automatic (75 ms at 30 fps). Raising it accepts choppier video, so keep it low for real
            robot data.
          </Typography>
          <Alert severity="info" sx={{ mt: 1 }}>
            Changes apply when the cell is (re)started. A camera that cannot deliver the chosen
            frame rate fails the connection test; the test offers the measured rate.
          </Alert>
        </Stack>
      </CardContent>
    </Card>
  );
}
