import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import { ExpandMore } from "@mui/icons-material";
import { armChoices } from "../lib/cellSpec";
import {
  armLabel,
  DEFAULT_CAMERA_MODEL,
  defaultCalibration,
  isRealCamera,
} from "../lib/cellComponents";
import { CameraFields, JointMappingFields } from "./SettingsCards";
import type {
  ArmCatalog,
  ArmEntry,
  CameraCatalog,
  CameraEntry,
  CameraModelId,
  DeviceScan,
} from "../types";

const CAMERA_LABELS: Partial<Record<CameraModelId, string>> = {
  opencv_usb: "USB webcam",
  realsense: "Intel RealSense",
  ids_ueye: "IDS uEye",
};

/** "UR (UR5e)" style label of a model and its variant, from the catalogue when it is loaded. */
function typeLabel(label: string, variants: Record<string, string> | undefined, variant?: string) {
  return variant ? `${label} · ${variants?.[variant] ?? variant}` : label;
}

/** Which device fills a role. Planned models are shown disabled until their driver exists. */
export function ArmModelSelect({
  role,
  value,
  catalog,
  onChange,
  id = role,
  disabled = false,
}: {
  role: ArmEntry["role"];
  value: string;
  catalog?: ArmCatalog;
  onChange: (model: string) => void;
  id?: string;
  /** The workspace layout sets the type: shown, but changed on the Cell page. */
  disabled?: boolean;
}) {
  const choices = armChoices(catalog, role);
  const label = `${role === "leader" ? "Leader" : "Follower"} model`;
  return (
    <FormControl size="small" sx={{ minWidth: 260 }}>
      <InputLabel id={`${id}-model`}>{label}</InputLabel>
      <Select
        labelId={`${id}-model`}
        label={label}
        disabled={disabled}
        value={choices.some((choice) => choice.id === value) ? value : ""}
        onChange={(event) => onChange(String(event.target.value))}
      >
        {choices.map((choice) => (
          <MenuItem
            key={choice.id}
            value={choice.id}
            disabled={choice.disabled}
            title={choice.hint}
          >
            {choice.label}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}

/** One section per leader and follower of the layout: backend, model, pairing, device, mapping. */
export function ArmsCard({
  arms,
  catalog,
  joints,
  scan,
  busy,
  onChange,
  onCalibrate,
  onImport,
}: {
  arms: ArmEntry[];
  catalog?: ArmCatalog;
  joints?: string[];
  scan: DeviceScan | null;
  busy: boolean;
  onChange: (arms: ArmEntry[]) => void;
  onCalibrate: (arm: ArmEntry) => void;
  onImport: (arm: ArmEntry, file: File) => void;
}) {
  const leaders = arms.filter((arm) => arm.role === "leader");
  const followers = arms.filter((arm) => arm.role === "follower");
  const patch = (id: string, change: Partial<ArmEntry>) =>
    onChange(arms.map((arm) => (arm.id === id ? { ...arm, ...change } : arm)));
  const setBackend = (arm: ArmEntry, backend: ArmEntry["backend"]) =>
    onChange(
      arms.map((item) => {
        if (item.id === arm.id) return { ...item, backend };
        // A follower is never real behind a mock leader.
        if (backend === "mock" && item.leader === arm.id) return { ...item, backend: "mock" };
        return item;
      }),
    );
  return (
    <Card>
      <CardContent>
        <Typography variant="h6">Arms</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          From the workspace layout: {leaders.length} leader{leaders.length === 1 ? "" : "s"} and{" "}
          {followers.length} follower{followers.length === 1 ? "" : "s"}. Add, remove or rename arms
          on the Cell page. Every follower is driven by one leader; one leader may drive several
          followers.
        </Typography>
        <Stack spacing={2}>
          {arms.map((arm) => {
            const leader = leaders.find((item) => item.id === arm.leader);
            const realBlocked = arm.role === "follower" && leader?.backend !== "real";
            return (
              <Box
                key={arm.id}
                role="group"
                aria-label={armLabel(arm)}
                sx={{ border: 1, borderColor: "divider", borderRadius: 1, p: 1.5 }}
              >
                <Stack spacing={1.5}>
                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                    <Typography variant="subtitle2">{armLabel(arm)}</Typography>
                    <Chip size="small" label={arm.id} variant="outlined" />
                    <Chip
                      size="small"
                      label={arm.role}
                      color={arm.role === "leader" ? "secondary" : "primary"}
                    />
                  </Stack>
                  <Stack
                    direction="row"
                    spacing={1.5}
                    alignItems="center"
                    flexWrap="wrap"
                    useFlexGap
                  >
                    <ToggleButtonGroup
                      exclusive
                      size="small"
                      value={arm.backend}
                      aria-label={`${armLabel(arm)} backend`}
                      onChange={(_, next: ArmEntry["backend"] | null) =>
                        next && setBackend(arm, next)
                      }
                    >
                      <ToggleButton value="mock">Mock</ToggleButton>
                      <ToggleButton value="real" disabled={realBlocked}>
                        Real
                      </ToggleButton>
                    </ToggleButtonGroup>
                    <ArmModelSelect
                      id={`arm-${arm.id}`}
                      role={arm.role}
                      value={arm.model}
                      catalog={catalog}
                      disabled={Boolean(arm.module)}
                      onChange={(model) => patch(arm.id, { model })}
                    />
                    {arm.variant && (
                      <Chip
                        size="small"
                        label={`Variant: ${catalog?.models[arm.model]?.variants?.[arm.variant] ?? arm.variant}`}
                      />
                    )}
                    {arm.module && (
                      <Typography variant="caption" color="text.secondary">
                        Type and variant are set on the arm module (Cell page).
                      </Typography>
                    )}
                    {arm.role === "follower" && (
                      <FormControl size="small" sx={{ minWidth: 200 }}>
                        <InputLabel id={`arm-${arm.id}-leader`}>Driven by</InputLabel>
                        <Select
                          labelId={`arm-${arm.id}-leader`}
                          label="Driven by"
                          value={arm.leader ?? ""}
                          onChange={(event) => {
                            const next = leaders.find((item) => item.id === event.target.value);
                            patch(arm.id, {
                              leader: String(event.target.value),
                              ...(next?.backend !== "real" && { backend: "mock" }),
                            });
                          }}
                        >
                          {leaders.map((item) => (
                            <MenuItem key={item.id} value={item.id}>
                              {armLabel(item)}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                    )}
                    {realBlocked && (
                      <Typography variant="caption" color="text.secondary">
                        A real follower needs a real leader.
                      </Typography>
                    )}
                  </Stack>
                  {arm.backend === "real" && (
                    <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
                      <FormControl size="small" sx={{ minWidth: 300 }}>
                        <InputLabel id={`arm-${arm.id}-port`}>Port</InputLabel>
                        <Select
                          labelId={`arm-${arm.id}-port`}
                          label="Port"
                          value={arm.device?.port ?? ""}
                          onChange={(event) => {
                            const found = scan?.serial.find((p) => p.port === event.target.value);
                            patch(arm.id, {
                              device: {
                                ...arm.device,
                                port: String(event.target.value),
                                serial: found?.serial || undefined,
                              },
                            });
                          }}
                        >
                          {(scan?.serial ?? []).map((port) => (
                            <MenuItem key={port.port} value={port.port}>
                              {port.port} ·{" "}
                              {port.serial ? `serial ${port.serial}` : "no serial number"}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                      <FormControl size="small" sx={{ minWidth: 220 }}>
                        <InputLabel id={`arm-${arm.id}-cal`}>Calibration file</InputLabel>
                        <Select
                          labelId={`arm-${arm.id}-cal`}
                          label="Calibration file"
                          value={arm.device?.calibration ?? defaultCalibration(arm, arms)}
                          onChange={(event) =>
                            patch(arm.id, {
                              device: { ...arm.device, calibration: String(event.target.value) },
                            })
                          }
                        >
                          {[
                            ...new Set([
                              ...(scan?.calibrations ?? []),
                              defaultCalibration(arm, arms),
                              ...(arm.device?.calibration ? [arm.device.calibration] : []),
                            ]),
                          ].map((name) => (
                            <MenuItem key={name} value={name}>
                              {name}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                      <Button disabled={!arm.device?.port || busy} onClick={() => onCalibrate(arm)}>
                        Calibrate…
                      </Button>
                      <Button component="label" disabled={busy}>
                        Import file…
                        <input
                          hidden
                          type="file"
                          accept=".yaml,.yml,text/yaml"
                          onChange={(event) => {
                            const file = event.target.files?.[0];
                            event.target.value = "";
                            if (file) onImport(arm, file);
                          }}
                        />
                      </Button>
                    </Stack>
                  )}
                  {arm.role === "follower" && (
                    <Accordion disableGutters variant="outlined">
                      <AccordionSummary expandIcon={<ExpandMore />}>
                        <Typography variant="body2">
                          Joint mapping from {leader ? armLabel(leader) : "its leader"}
                          {Object.keys(arm.joint_mapping ?? {}).length
                            ? ` · ${Object.keys(arm.joint_mapping ?? {}).length} customised`
                            : ""}
                        </Typography>
                      </AccordionSummary>
                      <AccordionDetails>
                        <JointMappingFields
                          mapping={arm.joint_mapping ?? {}}
                          joints={joints}
                          onChange={(joint_mapping) => patch(arm.id, { joint_mapping })}
                        />
                      </AccordionDetails>
                    </Accordion>
                  )}
                </Stack>
              </Box>
            );
          })}
        </Stack>
      </CardContent>
    </Card>
  );
}

/** One section per camera of the layout: mock or USB, device, resolution and frame rate. */
export function CamerasCard({
  cameras,
  catalog,
  scan,
  onChange,
}: {
  cameras: CameraEntry[];
  catalog?: CameraCatalog;
  scan: DeviceScan | null;
  onChange: (cameras: CameraEntry[]) => void;
}) {
  const patch = (id: string, change: Partial<CameraEntry>) =>
    onChange(cameras.map((camera) => (camera.id === id ? { ...camera, ...change } : camera)));
  const modelOf = (camera: CameraEntry) => camera.model ?? DEFAULT_CAMERA_MODEL;
  const labelOf = (model: CameraModelId) =>
    catalog?.models[model]?.label ?? CAMERA_LABELS[model] ?? model;
  return (
    <Card>
      <CardContent>
        <Typography variant="h6">Cameras</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          From the workspace layout: {cameras.length} camera{cameras.length === 1 ? "" : "s"}. Set
          the camera type on its module on the Cell page; choose mock or real here. Each one is
          recorded as <code>observation.images.&lt;id&gt;</code>; the slowest camera sets the
          episode timeline.
        </Typography>
        <Stack spacing={2}>
          {cameras.map((camera) => {
            const model = modelOf(camera);
            const info = catalog?.models[model];
            return (
              <Box
                key={camera.id}
                role="group"
                aria-label={camera.name ?? camera.id}
                sx={{ border: 1, borderColor: "divider", borderRadius: 1, p: 1.5 }}
              >
                <Stack spacing={1.5}>
                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                    <Typography variant="subtitle2">{camera.name ?? camera.id}</Typography>
                    <Chip size="small" label={camera.id} variant="outlined" />
                    <Chip
                      size="small"
                      color="primary"
                      variant="outlined"
                      label={typeLabel(labelOf(model), info?.variants, camera.variant)}
                    />
                    <ToggleButtonGroup
                      exclusive
                      size="small"
                      value={isRealCamera(camera) ? "real" : "synthetic"}
                      aria-label={`${camera.name ?? camera.id} source`}
                      onChange={(_, next: "synthetic" | "real" | null) =>
                        next && patch(camera.id, { source: next === "real" ? model : "synthetic" })
                      }
                    >
                      <ToggleButton value="synthetic">Mock</ToggleButton>
                      <ToggleButton value="real" disabled={info?.status === "planned"}>
                        Real
                      </ToggleButton>
                    </ToggleButtonGroup>
                    {camera.source === "opencv_usb" && (
                      <FormControl size="small" sx={{ minWidth: 260 }}>
                        <InputLabel id={`camera-${camera.id}-device`}>Device</InputLabel>
                        <Select
                          labelId={`camera-${camera.id}-device`}
                          label="Device"
                          value={camera.device?.device ?? ""}
                          onChange={(event) => {
                            const found = scan?.video.find((v) => v.device === event.target.value);
                            patch(camera.id, {
                              device: {
                                device: String(event.target.value),
                                serial: found?.serial || undefined,
                                card: found?.card,
                              },
                            });
                          }}
                        >
                          {(scan?.video ?? []).map((video) => (
                            <MenuItem key={video.device} value={video.device}>
                              {video.device} · {video.card}
                              {video.integrated ? " · laptop camera" : ""}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                    )}
                    {isRealCamera(camera) &&
                      camera.source !== "opencv_usb" &&
                      (info?.access ?? "usb_bus") === "usb_bus" && (
                        <TextField
                          size="small"
                          label="Serial number"
                          placeholder="empty = first camera found"
                          value={camera.device?.serial ?? ""}
                          slotProps={{ htmlInput: { maxLength: 32 } }}
                          onChange={(event) =>
                            patch(camera.id, {
                              device: { ...camera.device, serial: event.target.value || undefined },
                            })
                          }
                        />
                      )}
                    {isRealCamera(camera) && info?.access === "network" && (
                      <TextField
                        size="small"
                        label="Address"
                        placeholder="192.168.1.50"
                        required
                        value={camera.device?.address ?? ""}
                        slotProps={{ htmlInput: { maxLength: 253 } }}
                        onChange={(event) =>
                          patch(camera.id, {
                            device: { address: event.target.value || undefined },
                          })
                        }
                      />
                    )}
                    {isRealCamera(camera) && info?.installed === false && (
                      <Chip
                        size="small"
                        color="warning"
                        label="Driver image not on this host"
                        title={info.image}
                      />
                    )}
                    {camera.source === "ids_ueye" && (
                      <FormControl size="small" sx={{ minWidth: 160 }}>
                        <InputLabel id={`camera-${camera.id}-connection`}>Connection</InputLabel>
                        <Select
                          labelId={`camera-${camera.id}-connection`}
                          label="Connection"
                          value={camera.device?.connection ?? "usb"}
                          onChange={(event) =>
                            patch(camera.id, {
                              device: { ...camera.device, connection: String(event.target.value) },
                            })
                          }
                        >
                          <MenuItem value="usb">USB</MenuItem>
                          <MenuItem value="gige" disabled>
                            GigE (LAN) · not in cells yet
                          </MenuItem>
                        </Select>
                      </FormControl>
                    )}
                  </Stack>
                  {isRealCamera(camera) && info?.note && (
                    <Typography variant="caption" color="text.secondary">
                      {info.note}
                    </Typography>
                  )}
                  <CameraFields
                    title="Resolution"
                    value={{ width: camera.width, height: camera.height, fps: camera.fps }}
                    onChange={(value) => patch(camera.id, value)}
                  />
                </Stack>
              </Box>
            );
          })}
        </Stack>
      </CardContent>
    </Card>
  );
}
