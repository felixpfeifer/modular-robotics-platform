"""Small local HTTP boundary with explicit JSON and same-origin writes."""

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit


class LocalHandler(BaseHTTPRequestHandler):
    server_version = "MRP/0.1"

    def reply(self, status, payload, content_type="application/json; charset=utf-8"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        origin = self.headers.get("Origin")
        if origin and origin in getattr(self.server, "allowed_origins", set()):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' blob:; media-src 'self' blob:; frame-ancestors 'none'",
        )
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def valid_host(self):
        try:
            hostname = urlsplit("http://" + self.headers.get("Host", "")).hostname
            return hostname in self.server.allowed_hosts
        except ValueError:
            return False

    def body(self):
        if not self.valid_host():
            raise ValueError("Host is not allowed.")
        origin = self.headers.get("Origin")
        if (
            origin
            and origin != "http://" + self.headers.get("Host")
            and origin not in self.server.allowed_origins
        ):
            raise ValueError("Cross-origin writes are not allowed.")
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type must be application/json.")
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 65536:
            raise ValueError("JSON body must contain 1–65536 bytes.")
        self.connection.settimeout(10)
        value = json.loads(
            self.rfile.read(length),
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Invalid JSON constant.")),
        )
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object.")
        return value

    def check_write(self):
        if not self.valid_host():
            raise ValueError("Host is not allowed.")
        origin = self.headers.get("Origin")
        if (
            origin
            and origin != "http://" + self.headers.get("Host")
            and origin not in self.server.allowed_origins
        ):
            raise ValueError("Cross-origin writes are not allowed.")

    def save_upload(self, destination, content_type, limit):
        """Stream a binary request body to `destination`; returns its size."""
        self.check_write()
        if self.headers.get_content_type() != content_type:
            raise ValueError(f"Content-Type must be {content_type}.")
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= limit:
            raise ValueError(f"Upload must be 1–{limit} bytes.")
        self.connection.settimeout(60)
        remaining = length
        with open(destination, "wb") as out:
            while remaining:
                chunk = self.rfile.read(min(1 << 20, remaining))
                if not chunk:
                    raise ValueError("Upload ended early.")
                out.write(chunk)
                remaining -= len(chunk)
        return length

    def reply_stream(self, content_type, filename, writer):
        """Send a response of unknown length (connection closes at the end)."""
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            writer(self.wfile)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format, *args):
        # Never log body contents, project names or recorded annotations.
        pass
