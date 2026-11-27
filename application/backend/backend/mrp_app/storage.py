"""Persistent application metadata. Raw recorder artifacts remain authoritative."""

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

Row = dict[str, Any]


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    mode TEXT NOT NULL, state TEXT NOT NULL, started REAL NOT NULL,
                    ended REAL, snapshot TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
                    annotations TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                    state TEXT NOT NULL, created REAL NOT NULL, payload TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS trainings (
                    id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    state TEXT NOT NULL, created REAL NOT NULL, payload TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '', checkpoint TEXT
                );
                CREATE TABLE IF NOT EXISTS deployments (
                    id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    state TEXT NOT NULL, created REAL NOT NULL, payload TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '', ended REAL
                );
                CREATE TABLE IF NOT EXISTS models (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    source TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', path TEXT NOT NULL,
                    state TEXT NOT NULL, created REAL NOT NULL, detail TEXT NOT NULL DEFAULT '',
                    payload TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS uploads (
                    id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                    state TEXT NOT NULL, created REAL NOT NULL, payload TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '', revision TEXT
                );
            """)

        self.migrate()

    def migrate(self):
        # Projects predate per-project cells; older rows get the original mock cell.
        with self.connection() as db:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(projects)")}
            if "cell_spec" not in columns:
                db.execute("ALTER TABLE projects ADD COLUMN cell_spec TEXT")
            if "preset" not in columns:
                db.execute("ALTER TABLE projects ADD COLUMN preset TEXT")
            if "cell_layout" not in columns:
                db.execute("ALTER TABLE projects ADD COLUMN cell_layout TEXT")
            uploads = {row["name"] for row in db.execute("PRAGMA table_info(uploads)")}
            if "project_id" not in uploads:
                db.execute("ALTER TABLE uploads ADD COLUMN project_id TEXT")
            db.execute(
                "INSERT OR IGNORE INTO models (id,project_id,source,label,path,state,created,payload) "
                "SELECT id,project_id,'local_training',json_extract(payload,'$.label'),checkpoint,'complete',created,payload "
                "FROM trainings WHERE state='complete' AND checkpoint IS NOT NULL"
            )
            model_columns = {row["name"] for row in db.execute("PRAGMA table_info(models)")}
            for name, ddl in (
                ("runtime", "TEXT NOT NULL DEFAULT 'lerobot_act'"),
                ("kind", "TEXT NOT NULL DEFAULT 'local'"),
                ("repo_id", "TEXT"),
                ("revision", "TEXT"),
            ):
                if name not in model_columns:
                    db.execute(f"ALTER TABLE models ADD COLUMN {name} {ddl}")
            jobs = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
            if "project_id" not in jobs:
                db.execute("ALTER TABLE jobs ADD COLUMN project_id TEXT")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db

    def rows(self, sql: str, args: tuple[Any, ...] = ()) -> list[Row]:
        with self.connection() as db:
            result = [dict(row) for row in db.execute(sql, args)]
        for row in result:
            for name in ("snapshot", "annotations", "payload", "cell_spec", "cell_layout"):
                if row.get(name):
                    row[name] = json.loads(row[name])
        return result

    def execute(self, sql: str, args: tuple[Any, ...] = ()) -> int:
        with self.connection() as db:
            return db.execute(sql, args).rowcount

    def recover(self):
        self.execute(
            "UPDATE sessions SET state='interrupted', ended=?, detail=? "
            "WHERE state IN ('starting','recording','finalizing')",
            (time.time(), "Application restarted. Inspect recorder/artifacts before starting again."),
        )
        self.execute(
            "UPDATE jobs SET state='interrupted', detail=? WHERE state IN ('queued','running')",
            ("Application restarted. Inspect the export output; the job was not automatically retried.",),
        )
        self.execute(
            "UPDATE trainings SET state='interrupted', detail=? WHERE state IN ('queued','running')",
            ("Application restarted. Check the run's job.json in the training volume before retrying.",),
        )
        self.execute(
            "UPDATE deployments SET state='interrupted', ended=?, detail=? WHERE state IN ('starting','running')",
            (time.time(), "Application restarted. Check the policy containers and arbiter source."),
        )
        self.execute(
            "UPDATE models SET state='interrupted', detail=? WHERE state='importing'",
            ("Application restarted during import. Check the run folder before retrying.",),
        )
        self.execute(
            "UPDATE uploads SET state='interrupted', detail=? WHERE state IN ('queued','running')",
            ("Application restarted. Check the Hub repository before retrying.",),
        )
