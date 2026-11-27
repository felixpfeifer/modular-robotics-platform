import { createTheme } from "@mui/material";

/** App-specific colour roles, so components name what a colour is for instead of a hex value. */
type ShellPalette = {
  /** Sidebar background. */
  background: string;
  /** Navigation items and links. */
  text: string;
  /** Section headings and captions; at least 4.5:1 on `background`. */
  muted: string;
  selected: string;
  fieldBackground: string;
  fieldBorder: string;
  icon: string;
  brandBackground: string;
  brandText: string;
};
type MediaPalette = { background: string; text: string };
type SurfacePalette = {
  /** Empty states and inset panels inside cards. */
  subtle: string;
  /** Highlighted rows: the active project, a finished stage. */
  active: string;
  /** Stages that cannot start yet. */
  inactive: string;
  /** Placeholder icons in empty states. */
  placeholder: string;
};
type HeroPalette = {
  background: string;
  overline: string;
  text: string;
  action: string;
  actionHover: string;
  actionText: string;
};
type StatusPalette = { onlineBackground: string; onlineText: string; offlineBackground: string };

declare module "@mui/material/styles" {
  interface Palette {
    shell: ShellPalette;
    media: MediaPalette;
    surface: SurfacePalette;
    hero: HeroPalette;
    connection: StatusPalette;
  }
  interface PaletteOptions {
    shell?: ShellPalette;
    media?: MediaPalette;
    surface?: SurfacePalette;
    hero?: HeroPalette;
    connection?: StatusPalette;
  }
}

const divider = "#e5ebe7";

export const theme = createTheme({
  palette: {
    primary: { main: "#245c56", dark: "#17423e", light: "#e4f1ec" },
    secondary: { main: "#c8754e" },
    background: { default: "#f4f6f3", paper: "#ffffff" },
    // #5f6d68 keeps body text at ≥ 4.5:1 (WCAG AA) on both the page and card backgrounds.
    text: { primary: "#1d302d", secondary: "#5f6d68" },
    divider,
    shell: {
      background: "#1d3731",
      text: "#b8cbc3",
      muted: "#9bb2aa",
      selected: "#36584d",
      fieldBackground: "#27443e",
      fieldBorder: "#476158",
      icon: "#bcd0c8",
      brandBackground: "#bce0ce",
      brandText: "#204b43",
    },
    media: { background: "#172b27", text: "#a9c2b5" },
    surface: { subtle: "#f8faf8", active: "#f0f7f2", inactive: "#f6f7f6", placeholder: "#9bb5a7" },
    hero: {
      background: "#254c42",
      overline: "#b9d9c9",
      text: "#c5dcd2",
      action: "#cbe9d7",
      actionHover: "#b9ddc7",
      actionText: "#183e32",
    },
    connection: {
      onlineBackground: "#e8f3ed",
      onlineText: "#356f52",
      offlineBackground: "#f1f3f1",
    },
  },
  shape: { borderRadius: 12 },
  typography: {
    // Bundled with the app (see main.tsx), so it also renders on machines without internet.
    fontFamily: '"Inter Variable", "Helvetica Neue", system-ui, sans-serif',
    h4: { fontWeight: 700, letterSpacing: "-0.035em" },
    h6: { fontWeight: 700, letterSpacing: "-0.02em" },
    button: { fontWeight: 650, textTransform: "none" },
    overline: { fontWeight: 700, letterSpacing: "0.12em" },
  },
  components: {
    MuiCard: {
      styleOverrides: {
        root: { boxShadow: "0 3px 18px rgba(29, 48, 45, .035)", border: `1px solid ${divider}` },
      },
    },
    MuiCardContent: {
      styleOverrides: { root: { padding: 24, "&:last-child": { paddingBottom: 24 } } },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: { root: { borderRadius: 9, padding: "9px 16px" } },
    },
    MuiChip: { styleOverrides: { root: { fontWeight: 600 } } },
  },
});
