import { useState } from "react";
import { errorMessage, useRefreshLive } from "../api";
import type { RunAction } from "../types";

export type Notice = { text: string; error?: boolean };
export type RecordAction =
  "starting-cell" | "stopping-cell" | "starting-episode" | "finishing-episode";

/**
 * Runs one write at a time: shows its outcome as a notice and refetches live data afterwards.
 * `busy` disables other actions meanwhile; `recordAction` says which recording step is running.
 */
export function useRunAction() {
  const refreshLive = useRefreshLive();
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState(false);
  const [recordAction, setRecordAction] = useState<RecordAction | null>(null);

  const run: RunAction = async (work, message) => {
    setBusy(true);
    try {
      await work();
      setNotice({ text: message });
      await refreshLive();
    } catch (error) {
      setNotice({ text: errorMessage(error), error: true });
    } finally {
      setBusy(false);
    }
  };
  const runRecord = async (action: RecordAction, work: () => Promise<unknown>, message: string) => {
    setRecordAction(action);
    try {
      await run(work, message);
    } finally {
      setRecordAction(null);
    }
  };
  return { run, runRecord, busy, recordAction, notice, clearNotice: () => setNotice(null) };
}
