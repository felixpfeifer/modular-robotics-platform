import { useEffect, useRef, useState } from "react";
import { Box, Typography } from "@mui/material";
import { urls, withQuery } from "../api";
import { useReconnectingWebSocket } from "../lib/useReconnectingWebSocket";

export const cameraViewport = {
  aspectRatio: "4 / 3",
  bgcolor: "media.background",
  borderRadius: 2,
  overflow: "hidden",
  display: "grid",
  placeItems: "center",
};

/**
 * Live JPEG frames from the camera WebSocket. Without a live stream it can fall back to polling
 * a snapshot once a second (`snapshot`), for runtimes that only offer still previews.
 */
export function CameraPreview({
  label,
  camera,
  snapshot,
}: {
  label: string;
  camera?: string;
  snapshot: boolean;
}) {
  const [frame, setFrame] = useState(() => Date.now());
  const [available, setAvailable] = useState(false);
  const [connected, setConnected] = useState(false);
  const [liveFrame, setLiveFrame] = useState<string>();
  // The object URL currently shown; revoked when replaced so frames do not leak memory.
  const frameUrl = useRef<string | undefined>(undefined);
  const showFrame = (next?: string) => {
    if (frameUrl.current) URL.revokeObjectURL(frameUrl.current);
    frameUrl.current = next;
    setLiveFrame(next);
    if (!next) setAvailable(false);
  };
  useEffect(() => {
    if (connected || !snapshot) return;
    const timer = window.setInterval(() => setFrame(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [connected, snapshot]);
  useEffect(
    () => () => {
      if (frameUrl.current) URL.revokeObjectURL(frameUrl.current);
    },
    [],
  );
  useReconnectingWebSocket(withQuery("/api/v1/camera", { camera }), {
    onOpen: () => setConnected(true),
    // A text message means the camera has no frame to send right now.
    onMessage: (event) =>
      showFrame(event.data instanceof Blob ? URL.createObjectURL(event.data) : undefined),
    onClose: () => {
      showFrame(undefined);
      setConnected(false);
    },
  });
  return (
    <Box sx={cameraViewport}>
      {!available && (
        <Typography
          variant="body2"
          sx={{ color: "media.text", gridArea: "1 / 1", p: 1, textAlign: "center" }}
        >
          {snapshot ? "Camera preview unavailable." : "Waiting for camera…"}
        </Typography>
      )}
      <Box
        component="img"
        src={connected || !snapshot ? liveFrame : urls.cameraSnapshot(frame, camera)}
        alt={`${label} preview`}
        onLoad={() => setAvailable(true)}
        onError={() => setAvailable(false)}
        sx={{
          width: "100%",
          height: "100%",
          objectFit: "contain",
          gridArea: "1 / 1",
          visibility: available ? "visible" : "hidden",
        }}
      />
    </Box>
  );
}
