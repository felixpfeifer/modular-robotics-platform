import type { EpisodeDetail } from "../types";
import { get, path, post } from "./client";

export const getEpisode = (id: string) => get<EpisodeDetail>(path`/api/v1/episodes/${id}`);
export const deleteEpisode = (id: string) =>
  post(path`/api/v1/episodes/${id}/delete`, { confirm: true });
