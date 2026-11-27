import { Alert, Card, CardContent, Stack, TextField, Typography } from "@mui/material";
import type { Selection } from "../../lib/cellSpec";

const ROLES = [
  ["leader", "Leader arm"],
  ["follower", "Follower arm"],
  ["camera", "Main camera"],
  ["side_camera", "Side camera"],
] as const;

/** Optional third-party driver images per component; empty means the default image. */
export function ImageOverridesCard({
  images,
  onChange,
}: {
  images: Selection["images"];
  onChange: (images: Selection["images"]) => void;
}) {
  return (
    <Card>
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="h6">Docker Hub images</Typography>
          <Alert severity="warning">
            Only use images you trust. They run code on the deployment host and must implement the
            selected component&apos;s existing ROS and device interfaces. Hardware tests do not
            verify third-party image behavior.
          </Alert>
          {ROLES.map(([role, label]) => (
            <TextField
              key={role}
              label={label}
              size="small"
              value={images[role] ?? ""}
              placeholder="namespace/image:tag"
              helperText="Leave empty to use the default image"
              onChange={(event) => onChange({ ...images, [role]: event.target.value })}
            />
          ))}
        </Stack>
      </CardContent>
    </Card>
  );
}
