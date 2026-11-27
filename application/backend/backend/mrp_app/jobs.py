"""Persisted background work whose external operations run on the deployment agent."""

import json
import logging
import re
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal, Protocol

from .errors import AgentRejected, AgentUnavailable, AppError
from .storage import Row, Store

logger = logging.getLogger(__name__)


class JobKind(Enum):
    EXPORT = "jobs"
    TRAINING = "trainings"
    UPLOAD = "uploads"
    IMPORT = "models"

    @property
    def active_state(self) -> str:
        return "importing" if self is JobKind.IMPORT else "running"

    @property
    def pending_state(self) -> str:
        return "importing" if self is JobKind.IMPORT else "queued"


class AgentRequest(Protocol):
    def __call__(self, base: str, path: str, payload: Row, *, timeout: int) -> Row: ...


@dataclass(frozen=True)
class Result:
    detail: str
    state: Literal["complete", "failed", "interrupted", "aborted"] = "complete"
    checkpoint: str | None = None
    revision: str | None = None


class BackgroundJobs:
    def __init__(self, store: Store, request: AgentRequest) -> None:
        self.store = store
        self.request = request
        self.lock = threading.Lock()
        self.workers: dict[tuple[JobKind, str], threading.Thread] = {}
        self.closed = False

    def start(self, kind: JobKind, ident: str, run: Callable[[], Result]) -> None:
        with self.lock:
            if self.closed:
                self._finish(
                    kind, ident, Result("Application is shutting down.", "interrupted"), kind.pending_state
                )
                return
            worker = threading.Thread(
                target=self._run,
                args=(kind, ident, run),
                name=f"mrp-{kind.name.lower()}-{ident}",
                daemon=True,
            )
            self.workers[kind, ident] = worker
            try:
                worker.start()
            except RuntimeError:
                self.workers.pop((kind, ident))
                self._finish(
                    kind,
                    ident,
                    Result("Application could not start the worker.", "failed"),
                    kind.pending_state,
                )
                logger.error("Could not start background worker operation=%s id=%s", kind.name, ident)

    def _run(self, kind: JobKind, ident: str, run: Callable[[], Result]) -> None:
        expected = kind.pending_state
        phase = "start"
        try:
            with self.lock:
                if self.closed:
                    return
                if kind is not JobKind.IMPORT and not self.store.execute(
                    f"UPDATE {kind.value} SET state='running' WHERE id=? AND state='queued'", (ident,)
                ):
                    return
            expected = kind.active_state
            phase = "run"
            try:
                result = run()
            except AgentUnavailable:
                result = Result("Agent outcome is unknown. Check the result before retrying.", "interrupted")
            except AppError:
                result = Result(
                    "Agent operation failed. Check the deployment agent and job output.", "failed"
                )
            if result.state in ("failed", "interrupted"):
                logger.warning("Background operation %s operation=%s id=%s", result.state, kind.name, ident)
            phase = "save result"
            self._settle(kind, ident, result, expected)
        except Exception as exc:
            # Exception messages and payloads can include user credentials.
            logger.error(
                "Worker error operation=%s id=%s phase=%s type=%s",
                kind.name,
                ident,
                phase,
                type(exc).__name__,
            )
            try:
                self._settle(
                    kind,
                    ident,
                    Result("Application worker failed. Check the application logs.", "failed"),
                    expected,
                )
            except sqlite3.Error:
                logger.error("Could not persist worker failure operation=%s id=%s", kind.name, ident)
        finally:
            with self.lock:
                self.workers.pop((kind, ident), None)

    def _settle(self, kind: JobKind, ident: str, result: Result, expected: str) -> None:
        with self.lock:
            if not self.closed:
                self._finish(kind, ident, result, expected)

    def _finish(self, kind: JobKind, ident: str, result: Result, expected: str) -> None:
        if kind is JobKind.TRAINING and result.checkpoint:
            with self.store.connection() as db:
                updated = db.execute(
                    "UPDATE trainings SET state=?,detail=?,checkpoint=? WHERE id=? AND state=?",
                    (result.state, result.detail, result.checkpoint, ident, expected),
                )
                if updated.rowcount:
                    db.execute(
                        "INSERT INTO models (id,project_id,source,label,path,state,created,payload) "
                        "SELECT id,project_id,'local_training',COALESCE(json_extract(payload,'$.label'),''),"
                        "checkpoint,'complete',?,payload FROM trainings WHERE id=?",
                        (time.time(), ident),
                    )
        elif kind is JobKind.UPLOAD:
            self.store.execute(
                "UPDATE uploads SET state=?,detail=?,revision=? WHERE id=? AND state=?",
                (result.state, result.detail, result.revision, ident, expected),
            )
        else:
            self.store.execute(
                f"UPDATE {kind.value} SET state=?,detail=? WHERE id=? AND state=?",
                (result.state, result.detail, ident, expected),
            )

    def wait(self, timeout: float) -> None:
        """Wait up to one deadline for the workers currently in flight."""
        with self.lock:
            workers = tuple(self.workers.values())
        deadline = time.monotonic() + timeout
        for worker in workers:
            worker.join(max(0, deadline - time.monotonic()))

    def close(self) -> None:
        with self.lock:
            if self.closed:
                return
            self.closed = True
            for kind, ident in self.workers:
                self.store.execute(
                    f"UPDATE {kind.value} SET state='interrupted',detail=? WHERE id=? AND state IN ('queued',?)",
                    (
                        "Application stopped. Check the operation output before retrying.",
                        ident,
                        kind.active_state,
                    ),
                )

    @staticmethod
    def _report(report: object, key: str, ident: str, state_key: str) -> Row:
        if not isinstance(report, dict) or report.get(key) != ident:
            raise AgentUnavailable("Agent returned an invalid or mismatched report.", 502)
        state = report.get(state_key)
        if state == "failed":
            raise AppError("Agent reported failure.", 502)
        if state != "complete":
            raise AgentUnavailable("Agent report did not establish a result.", 502)
        return report

    def export(self, agent: str, ident: str, repo_id: str, preset: str, ratio: int) -> Result:
        report = self.request(
            agent,
            "/api/v1/exports",
            {"job_id": ident, "repo_id": repo_id, "preset": preset, "downsample_hz_ratio": ratio},
            timeout=3600,
        )
        self._report(report, "job_id", ident, "state")
        return Result("Converter completed dataset reopening and frame verification.")

    def reconcile_exports(self, exports_dir: Path) -> None:
        for job in self.store.rows("SELECT id FROM jobs WHERE state IN ('interrupted','running')"):
            ident = job["id"]
            try:
                report = json.loads((exports_dir / ident / "report.json").read_text())
            except (OSError, ValueError):
                continue
            if not isinstance(report, dict) or report.get("job_id") != ident:
                continue
            state = report.get("state")
            if state in ("complete", "failed"):
                detail = (
                    "Converter completed dataset reopening and frame verification."
                    if state == "complete"
                    else "Converter failed. Check the export report and log."
                )
                self.store.execute(
                    "UPDATE jobs SET state=?,detail=? WHERE id=? AND state IN ('interrupted','running')",
                    (state, detail, ident),
                )

    def upload(self, agent: str, ident: str, payload: Row, token: str, path: str | None = None) -> Result:
        request = {
            "job_id": ident,
            **payload,
            "token": token,
            "confirm_upload": True,
            "confirm_public": payload["visibility"] == "public",
        }
        endpoint, label = "/api/v1/uploads", "Dataset"
        if path is not None:
            request["path"] = path
            endpoint, label = "/api/v1/model-uploads", "Model"
        report = self._report(self.request(agent, endpoint, request, timeout=3600), "job_id", ident, "state")
        revision = report.get("revision")
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", revision):
            raise AgentUnavailable("Agent returned an invalid upload revision.", 502)
        return Result(f"{label} uploaded and Hub revision recorded.", revision=revision)

    def train(self, agent: str, ident: str, payload: Row, model_path: Callable[[str], str]) -> Result:
        try:
            response = self.request(agent, "/api/v1/trainings", payload, timeout=86400)
        except AgentRejected as exc:
            if exc.aborted_run == ident:
                return Result("Training was aborted; no model was saved.", "aborted")
            raise
        report = self._report(response, "run_id", ident, "status")
        checkpoint = report.get("checkpoint")
        if not isinstance(checkpoint, str):
            raise AgentUnavailable("Agent returned no checkpoint location.", 502)
        normalized = model_path(checkpoint)
        if normalized.split("/", 1)[0] != ident:
            raise AgentUnavailable("Agent returned a checkpoint for another run.", 502)
        return Result("Training finished and a complete ACT checkpoint was written.", checkpoint=normalized)

    def import_hub(self, agent: str, ident: str, payload: Row, label: str, token: str | None) -> Result:
        report = self.request(
            agent,
            "/api/v1/models/hub",
            {"run_id": ident, **payload, "label": label, "token": token},
            timeout=3600,
        )
        self._report(report, "run_id", ident, "status")
        return Result("Model imported from the Hugging Face Hub.")
