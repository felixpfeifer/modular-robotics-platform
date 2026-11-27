import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Typography,
} from "@mui/material";
import { calibrateArm as calibrateArmStep, errorMessage, type CalibrationStep } from "../../api";
import type { ArmDevice } from "../../types";

export type Role = "leader" | "follower";

/**
 * Guides one arm through zero pose, range sweep and save. It only reads positions and writes a
 * calibration file; it never moves the servos.
 */
export function CalibrationWizard({
  role,
  device,
  name,
  title,
  onClose,
  onSaved,
}: {
  role: Role;
  device: ArmDevice;
  /** The calibration file to write; one per arm when a cell has several of a role. */
  name: string;
  title: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [step, setStep] = useState<"zero" | "range" | "save" | "done">("zero");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recording, setRecording] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const sweeping = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      sweeping.current = false;
    };
  }, []);
  const calibrate = (step: CalibrationStep) =>
    calibrateArmStep({
      role,
      port: device.port,
      serial: device.serial,
      ...step,
      // The backend names the file after the role unless told otherwise.
      ...(name !== `${role}.yaml` && { name }),
    });
  const call = async (stepName: "zero" | "save", next: "range" | "done") => {
    setBusy(true);
    setError("");
    try {
      await calibrate({ step: stepName });
      setStep(next);
      if (next === "done") onSaved();
    } catch (exc) {
      setError(errorMessage(exc, "Calibration step failed"));
    } finally {
      setBusy(false);
    }
  };
  const startSweep = async () => {
    sweeping.current = true;
    setRecording(true);
    setError("");
    try {
      do {
        await calibrate({ step: "range", seconds: 2 });
      } while (sweeping.current);
      if (mounted.current) setStep("save");
    } catch (exc) {
      if (mounted.current) setError(errorMessage(exc, "Calibration step failed"));
    } finally {
      sweeping.current = false;
      if (mounted.current) {
        setRecording(false);
        setFinishing(false);
      }
    }
  };
  const close = () => {
    sweeping.current = false;
    onClose();
  };
  return (
    <Dialog open onClose={close} fullWidth maxWidth="sm">
      <DialogTitle>Calibrate {title}</DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          <Alert severity="info">
            Stop the cell first and keep the arm unpowered or torque-off so you can move it by hand.
            This only reads positions and writes a calibration file; it never changes the servos.
          </Alert>
          {step === "zero" && (
            <Typography>
              1. Put the arm in its zero pose (all joints at the middle of their range, as in the
              SO-101 assembly guide), then capture it.
            </Typography>
          )}
          {step === "range" && (
            <Typography>
              2. Click start, then slowly move every joint through its full range, including the
              gripper. Click Finish when you have moved every joint through its range.
            </Typography>
          )}
          {step === "save" && <Typography>3. Save the calibration file for this arm.</Typography>}
          {step === "done" && <Alert severity="success">Calibration saved.</Alert>}
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={close}>{step === "done" ? "Close" : "Cancel"}</Button>
        {step === "zero" && (
          <Button variant="contained" disabled={busy} onClick={() => void call("zero", "range")}>
            Capture zero pose
          </Button>
        )}
        {step === "range" && (
          <Button
            variant="contained"
            disabled={busy || finishing}
            onClick={() => {
              if (recording) {
                sweeping.current = false;
                setFinishing(true);
              } else void startSweep();
            }}
          >
            {finishing ? "Finishing…" : recording ? "Finish range sweep" : "Start range sweep"}
          </Button>
        )}
        {step === "save" && (
          <Button variant="contained" disabled={busy} onClick={() => void call("save", "done")}>
            Save calibration
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
