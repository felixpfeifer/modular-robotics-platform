import { useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { saveCustomCamera } from "../api";
import type { CameraCatalog, CustomCameraRequest } from "../types";

/** "Acme X1 (USB)" -> "acme_x1_usb": the id a camera model gets unless the user types one. */
export function cameraIdFrom(label: string): string {
  const slug = label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const id = /^[a-z]/.test(slug) ? slug : `cam_${slug}`;
  return id.slice(0, 32).replace(/_+$/, "");
}

/** "mono=Mono, color=Color" -> {mono: "Mono", color: "Color"}; a bare "d435" uses its id as label. */
export function parseVariants(text: string): Record<string, string> {
  const variants: Record<string, string> = {};
  for (const part of text.split(",")) {
    const [id, label] = part.split("=").map((s) => s.trim());
    if (id) variants[id.toLowerCase()] = label || id;
  }
  return variants;
}

/**
 * Add a camera whose driver is a Docker image (yours or a vendor's). The image must follow the
 * MRP camera driver contract (README, "Camera drivers"): publish JPEG CompressedImage on
 * image/compressed and accept image_width, image_height, fps and serial_number/address.
 */
export function CustomCameraDialog({
  open,
  onClose,
  onSaved,
  agent,
}: {
  open: boolean;
  onClose: () => void;
  /** Called with the new model id and the refreshed camera catalogue. */
  onSaved: (id: string, cameras: CameraCatalog) => void;
  /** Whether a deployment agent is configured (only then can the image be pulled). */
  agent: boolean;
}) {
  const [label, setLabel] = useState("");
  const [id, setId] = useState("");
  const [image, setImage] = useState("");
  const [access, setAccess] = useState<CustomCameraRequest["access"]>("usb_bus");
  const [fpsType, setFpsType] = useState<CustomCameraRequest["fps_type"]>("int");
  const [command, setCommand] = useState("");
  const [variants, setVariants] = useState("");
  const [vendor, setVendor] = useState("");
  const [note, setNote] = useState("");
  const [trusted, setTrusted] = useState(false);
  const [pull, setPull] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const modelId = id || cameraIdFrom(label);
  const args = command.trim().split(/\s+/).filter(Boolean);
  const ready = Boolean(label.trim() && image.trim() && args.length && trusted && modelId);

  const save = () => {
    const body: CustomCameraRequest = {
      id: modelId,
      label: label.trim(),
      image: image.trim(),
      access,
      fps_type: fpsType,
      probe_command: args,
      trusted,
      pull: agent && pull,
    };
    const parsed = parseVariants(variants);
    if (Object.keys(parsed).length) body.variants = parsed;
    if (access === "usb_bus" && vendor.trim())
      body.usb = { vendor_id: vendor.trim().toLowerCase() };
    if (note.trim()) body.note = note.trim();
    setBusy(true);
    setError("");
    saveCustomCamera(body)
      .then((reply) => {
        if (reply.pull && !reply.pull.ok)
          setError(`Saved, but the image could not be pulled: ${reply.pull.detail}`);
        onSaved(reply.id, reply.cameras);
        if (!reply.pull || reply.pull.ok) onClose();
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Add a custom camera</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            A camera type whose driver is a Docker image. Images labelled{" "}
            <code>io.mrp.driver.kind=camera</code> on this host are listed automatically; add others
            here. The connection test on the cell setup page checks that the driver really delivers
            images.
          </Typography>
          <TextField
            size="small"
            label="Name"
            required
            placeholder="Acme X1"
            value={label}
            slotProps={{ htmlInput: { maxLength: 60 } }}
            onChange={(event) => setLabel(event.target.value)}
          />
          <TextField
            size="small"
            label="Id"
            value={modelId}
            helperText="Used in cell files; lowercase letters, digits and _"
            slotProps={{ htmlInput: { maxLength: 32 } }}
            onChange={(event) => setId(event.target.value)}
          />
          <TextField
            size="small"
            label="Docker image"
            required
            placeholder="namespace/camera-driver:1.0"
            value={image}
            onChange={(event) => setImage(event.target.value)}
          />
          <Stack direction="row" spacing={2}>
            <TextField
              select
              size="small"
              label="Connection"
              value={access}
              sx={{ flex: 1 }}
              onChange={(event) => setAccess(event.target.value as CustomCameraRequest["access"])}
            >
              <MenuItem value="usb_bus">USB (driver gets the USB bus)</MenuItem>
              <MenuItem value="network">Network (IP camera, no host device)</MenuItem>
            </TextField>
            <TextField
              select
              size="small"
              label="fps parameter"
              value={fpsType}
              sx={{ width: 160 }}
              onChange={(event) =>
                setFpsType(event.target.value as CustomCameraRequest["fps_type"])
              }
            >
              <MenuItem value="int">integer</MenuItem>
              <MenuItem value="float">double</MenuItem>
            </TextField>
          </Stack>
          <TextField
            size="small"
            label="Driver node command"
            required
            placeholder="ros2 run camera_acme camera_node"
            helperText="Starts the node inside the image; the connection test runs it with the cell's settings"
            value={command}
            onChange={(event) => setCommand(event.target.value)}
          />
          <TextField
            size="small"
            label="Variants"
            placeholder="mono=Mono, color=Color"
            value={variants}
            onChange={(event) => setVariants(event.target.value)}
          />
          {access === "usb_bus" && (
            <TextField
              size="small"
              label="USB vendor id"
              placeholder="1d6b"
              helperText="Optional: lets the connection test find the camera on USB"
              value={vendor}
              slotProps={{ htmlInput: { maxLength: 4 } }}
              onChange={(event) => setVendor(event.target.value)}
            />
          )}
          <TextField
            size="small"
            label="Note"
            value={note}
            slotProps={{ htmlInput: { maxLength: 280 } }}
            onChange={(event) => setNote(event.target.value)}
          />
          <Alert severity="warning">
            Only use images you trust. The driver runs on the deployment host
            {access === "usb_bus" ? " with access to the host's USB bus" : ""}. It never gets
            privileges or extra capabilities.
          </Alert>
          <FormControlLabel
            control={<Checkbox checked={trusted} onChange={(_, on) => setTrusted(on)} />}
            label="I trust this image"
          />
          {agent && (
            <FormControlLabel
              control={<Checkbox checked={pull} onChange={(_, on) => setPull(on)} />}
              label="Pull the image now"
            />
          )}
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button variant="contained" onClick={save} disabled={!ready || busy}>
          {busy ? "Saving…" : "Add camera"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
