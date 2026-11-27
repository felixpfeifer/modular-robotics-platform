import {
  annotateEpisode,
  markEpisode,
  setControlSource,
  startCell,
  startEpisode,
  stopCell,
} from "../api";
import { RobotTelemetryProvider } from "../components/RobotTelemetryProvider";
import { RecordPage } from "../pages/RecordPage";
import { useWorkspace } from "../workspace/WorkspaceContext";

/** Presets whose follower is a real arm, so starting the cell needs the operator's confirmation. */
const REAL_HARDWARE = new Set(["real-so101", "hwleader-so101"]);

export function Component() {
  const { status, project, projectId, sessions, episodes, busy, run, runRecord, recordAction } =
    useWorkspace();
  const { runtime } = status;
  const episodeId = runtime.active_episode_id ?? "";
  return (
    <RobotTelemetryProvider>
      <RecordPage
        runtime={runtime}
        busy={busy}
        projectId={project?.id ?? ""}
        mode={status.mode}
        layout={project?.cell_layout}
        cameras={project?.cell_spec?.cameras}
        sessions={sessions}
        episodes={episodes}
        note={(text) => void run(() => annotateEpisode(episodeId, text), "Note added.")}
        start={() =>
          void runRecord("starting-episode", () => startEpisode(projectId), "Recording started.")
        }
        mark={(kind) =>
          void runRecord(
            "finishing-episode",
            () => markEpisode(episodeId, kind),
            `Episode marked ${kind}.`,
          )
        }
        recordAction={recordAction}
        realHardware={REAL_HARDWARE.has(project?.preset ?? "")}
        mockHandover={project?.preset === "hwleader-so101"}
        cell={(confirmed) =>
          void (runtime.cell_running
            ? runRecord("stopping-cell", () => stopCell(projectId), "Cell stopped.")
            : runRecord(
                "starting-cell",
                () => startCell(projectId, Boolean(confirmed)),
                "Cell started.",
              ))
        }
        teleop={() =>
          void run(
            () => setControlSource(runtime.active_source === "teleop" ? "none" : "teleop"),
            "Control source updated.",
          )
        }
      />
    </RobotTelemetryProvider>
  );
}
