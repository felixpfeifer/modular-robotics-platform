import type { Catalog, Episode, LaunchCommand, LaunchRequest, NetworkInfo, Status } from "../types";
import { get, post } from "./client";

export const getStatus = () => get<Status>("/api/v1/status");
export const getCatalog = () => get<Catalog>("/api/v1/catalog");
export const getNetwork = () => get<NetworkInfo>("/api/v1/network");
export const listEpisodes = () => get<{ episodes: Episode[] }>("/api/v1/episodes");

/** The `docker run` command for a remote host; the token is only included when asked for. */
export const getLaunchCommand = (
  request: LaunchRequest & { image?: string; include_token: boolean; confirm_token: boolean },
) => post<LaunchCommand>("/api/v1/launch-command", request);
