import { ToggleButton, ToggleButtonGroup } from "@mui/material";
import type { Mode } from "../../lib/cellSpec";

/** Mock or real for one arm; `realDisabled` when the other arm rules out a real one. */
export function ModeToggle({
  value,
  onChange,
  disabled,
  realDisabled,
  name,
}: {
  value: Mode;
  onChange: (mode: Mode) => void;
  disabled?: boolean;
  realDisabled?: boolean;
  name: string;
}) {
  return (
    <ToggleButtonGroup
      exclusive
      size="small"
      value={value}
      disabled={disabled}
      aria-label={name}
      onChange={(_, next: Mode | null) => next && onChange(next)}
    >
      <ToggleButton value="mock">Mock</ToggleButton>
      <ToggleButton value="real" disabled={realDisabled}>
        Real
      </ToggleButton>
    </ToggleButtonGroup>
  );
}
