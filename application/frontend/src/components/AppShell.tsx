import { useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router";
import { Code, Menu as MenuIcon, SmartToy } from "@mui/icons-material";
import {
  AppBar,
  Box,
  Chip,
  Drawer,
  FormControl,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  MenuItem,
  Select,
  Toolbar,
  Typography,
} from "@mui/material";
import { urls } from "../api";
import { navigation, pageAt } from "../navigation";
import type { Status } from "../types";

export function AppShell({
  status,
  projectId,
  setProjectId,
  connected,
  children,
}: {
  status: Status | null;
  /** False while the last status poll failed; the shown data may be stale. */
  connected: boolean;
  projectId: string;
  setProjectId: (id: string) => void;
  children: ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const current = pageAt(useLocation().pathname);
  const sidebar = (
    <Box sx={{ height: "100%", display: "flex", flexDirection: "column", p: 2 }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, px: 1, py: 2, mb: 3 }}>
        <Box
          sx={{
            width: 38,
            height: 38,
            borderRadius: 2,
            bgcolor: "shell.brandBackground",
            color: "shell.brandText",
            display: "grid",
            placeItems: "center",
          }}
        >
          <SmartToy fontSize="small" />
        </Box>
        <Box>
          <Typography fontWeight={750} lineHeight={1.1}>
            MRP Studio
          </Typography>
          <Typography variant="caption" sx={{ color: "shell.muted" }}>
            ROBOTICS WORKSPACE
          </Typography>
        </Box>
      </Box>
      <Typography variant="overline" sx={{ color: "shell.muted", px: 1, mb: 1, fontSize: 10 }}>
        WORKSPACE
      </Typography>
      <FormControl
        fullWidth
        size="small"
        sx={{
          mb: 3,
          "& .MuiOutlinedInput-root": {
            color: "white",
            bgcolor: "shell.fieldBackground",
            "& fieldset": { borderColor: "shell.fieldBorder" },
          },
          "& .MuiSvgIcon-root": { color: "shell.icon" },
        }}
      >
        <Select
          value={projectId}
          displayEmpty
          inputProps={{ "aria-label": "Active project" }}
          onChange={(event) => setProjectId(event.target.value)}
          renderValue={(value) =>
            status?.projects.find((p) => p.id === value)?.name || "Select a project"
          }
        >
          {status?.projects.map((project) => (
            <MenuItem key={project.id} value={project.id}>
              {project.name}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      <Typography variant="overline" sx={{ color: "shell.muted", px: 1, mb: 1, fontSize: 10 }}>
        NAVIGATION
      </Typography>
      <List
        disablePadding
        sx={{
          "& .MuiListItemButton-root": {
            borderRadius: 2,
            mb: 0.5,
            color: "shell.text",
            minHeight: 44,
          },
          "& .Mui-selected, & .Mui-selected:hover": { bgcolor: "shell.selected", color: "#fff" },
          "& .MuiListItemIcon-root": { color: "inherit", minWidth: 38 },
          "& .MuiListItemText-primary": { fontSize: 14, fontWeight: 600 },
        }}
      >
        {navigation.map((item) => (
          <ListItemButton
            key={item.id}
            component={NavLink}
            to={item.path}
            selected={current.id === item.id}
            onClick={() => setMobileOpen(false)}
          >
            <ListItemIcon>{item.icon}</ListItemIcon>
            <ListItemText primary={item.label} />
          </ListItemButton>
        ))}
      </List>
      <Box sx={{ mt: "auto", pt: 3 }}>
        <ListItemButton
          component="a"
          href={urls.docs()}
          target="_blank"
          rel="noopener noreferrer"
          sx={{ borderRadius: 2, color: "shell.text" }}
        >
          <ListItemIcon sx={{ color: "inherit", minWidth: 38 }}>
            <Code />
          </ListItemIcon>
          <ListItemText
            primary="API documentation"
            slotProps={{ primary: { sx: { fontSize: 13 } } }}
          />
        </ListItemButton>
        <Typography variant="caption" sx={{ display: "block", px: 2, pt: 2, color: "shell.muted" }}>
          MRP CONTROL STUDIO · V0.2
        </Typography>
      </Box>
    </Box>
  );
  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <Drawer
        variant="permanent"
        sx={{
          display: { xs: "none", md: "block" },
          width: 248,
          flexShrink: 0,
          "& .MuiDrawer-paper": {
            width: 248,
            bgcolor: "shell.background",
            color: "white",
            border: 0,
          },
        }}
      >
        {sidebar}
      </Drawer>
      <Drawer
        variant="temporary"
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        sx={{ "& .MuiDrawer-paper": { width: 248, bgcolor: "shell.background", color: "white" } }}
      >
        {sidebar}
      </Drawer>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <AppBar
          position="sticky"
          color="inherit"
          elevation={0}
          sx={{
            bgcolor: "rgba(255,255,255,.94)",
            borderBottom: "1px solid",
            borderColor: "divider",
          }}
        >
          <Toolbar sx={{ minHeight: "72px !important", px: { xs: 2, md: 4 } }}>
            <IconButton
              aria-label="Open navigation"
              onClick={() => setMobileOpen(true)}
              sx={{ display: { md: "none" }, mr: 1 }}
            >
              <MenuIcon />
            </IconButton>
            <Box sx={{ flex: 1 }}>
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{ display: { xs: "none", sm: "block" } }}
              >
                WORKSPACE / {current.label.toUpperCase()}
              </Typography>
              <Typography component="h1" fontWeight={700}>
                {current.label}
              </Typography>
            </Box>
            <Chip
              size="small"
              role="status"
              label={
                !status
                  ? "Connecting"
                  : !connected
                    ? "Disconnected"
                    : status.mode === "ros"
                      ? "ROS runtime"
                      : "Demo runtime"
              }
              sx={{
                bgcolor:
                  status && connected
                    ? "connection.onlineBackground"
                    : "connection.offlineBackground",
                color: status && connected ? "connection.onlineText" : "text.secondary",
                "&:before": {
                  content: '""',
                  width: 7,
                  height: 7,
                  borderRadius: "50%",
                  bgcolor: "currentColor",
                  ml: 1.2,
                },
              }}
            />
          </Toolbar>
        </AppBar>
        <Box component="main" sx={{ p: { xs: 2, sm: 3, lg: 4 }, maxWidth: 1500, mx: "auto" }}>
          {children}
        </Box>
      </Box>
    </Box>
  );
}
