import type { ReactNode } from "react";
import {
  Cable,
  Dataset,
  FolderOpen,
  Hub,
  ModelTraining,
  RocketLaunch,
  Settings,
  SmartToy,
  Videocam,
  VideoLibrary,
} from "@mui/icons-material";
import type { Page } from "./types";

/** Sidebar order; `path` is the page's URL, so pages can be bookmarked and reloaded. */
export const navigation: { id: Page; path: string; label: string; icon: ReactNode }[] = [
  { id: "overview", path: "/", label: "Overview", icon: <SmartToy /> },
  { id: "projects", path: "/projects", label: "Projects", icon: <FolderOpen /> },
  { id: "cell", path: "/cell", label: "Cell", icon: <Hub /> },
  { id: "devices", path: "/components", label: "Components", icon: <Cable /> },
  { id: "record", path: "/record", label: "Record", icon: <Videocam /> },
  { id: "episodes", path: "/episodes", label: "Episodes", icon: <VideoLibrary /> },
  { id: "dataset", path: "/dataset", label: "Dataset", icon: <Dataset /> },
  { id: "train", path: "/train", label: "Train", icon: <ModelTraining /> },
  { id: "deploy", path: "/deploy", label: "Deploy", icon: <RocketLaunch /> },
  { id: "settings", path: "/settings", label: "Settings", icon: <Settings /> },
];

export const pagePath = (page: Page) => navigation.find((item) => item.id === page)?.path ?? "/";

export const pageAt = (pathname: string) =>
  navigation.find((item) => item.path === pathname) ?? navigation[0];
