import { Card, CardContent, Typography } from "@mui/material";
import type { NetworkInfo } from "../../types";

/** The fixed ROS/Zenoh settings and how to pass USB devices through to WSL. */
export function ConnectionHelpCard({ network }: { network?: NetworkInfo }) {
  return (
    <Card>
      <CardContent>
        <Typography variant="h6">Connection setup</Typography>
        {network?.ros_domain_id && (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            ROS domain {network.ros_domain_id}, Zenoh router port {network.zenoh_port} on{" "}
            {network.zenoh_bind}. These are fixed when the application is deployed, because the
            application itself connects with them.
          </Typography>
        )}
        <Typography variant="subtitle2">USB devices on Windows with WSL</Typography>
        <Typography
          variant="body2"
          component="div"
          sx={{ fontFamily: "monospace", whiteSpace: "pre-wrap" }}
        >
          {`PowerShell (administrator):  usbipd list
                             usbipd bind --busid <BUSID>
                             usbipd attach --wsl --busid <BUSID>
WSL, once per start:         sudo modprobe uvcvideo cdc_acm ch341`}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Use the BUSID of each arm and camera from the list. Afterwards click “Scan devices”.
        </Typography>
      </CardContent>
    </Card>
  );
}
