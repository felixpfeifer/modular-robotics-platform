"""Small HTTP API and atomic persistent store for a cell document."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .model import InvalidConfig, validate
from .deploy import Deployment, PlanError, render
from .openapi import OPENAPI, SWAGGER_HTML

MAX_BODY = 1024 * 1024


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def read(self):
        with self.lock:
            return self._read()

    def _read(self):
        if not self.path.exists():
            return None, None
        doc = validate(json.loads(self.path.read_text(encoding="utf-8")))
        return doc, self.tag(doc)

    @staticmethod
    def tag(doc):
        data = json.dumps(
            doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        return '"' + hashlib.sha256(data).hexdigest() + '"'

    def write(self, doc, if_match=None, if_none_match=None):
        validate(doc)
        with self.lock:
            old, tag = self._read()
            if if_match is not None and (
                old is None or (if_match != "*" and if_match != tag)
            ):
                raise Conflict()
            if if_none_match == "*" and old is not None:
                raise Conflict()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.path.parent, delete=False
                ) as f:
                    temp = f.name
                    json.dump(doc, f, indent=2, ensure_ascii=False, allow_nan=False)
                    f.write("\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp, self.path)
            finally:
                if temp and os.path.exists(temp):
                    os.unlink(temp)
            return self.tag(doc)


class Conflict(Exception):
    pass


def make_handler(store, deployment=None):
    deployment = deployment or Deployment()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, payload, tag=None):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            if tag:
                self.send_header("ETag", tag)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/docs", "/docs/"):
                data = SWAGGER_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return self.wfile.write(data)
            if self.path == "/openapi.json":
                return self.reply(200, OPENAPI)
            if self.path == "/api/v1/deployment/status":
                return self.deploy("status")
            if self.path == "/health":
                return self.reply(200, {"status": "ok"})
            if self.path not in ("/api/v1/cell", "/api/v1/deployment/plan"):
                return self.reply(404, {"error": "not found"})
            try:
                doc, tag = store.read()
                if doc is None:
                    return self.reply(404, {"error": "cell not configured"})
                if self.path == "/api/v1/deployment/plan":
                    try:
                        return self.reply(200, render(doc), tag)
                    except PlanError as exc:
                        return self.reply(422, {"error": str(exc)})
                self.reply(200, doc, tag)
            except (OSError, ValueError) as exc:
                self.reply(500, {"error": f"cannot read configuration: {exc}"})

        def do_POST(self):
            actions = {"/api/v1/deployment/up": "up", "/api/v1/deployment/down": "down"}
            if self.path not in actions:
                return self.reply(404, {"error": "not found"})
            return self.deploy(actions[self.path])

        def deploy(self, action):
            try:
                doc = None
                tag = None
                if action == "up":
                    doc, tag = store.read()
                    if doc is None:
                        return self.reply(404, {"error": "cell not configured"})
                    expected = self.headers.get("If-Match")
                    if expected is not None and expected not in ("*", tag):
                        return self.reply(412, {"error": "configuration has changed"})
                result = deployment.run(action, doc)
                payload = {
                    "project": deployment.project,
                    "action": action,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
                if result.returncode:
                    payload["error"] = "Docker Compose command failed"
                    payload["exit_code"] = result.returncode
                    return self.reply(502, payload)
                return self.reply(200, payload, tag)
            except PlanError as exc:
                return self.reply(422, {"error": str(exc)})
            except subprocess.TimeoutExpired:
                return self.reply(
                    504,
                    {
                        "error": "Docker Compose command timed out; inspect deployment status"
                    },
                )
            except (OSError, ValueError) as exc:
                return self.reply(500, {"error": f"deployment failed: {exc}"})

        def do_PUT(self):
            if self.path != "/api/v1/cell":
                return self.reply(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", ""))
                if length < 0 or length > MAX_BODY:
                    return self.reply(413, {"error": "body too large"})
                doc = json.loads(
                    self.rfile.read(length),
                    parse_constant=lambda value: (_ for _ in ()).throw(
                        ValueError("invalid JSON constant")
                    ),
                )
                tag = store.write(
                    doc, self.headers.get("If-Match"), self.headers.get("If-None-Match")
                )
                self.reply(200, doc, tag)
            except Conflict:
                self.reply(412, {"error": "configuration has changed"})
            except (ValueError, UnicodeDecodeError, InvalidConfig) as exc:
                self.reply(400, {"error": str(exc)})
            except OSError as exc:
                self.reply(500, {"error": f"cannot save configuration: {exc}"})

    return Handler


def serve(host, port, path, project="mrp-cell"):
    return ThreadingHTTPServer(
        (host, port), make_handler(Store(path), Deployment(project))
    )
