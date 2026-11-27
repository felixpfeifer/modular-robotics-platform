"""Request limits and headers for the dashboard API."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .errors import AppError

RAW_UPLOADS = frozenset(
    {
        "/api/v1/models/import",
        "/api/v1/datasets/validate-zip",
        "/api/v1/config/validate",
        "/api/v1/config/import",
    }
)
JSON_LIMIT = 65536


def media_type(request: Request) -> str:
    return request.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


class ApiBoundary:
    def __init__(self, app: ASGIApp, hosts: set[str], origins: set[str]) -> None:
        self.app = app
        self.hosts = hosts
        self.origins = origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        path = request.url.path
        origin = request.headers.get("origin")

        async def send_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
                if path in ("/docs", "/redoc"):
                    headers["Content-Security-Policy"] = (
                        "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                        "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data: "
                        "https://fastapi.tiangolo.com; connect-src 'self'; frame-ancestors 'none'"
                    )
                else:
                    headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
                if origin and origin in self.origins:
                    headers["Access-Control-Allow-Origin"] = origin
                    headers["Vary"] = "Origin"
            await send(message)

        response = self.check_request(request, origin)
        if response:
            await response(scope, receive, send_headers)
        elif request.method == "POST" and path not in RAW_UPLOADS:
            await self.forward_json(scope, receive, send_headers)
        else:
            await self.app(scope, receive, send_headers)

    def check_request(self, request: Request, origin: str | None) -> Response | None:
        host = request.headers.get("host", "")
        try:
            hostname = urlsplit("http://" + host).hostname
        except ValueError:
            hostname = None
        if hostname not in self.hosts:
            return error("Host is not allowed.", 403)
        if request.method == "OPTIONS" and request.headers.get("access-control-request-method"):
            method = request.headers["access-control-request-method"].upper()
            requested = {
                header.strip().lower()
                for header in request.headers.get("access-control-request-headers", "").split(",")
                if header.strip()
            }
            if origin not in self.origins or method not in {"GET", "POST"} or requested - {"content-type"}:
                return error("Cross-origin request is not allowed.")
            return Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Methods": "GET, POST",
                    "Access-Control-Allow-Headers": "Content-Type",
                },
            )
        if (
            request.method in ("POST", "PUT", "PATCH", "DELETE")
            and origin
            and origin != "http://" + host
            and origin not in self.origins
        ):
            return error("Cross-origin writes are not allowed.")
        if (
            request.method == "POST"
            and request.url.path not in RAW_UPLOADS
            and media_type(request) != "application/json"
        ):
            return error("Content-Type must be application/json.")
        return None

    async def forward_json(self, scope: Scope, receive: Receive, send: Send) -> None:
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > JSON_LIMIT:
                await error(f"JSON body must contain 1–{JSON_LIMIT} bytes.")(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        if not body:
            await error(f"JSON body must contain 1–{JSON_LIMIT} bytes.")(scope, receive, send)
            return

        buffered: Message | None = {"type": "http.request", "body": bytes(body), "more_body": False}

        async def replay() -> Message:
            nonlocal buffered
            if buffered is None:
                return await receive()
            message, buffered = buffered, None
            return message

        await self.app(scope, replay, send)


@asynccontextmanager
async def archive_upload(
    request: Request,
    directory: Path,
    *,
    filename: str,
    media_types: tuple[str, ...],
    limit: int,
    label: str,
) -> AsyncIterator[Path]:
    if media_type(request) not in media_types:
        raise AppError(f"Content-Type must be {media_types[0]}.")
    try:
        length = int(request.headers.get("content-length", "0"))
    except ValueError as exc:
        raise AppError("Invalid Content-Length.") from exc
    if not 0 < length <= limit:
        raise AppError(f"{label} must be 1–{limit} bytes.")
    with TemporaryDirectory(dir=directory) as scratch:
        path = Path(scratch) / filename
        size = 0
        with path.open("wb") as output:
            try:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > length:
                        raise AppError("Upload exceeded its declared length.")
                    if chunk:
                        await run_in_threadpool(output.write, chunk)
            except ClientDisconnect as exc:
                raise AppError("Upload ended early.") from exc
        if size != length:
            raise AppError("Upload ended early.")
        yield path
