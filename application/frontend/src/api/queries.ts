import { QueryClient, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { listBackups } from "./config";
import { scanDevices } from "./devices";
import { getEpisode } from "./episodes";
import { getWorkflow } from "./projects";
import { getCatalog, getNetwork, getStatus, listEpisodes } from "./system";
import { getTrainingProgress } from "./training";

/** Live backend state is polled at this rate while the tab is visible. */
export const POLL_MS = 2000;

export const queryKeys = {
  status: ["status"] as const,
  episodes: ["episodes"] as const,
  episode: (id: string) => ["episodes", id] as const,
  workflow: (projectId: string) => ["workflow", projectId] as const,
  /** Changes only when custom cameras are added, removed or pulled. */
  catalog: ["catalog"] as const,
  network: ["network"] as const,
  deviceScan: ["devices", "scan"] as const,
  backups: ["config", "backups"] as const,
  trainingProgress: (id: string) => ["trainings", id, "progress"] as const,
};

/**
 * Not refetched after every write: the catalog and network only change on redeploys or camera
 * edits, and a device scan probes USB hardware, so it runs on page visits and on request only.
 */
const NOT_LIVE = new Set<string>([
  queryKeys.catalog[0],
  queryKeys.network[0],
  queryKeys.deviceScan[0],
]);

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: 1, retryDelay: 500 },
      mutations: { retry: false },
    },
  });
}

/** Refetches every live query after a write, leaving the static catalog alone. */
export function useRefreshLive() {
  const client = useQueryClient();
  return useCallback(
    () =>
      client.invalidateQueries({
        predicate: (query) => !NOT_LIVE.has(String(query.queryKey[0])),
      }),
    [client],
  );
}

export function useInvalidateCatalog() {
  const client = useQueryClient();
  return useCallback(() => client.invalidateQueries({ queryKey: queryKeys.catalog }), [client]);
}

// Polling queries never retry: the next poll is the retry, and a failure must show at once.
export const useStatus = () =>
  useQuery({
    queryKey: queryKeys.status,
    queryFn: getStatus,
    refetchInterval: POLL_MS,
    retry: false,
  });

export const useEpisodes = () =>
  useQuery({
    queryKey: queryKeys.episodes,
    queryFn: async () => (await listEpisodes()).episodes,
    refetchInterval: POLL_MS,
    retry: false,
  });

export const useWorkflow = (projectId: string) =>
  useQuery({
    queryKey: queryKeys.workflow(projectId),
    queryFn: () => getWorkflow(projectId),
    enabled: Boolean(projectId),
    refetchInterval: POLL_MS,
    retry: false,
  });

export const useCatalog = () =>
  useQuery({ queryKey: queryKeys.catalog, queryFn: getCatalog, staleTime: Infinity });

export const useNetwork = () =>
  useQuery({ queryKey: queryKeys.network, queryFn: getNetwork, staleTime: Infinity });

export const useDeviceScan = () =>
  useQuery({ queryKey: queryKeys.deviceScan, queryFn: scanDevices, refetchOnWindowFocus: false });

export const useEpisode = (id: string) =>
  useQuery({ queryKey: queryKeys.episode(id), queryFn: () => getEpisode(id) });

export const useBackups = () =>
  useQuery({
    queryKey: queryKeys.backups,
    queryFn: async () => (await listBackups()).backups ?? [],
  });

export const useTrainingProgress = (id: string) =>
  useQuery({
    queryKey: queryKeys.trainingProgress(id),
    queryFn: () => getTrainingProgress(id),
    refetchInterval: 3000,
    retry: false,
  });
