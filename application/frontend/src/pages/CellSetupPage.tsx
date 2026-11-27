import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Switch,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import {
  identifyLeader,
  importCalibration as uploadCalibration,
  saveCell,
  queryKeys,
  scanDevices,
  useCatalog,
  useDeviceScan,
  useNetwork,
  takeSnapshot,
  testCell,
} from "../api";
import { ArmModelSelect, ArmsCard, CamerasCard } from "../components/CellListCards";
import { CalibrationWizard, type Role } from "../components/cellSetup/CalibrationWizard";
import { ConnectionHelpCard } from "../components/cellSetup/ConnectionHelpCard";
import { ConnectionTestResults } from "../components/cellSetup/ConnectionTestResults";
import { ImageOverridesCard } from "../components/cellSetup/ImageOverridesCard";
import { ModeToggle } from "../components/cellSetup/ModeToggle";
import { SettingsCard } from "../components/SettingsCards";
import { armLabel, defaultCalibration, moduleModel } from "../lib/cellComponents";
import {
  allLeadersMock,
  buildCell,
  followerAllowed,
  fromProject,
  hasRealDevices,
  missingDevices,
  movesMotors,
  presetFor,
  usesMainUsb,
  settingsErrors,
  usesSideUsb,
  type Mode,
  type Selection,
} from "../lib/cellSpec";
import type {
  ArmDevice,
  ArmEntry,
  DeviceScan,
  IdentifyResult,
  Project,
  RunAction,
  TestResult,
  VideoDevice,
} from "../types";

const label = (role: Role) => (role === "leader" ? "Leader" : "Follower");

export function CellSetupPage({
  project,
  busy,
  run,
  onDirtyChange,
}: {
  project?: Project;
  busy: boolean;
  run: RunAction;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [selection, setSelection] = useState<Selection>(() => fromProject(project));
  const [savedSelection, setSavedSelection] = useState(() => JSON.stringify(fromProject(project)));
  const dirty = JSON.stringify(selection) !== savedSelection;
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
  const queryClient = useQueryClient();
  const scanQuery = useDeviceScan();
  // The demo backend answers some scans without calibrations; treat those as no scan yet.
  const scan = scanQuery.data && Array.isArray(scanQuery.data.calibrations) ? scanQuery.data : null;
  const setScan = (next: DeviceScan | ((current?: DeviceScan) => DeviceScan | undefined)) =>
    queryClient.setQueryData(queryKeys.deviceScan, next);
  const [test, setTest] = useState<TestResult | null>(null);
  const [identify, setIdentify] = useState<IdentifyResult | null>(null);
  const [snapshots, setSnapshots] = useState<Record<string, string>>({});
  const [wizard, setWizard] = useState<{
    role: Role;
    device: ArmDevice;
    name: string;
    title: string;
    apply: () => void;
  } | null>(null);
  const network = useNetwork().data;
  const robots = useCatalog().data;
  // Re-derive when the project or the arms/cameras placed in its layout change, not on every refresh.
  const layoutKey = JSON.stringify(
    (project?.cell_layout?.modules ?? [])
      .filter((m) => m.type === "arm" || m.type === "camera")
      .map((m) => [
        m.id,
        m.name,
        m.enabled,
        m.properties.role,
        m.properties.model,
        m.properties.variant,
      ]),
  );
  const sourceKey = `${project?.id}|${layoutKey}`;
  const [loadedKey, setLoadedKey] = useState(sourceKey);
  if (loadedKey !== sourceKey) {
    setLoadedKey(sourceKey);
    const initial = fromProject(project);
    setSelection(initial);
    setSavedSelection(JSON.stringify(initial));
  }
  if (!project) return <Alert severity="info">Select or create a project first.</Alert>;

  const update = (patch: Partial<Selection>) => {
    setSelection((old) => ({ ...old, ...patch }));
    setTest(null);
  };
  const setArm = (role: Role, patch: Partial<ArmDevice>) =>
    update({
      devices: { ...selection.devices, [role]: { ...selection.devices[role], ...patch } },
    });
  const setLeader = (mode: Mode) =>
    update({ leader: mode, follower: followerAllowed(mode) ? selection.follower : "mock" });
  const real = hasRealDevices(selection);
  // A single leader/follower placed in the layout with a type: that module decides the model.
  const typedInLayout = (role: Role) =>
    Boolean(
      moduleModel(
        (project.cell_layout?.modules ?? []).find(
          (m) => m.type === "arm" && m.enabled !== false && m.properties.role === role,
        ),
      ),
    );
  const joints = robots?.robots?.[robots.presets?.[presetFor(selection)]?.robot ?? ""]?.joint_names;
  const missing = missingDevices(selection);
  const invalid = settingsErrors(selection.settings);
  const save = async () => {
    const current = JSON.stringify(selection);
    await saveCell(project.id, buildCell(selection));
    setSavedSelection(current);
  };
  const portOption = (port: DeviceScan["serial"][number]) => (
    <MenuItem key={port.port} value={port.port}>
      {port.port} · {port.serial ? `serial ${port.serial}` : "no serial number"}
      {port.likely_so101 ? "" : " · unknown adapter"}
    </MenuItem>
  );
  const pickPort = (role: Role, port: string) => {
    const found = scan?.serial.find((item) => item.port === port);
    setArm(role, { port, serial: found?.serial || undefined });
  };
  const pickCamera = (role: "camera" | "side_camera", camera: VideoDevice) =>
    update({
      devices: {
        ...selection.devices,
        [role]: { device: camera.device, serial: camera.serial || undefined, card: camera.card },
      },
    });
  const importCalibration = (name: string, file: File, apply: () => void) =>
    run(async () => {
      await uploadCalibration(name, await file.text());
      apply();
      setScan(await scanDevices());
    }, `Calibration imported as ${name}.`);
  /** Set one listed arm's calibration file without losing other edits. */
  const listedCalibration = (id: string, calibration: string) => () =>
    setSelection((old) => ({
      ...old,
      arms: (old.arms ?? []).map((arm) =>
        arm.id === id ? { ...arm, device: { ...arm.device, calibration } } : arm,
      ),
    }));
  const legacyCalibration = (role: Role, calibration: string) => () =>
    setSelection((old) => ({
      ...old,
      devices: { ...old.devices, [role]: { ...old.devices[role], calibration } },
    }));
  const calibrateArm = (arm: ArmEntry, arms: ArmEntry[]) => {
    const name = arm.device?.calibration ?? defaultCalibration(arm, arms);
    setWizard({
      role: arm.role,
      device: arm.device ?? {},
      name,
      title: armLabel(arm),
      apply: listedCalibration(arm.id, name),
    });
  };
  const setCameraFps = (check: TestResult["checks"][number], fps: number) => {
    if (selection.cameras) {
      const id = check.camera_id ?? check.role;
      update({
        cameras: selection.cameras.map((camera) =>
          camera.id === id ? { ...camera, fps } : camera,
        ),
      });
      return;
    }
    const key = check.role === "side_camera" ? "side_camera" : "camera";
    update({ settings: { ...selection.settings, [key]: { ...selection.settings[key], fps } } });
  };
  const cameraPicker = (role: "camera" | "side_camera", title: string) => (
    <Stack spacing={1} key={role}>
      <Typography variant="subtitle2">{title}</Typography>
      {(scan?.video ?? []).length === 0 && (
        <Typography variant="body2" color="text.secondary">
          Scan to list cameras.
        </Typography>
      )}
      {(scan?.video ?? []).map((camera) => {
        const chosen = selection.devices[role]?.device === camera.device;
        const shotKey = `${role}:${camera.device}`;
        return (
          <Stack key={camera.device} direction="row" spacing={1.5} alignItems="center">
            <Button
              variant={chosen ? "contained" : "outlined"}
              onClick={() => pickCamera(role, camera)}
            >
              {camera.device} · {camera.card}
            </Button>
            {camera.integrated && <Chip size="small" label="laptop camera" />}
            <Button
              size="small"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const shot = await takeSnapshot(camera.device, camera.serial || undefined);
                  if (shot.jpeg_base64)
                    setSnapshots((old) => ({ ...old, [shotKey]: shot.jpeg_base64 as string }));
                }, "Snapshot taken.")
              }
            >
              Preview
            </Button>
            {snapshots[shotKey] && (
              <Box
                component="img"
                alt={`Preview of ${camera.device}`}
                src={`data:image/jpeg;base64,${snapshots[shotKey]}`}
                sx={{ height: 72, borderRadius: 1 }}
              />
            )}
          </Stack>
        );
      })}
    </Stack>
  );

  return (
    <Stack spacing={2}>
      {dirty && (
        <Alert severity="warning">
          Unsaved changes. Save the cell before leaving or reloading this page.
        </Alert>
      )}
      <Card>
        <CardContent>
          <Typography variant="h6">Components</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Mock components need no hardware and can produce moving joint data for testing the
            pipeline and training. Real components use USB devices.
          </Typography>
          <Stack spacing={2}>
            {selection.arms ? (
              <Typography variant="body2">
                {selection.arms.length} arms from the workspace layout: set each one in the Arms
                card below.
              </Typography>
            ) : (
              <>
                <Stack direction="row" spacing={2} alignItems="center">
                  <Typography sx={{ width: 120 }}>Leader arm</Typography>
                  <ModeToggle name="Leader arm" value={selection.leader} onChange={setLeader} />
                  <ArmModelSelect
                    role="leader"
                    value={selection.leaderModel}
                    catalog={robots?.arms}
                    disabled={typedInLayout("leader")}
                    onChange={(leaderModel) => update({ leaderModel })}
                  />
                </Stack>
                <Stack direction="row" spacing={2} alignItems="center">
                  <Typography sx={{ width: 120 }}>Follower arm</Typography>
                  <ModeToggle
                    name="Follower arm"
                    value={selection.follower}
                    realDisabled={!followerAllowed(selection.leader)}
                    onChange={(follower) => update({ follower })}
                  />
                  <ArmModelSelect
                    role="follower"
                    value={selection.followerModel}
                    catalog={robots?.arms}
                    disabled={typedInLayout("follower")}
                    onChange={(followerModel) => update({ followerModel })}
                  />
                  {!followerAllowed(selection.leader) && (
                    <Typography variant="caption" color="text.secondary">
                      A real follower needs the real leader.
                    </Typography>
                  )}
                </Stack>
              </>
            )}
            {selection.cameras ? (
              <Typography variant="body2">
                {selection.cameras.length} camera{selection.cameras.length === 1 ? "" : "s"} from
                the workspace layout: set each one in the Cameras card below.
              </Typography>
            ) : (
              <Stack direction="row" spacing={2} alignItems="center">
                <Typography sx={{ width: 120 }}>Camera</Typography>
                <ToggleButtonGroup
                  exclusive
                  size="small"
                  aria-label="Camera"
                  value={selection.camera}
                  onChange={(_, camera: Selection["camera"] | null) => camera && update({ camera })}
                >
                  <ToggleButton value="synthetic">Mock</ToggleButton>
                  <ToggleButton value="opencv_usb">USB camera</ToggleButton>
                </ToggleButtonGroup>
              </Stack>
            )}
            {allLeadersMock(selection) && (
              <FormControlLabel
                control={
                  <Switch
                    checked={selection.mockMotion}
                    onChange={(event) => update({ mockMotion: event.target.checked })}
                  />
                }
                label={`Mock ${selection.arms ? "leaders move" : "leader moves"} on ${selection.arms ? "their" : "its"} own (joint data for pipeline and training tests)`}
              />
            )}
            <Typography variant="body2" component="div">
              Cell type: <Chip size="small" label={presetFor(selection)} />
            </Typography>
          </Stack>
        </CardContent>
      </Card>

      {selection.arms && (
        <ArmsCard
          arms={selection.arms}
          catalog={robots?.arms}
          joints={joints}
          scan={scan}
          busy={busy}
          onChange={(arms) => update({ arms })}
          onCalibrate={(arm) => calibrateArm(arm, selection.arms ?? [])}
          onImport={(arm, file) => {
            const name = arm.device?.calibration ?? defaultCalibration(arm, selection.arms ?? []);
            void importCalibration(name, file, listedCalibration(arm.id, name));
          }}
        />
      )}
      {selection.cameras && (
        <CamerasCard
          cameras={selection.cameras}
          catalog={robots?.cameras}
          scan={scan}
          onChange={(cameras) => update({ cameras })}
        />
      )}

      <ImageOverridesCard images={selection.images} onChange={(images) => update({ images })} />

      <SettingsCard
        settings={selection.settings}
        joints={joints}
        mockLeader={allLeadersMock(selection)}
        mockMotion={selection.mockMotion}
        listedArms={Boolean(selection.arms)}
        listedCameras={Boolean(selection.cameras)}
        onChange={(settings) => update({ settings })}
      />

      {real && (
        <Card>
          <CardContent>
            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Box>
                <Typography variant="h6">USB devices</Typography>
                <Typography variant="body2" color="text.secondary">
                  Scan, then pick each device. The laptop&apos;s integrated camera is listed last.
                </Typography>
              </Box>
              <Button
                variant="outlined"
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    setScan(await scanDevices());
                  }, "Scan finished.")
                }
              >
                Scan devices
              </Button>
            </Stack>
            {scan?.hints.map((hint) => (
              <Alert key={hint} severity="warning" sx={{ mt: 2 }}>
                {hint}
              </Alert>
            ))}
            <Stack spacing={2} sx={{ mt: 2 }}>
              {selection.arms && (
                <Typography variant="body2" color="text.secondary">
                  Pick each real arm&apos;s port and calibration in the Arms card
                  {selection.cameras ? ", and each USB camera in the Cameras card" : ""}.
                </Typography>
              )}
              {(["leader", "follower"] as Role[])
                .filter((role) => !selection.arms && selection[role] === "real")
                .map((role) => (
                  <Stack key={role} direction={{ xs: "column", md: "row" }} spacing={1.5}>
                    <FormControl size="small" sx={{ minWidth: 320 }}>
                      <InputLabel id={`${role}-port`}>{label(role)} port</InputLabel>
                      <Select
                        labelId={`${role}-port`}
                        label={`${label(role)} port`}
                        value={selection.devices[role]?.port ?? ""}
                        onChange={(event) => pickPort(role, event.target.value)}
                      >
                        {(scan?.serial ?? []).map(portOption)}
                      </Select>
                    </FormControl>
                    <FormControl size="small" sx={{ minWidth: 220 }}>
                      <InputLabel id={`${role}-cal`}>Calibration file</InputLabel>
                      <Select
                        labelId={`${role}-cal`}
                        label="Calibration file"
                        value={selection.devices[role]?.calibration ?? ""}
                        onChange={(event) => setArm(role, { calibration: event.target.value })}
                      >
                        {[
                          ...new Set([
                            ...(scan?.calibrations ?? []),
                            ...(selection.devices[role]?.calibration
                              ? [selection.devices[role].calibration]
                              : []),
                          ]),
                        ].map((name) => (
                          <MenuItem key={name} value={name}>
                            {name}
                          </MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                    <Button
                      disabled={!selection.devices[role]?.port || busy}
                      onClick={() =>
                        setWizard({
                          role,
                          device: selection.devices[role] as ArmDevice,
                          name: `${role}.yaml`,
                          title: `the ${role} arm`,
                          apply: legacyCalibration(role, `${role}.yaml`),
                        })
                      }
                    >
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
                          if (file)
                            void importCalibration(
                              `${role}.yaml`,
                              file,
                              legacyCalibration(role, `${role}.yaml`),
                            );
                        }}
                      />
                    </Button>
                  </Stack>
                ))}
              {!selection.arms && selection.leader === "real" && selection.follower === "real" && (
                <Box>
                  <Button
                    variant="outlined"
                    disabled={missing.length > 0 && !selection.devices.leader?.port}
                    onClick={() =>
                      void run(async () => {
                        const ports = [
                          selection.devices.leader?.port,
                          selection.devices.follower?.port,
                        ];
                        setIdentify(await identifyLeader(ports, 5));
                      }, "Identify test finished.")
                    }
                  >
                    Check which port is the leader
                  </Button>
                  <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                    Pick both ports, click, then move only the leader arm by hand for 5 seconds.
                  </Typography>
                  {identify && (
                    <Alert
                      sx={{ mt: 1 }}
                      severity={identify.suggested_leader ? "success" : "warning"}
                      action={
                        identify.suggested_leader &&
                        identify.suggested_leader !== selection.devices.leader?.port ? (
                          <Button
                            color="inherit"
                            size="small"
                            onClick={() => {
                              const { leader, follower } = selection.devices;
                              update({
                                devices: {
                                  ...selection.devices,
                                  leader: follower,
                                  follower: leader,
                                },
                              });
                              setIdentify(null);
                            }}
                          >
                            Swap
                          </Button>
                        ) : undefined
                      }
                    >
                      {identify.suggested_leader
                        ? `${identify.suggested_leader} moved: it is the leader.${
                            identify.suggested_leader === selection.devices.leader?.port
                              ? " Matches your selection."
                              : " Your selection is swapped."
                          }`
                        : identify.detail}
                    </Alert>
                  )}
                </Box>
              )}
              {usesMainUsb(selection) && cameraPicker("camera", "Main USB camera")}
              {usesSideUsb(selection) && cameraPicker("side_camera", "Side USB camera")}
            </Stack>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent>
          <Typography variant="h6">Save and test</Typography>
          {movesMotors(selection) && (
            <Alert severity="warning" sx={{ my: 1 }}>
              This cell powers real motors. Keep the power switch within reach.
            </Alert>
          )}
          <Stack direction="row" spacing={1.5} sx={{ my: 1.5 }} alignItems="center">
            <Button
              variant="contained"
              disabled={busy || invalid.length > 0 || (real && missing.length > 0)}
              onClick={() => void run(async () => void (await save()), "Cell saved.")}
            >
              Save cell
            </Button>
            {real && (
              <Button
                variant="outlined"
                disabled={busy || invalid.length > 0 || missing.length > 0}
                onClick={() =>
                  void run(async () => {
                    await save();
                    setTest(await testCell(project.id));
                  }, "Connection test finished.")
                }
              >
                Run connection test
              </Button>
            )}
            {invalid.length > 0 && (
              <Typography variant="caption" color="error">
                Fix: {invalid.join(", ")}.
              </Typography>
            )}
            {real && missing.length > 0 && (
              <Typography variant="caption" color="text.secondary">
                Still needed: {missing.join(", ")}.
              </Typography>
            )}
          </Stack>
          {test && <ConnectionTestResults test={test} onUseFps={setCameraFps} />}
        </CardContent>
      </Card>
      <ConnectionHelpCard network={network} />
      {wizard && (
        <CalibrationWizard
          role={wizard.role}
          device={wizard.device}
          name={wizard.name}
          title={wizard.title}
          onClose={() => setWizard(null)}
          onSaved={() => {
            wizard.apply();
            setScan((current) =>
              current
                ? { ...current, calibrations: [...new Set([...current.calibrations, wizard.name])] }
                : current,
            );
            void queryClient.invalidateQueries({ queryKey: queryKeys.deviceScan });
          }}
        />
      )}
    </Stack>
  );
}
