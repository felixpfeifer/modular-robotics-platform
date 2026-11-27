"""The application's persisted recording lifecycle."""

import json
import threading
import time
import uuid
from _thread import RLock
from collections.abc import Callable
from typing import Protocol

from .errors import AppError
from .runtime import RuntimeErrorDetail
from .storage import Row, Store

Completion = Callable[[str, str, str], None]


class RecordingRuntime(Protocol):
    mode: str

    def status(self) -> Row: ...
    def start(self, episode_id: str, snapshot: Row, completed: Completion) -> None: ...
    def mark(self, episode_id: str, kind: str, annotation: str) -> None: ...


class Recording:
    def __init__(
        self,
        store: Store,
        lock: RLock,
        runtime: RecordingRuntime,
        require_runtime_preset: Callable[[str], Row],
        snapshot_for: Callable[[str], Row],
        with_cell: Callable[[Row], Row],
    ) -> None:
        self.store = store
        self.lock = lock
        self.runtime = runtime
        self.require_runtime_preset = require_runtime_preset
        self.snapshot_for = snapshot_for
        self.with_cell = with_cell
        self.callback_lock = threading.Lock()
        self.closed = False

    def start(self, request_id: str, project_id: object) -> Row:
        with self.lock:
            previous = self.store.rows("SELECT * FROM sessions WHERE request_id=?", (request_id,))
            if previous:
                if previous[0]["project_id"] != project_id:
                    raise AppError("Request ID already belongs to another project.", 409)
                return previous[0]
            projects = self.store.rows("SELECT * FROM projects WHERE id=?", (project_id,))
            if not projects:
                raise AppError("Select an existing project.")
            self.require_runtime_preset(projects[0]["id"])
            active = self.store.rows(
                "SELECT id FROM sessions WHERE state IN ('starting','recording','finalizing')"
            )
            status = self.runtime.status()
            if active or status.get("active_episode_id"):
                raise AppError("An episode is already active. Finish it before starting another.", 409)
            if not status["ready"]:
                missing = [
                    f"{check['name']}: {check['detail']}"
                    for check in status.get("checks", [])
                    if not check["ready"]
                ]
                if status.get("active_source") != "teleop":
                    missing.append("Enable teleoperation")
                raise AppError("Cell is not ready: " + "; ".join(missing or ["check recorder status"]), 409)
            ident = str(uuid.uuid4())
            snapshot = {
                **self.snapshot_for(projects[0]["preset"]),
                "project_id": projects[0]["id"],
                "mode": self.runtime.mode,
                "cell_layout": self.with_cell(dict(projects[0]))["cell_layout"],
            }
            self.store.execute(
                "INSERT INTO sessions (id,request_id,project_id,mode,state,started,snapshot) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    ident,
                    request_id,
                    projects[0]["id"],
                    self.runtime.mode,
                    "starting",
                    time.time(),
                    json.dumps(snapshot),
                ),
            )
            try:
                self.runtime.start(ident, snapshot, self.completed)
            except (RuntimeErrorDetail, TimeoutError) as exc:
                # A timed-out ROS request may still be accepted. Never retry automatically.
                self.store.execute(
                    "UPDATE sessions SET state=?,ended=?,detail=? WHERE id=? AND state='starting'",
                    (
                        "interrupted" if isinstance(exc, TimeoutError) else "failed",
                        time.time(),
                        str(exc),
                        ident,
                    ),
                )
                raise AppError(str(exc), 409) from exc
            self.store.execute(
                "UPDATE sessions SET state='recording' WHERE id=? AND state='starting'", (ident,)
            )
            return self.store.rows("SELECT * FROM sessions WHERE id=?", (ident,))[0]

    def completed(self, ident: str, state: str, detail: str) -> None:
        # A recorder callback for this episode can resolve a timed-out start.
        # An uncertain callback cannot replace an already recorded result.
        with self.callback_lock:
            if self.closed:
                return
            resolvable = state in ("recorded", "rejected")
            self.store.execute(
                "UPDATE sessions SET state=?,ended=?,detail=? WHERE id=? AND "
                "(state IN ('starting','recording','finalizing') OR (state='interrupted' AND ?))",
                (state, time.time(), detail, ident, resolvable),
            )

    def mark(self, ident: str, body: Row) -> dict[str, bool]:
        with self.lock:
            kind = body.get("kind")
            if kind not in ("success", "failure", "cancel", "annotation"):
                raise AppError("Unknown episode mark.")
            annotation = body.get("annotation", "")
            if not isinstance(annotation, str) or len(annotation) > 256:
                raise AppError("Annotation must be at most 256 characters.")
            session = self.store.rows("SELECT * FROM sessions WHERE id=?", (ident,))
            if not session:
                raise AppError("Session not found.", 404)
            if session[0]["state"] == "finalizing":
                raise AppError("This episode was already marked and is being saved and validated.", 409)
            if session[0]["state"] != "recording":
                raise AppError(f"Session is no longer recording (it is {session[0]['state']}).", 409)
            try:
                self.runtime.mark(ident, kind, annotation)
            except (RuntimeErrorDetail, TimeoutError) as exc:
                raise AppError(str(exc), 409) from exc
            if kind == "annotation":
                annotations = session[0]["annotations"] + [{"time": time.time(), "text": annotation}]
                self.store.execute(
                    "UPDATE sessions SET annotations=? WHERE id=?", (json.dumps(annotations), ident)
                )
            elif self.runtime.mode == "demo":
                self.completed(
                    ident,
                    "demo_complete" if kind == "success" else "demo_rejected",
                    "UI demo only; no MCAP or validation evidence was produced.",
                )
            else:
                self.store.execute(
                    "UPDATE sessions SET state='finalizing' WHERE id=? AND state='recording'", (ident,)
                )
            return {"accepted": True}

    def close(self) -> None:
        with self.callback_lock:
            self.closed = True
