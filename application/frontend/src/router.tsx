import { Navigate, type RouteObject } from "react-router";
import { CircularProgress, Stack } from "@mui/material";
import { AppError, PageError } from "./components/RouteError";
import { navigation } from "./navigation";
import type { Page } from "./types";
import { WorkspaceLayout } from "./workspace/WorkspaceLayout";

import { Component as Overview } from "./routes/OverviewRoute";

/** The landing page ships with the shell; every other page is its own chunk, loaded on first visit. */
const pages: Record<Exclude<Page, "overview">, RouteObject["lazy"]> = {
  projects: () => import("./routes/ProjectsRoute"),
  cell: () => import("./routes/CellRoute"),
  devices: () => import("./routes/ComponentsRoute"),
  record: () => import("./routes/RecordRoute"),
  episodes: () => import("./routes/EpisodesRoute"),
  dataset: () => import("./routes/DatasetRoute"),
  train: () => import("./routes/TrainRoute"),
  deploy: () => import("./routes/DeployRoute"),
  settings: () => import("./routes/SettingsRoute"),
};

/** Loads every page chunk now, e.g. so later navigation never waits on the network. */
export const preloadPages = () =>
  Promise.all(Object.values(pages).map((load) => (typeof load === "function" ? load() : null)));

export const routes: RouteObject[] = [
  {
    path: "/",
    Component: WorkspaceLayout,
    ErrorBoundary: AppError,
    // Shown while the first page of a deep link loads.
    HydrateFallback: () => (
      <Stack alignItems="center" sx={{ py: 12 }}>
        <CircularProgress aria-label="Loading MRP Studio" />
      </Stack>
    ),
    children: [
      {
        // A page that crashes is replaced by an error; the shell and navigation stay usable.
        ErrorBoundary: PageError,
        children: [
          { index: true, Component: Overview },
          ...navigation.flatMap(({ id, path }): RouteObject[] =>
            id === "overview" ? [] : [{ path, lazy: pages[id] }],
          ),
          { path: "*", element: <Navigate to="/" replace /> },
        ],
      },
    ],
  },
];
