"""FastAPI HTTP boundary for the recording application."""

import asyncio
import logging
import socket
import threading
from contextlib import nullcontext
from urllib.parse import urlsplit

import uvicorn
from fastapi import APIRouter, FastAPI, WebSocket
from fastapi.concurrency import contextmanager_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.websockets import WebSocketDisconnect

from . import api_models as models
from . import api_routes
from .api_boundary import ApiBoundary
from .errors import AppError
from .runtime import RuntimeErrorDetail
from .service import Application
from .webrtc import WebRtcBridge
from .webrtc import available as webrtc_available

CAMERA_PREVIEW_FPS = 10


def create_api(app: Application, allowed_hosts=(), allowed_origins=()):
    api = FastAPI(
        title="MRP Recording API",
        version="1.0.0",
        description=(
            "Manage projects, recordings, datasets and models. Use **Try it out** to send a request. "
            "For operations with a request_id, reuse the same UUID when retrying. "
            "Some operations require a running ROS cell and deployment agent."
        ),
        swagger_ui_parameters={"docExpansion": "none", "defaultModelsExpandDepth": 1},
    )
    hosts = {"localhost", "127.0.0.1", "::1", *allowed_hosts}
    origins = set(allowed_origins)
    webrtc = WebRtcBridge(app.runtime)
    api.state.webrtc = webrtc

    api.add_middleware(ApiBoundary, hosts=hosts, origins=origins)

    @api.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            {
                "error": "Invalid request: "
                + "; ".join(f"{'.'.join(str(part) for part in e['loc'])}: {e['msg']}" for e in exc.errors())
            },
            status_code=400,
        )

    @api.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=exc.headers)

    @api.exception_handler(AppError)
    async def app_error(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=exc.status)

    @api.exception_handler(ValueError)
    @api.exception_handler(RuntimeErrorDetail)
    @api.exception_handler(TimeoutError)
    async def invalid(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=400)

    @api.exception_handler(Exception)
    async def unexpected(request, exc):
        logging.getLogger(__name__).error(
            "API operation failed method=%s route=%s type=%s",
            request.method,
            getattr(request.scope.get("route"), "path", "unknown"),
            type(exc).__name__,
        )
        return JSONResponse({"error": "Operation failed. Inspect application logs."}, status_code=500)

    @api.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/docs", status_code=302)

    @api.get("/health", tags=["Status"], summary="Check application health")
    def health():
        return {"status": "ok", "mode": app.runtime.mode}

    @api.get("/api/v1/status", tags=["Status"], summary="Get runtime readiness and application state")
    def status():
        return app.status()

    live = APIRouter()

    async def accept_live_socket(websocket: WebSocket):
        host = websocket.headers.get("host", "")
        try:
            hostname = urlsplit("http://" + host).hostname
            origin = websocket.headers.get("origin")
            parsed_origin = urlsplit(origin) if origin else None
        except ValueError:
            hostname = None
            origin = None
            parsed_origin = None
        same_origin = (
            parsed_origin and parsed_origin.scheme in ("http", "https") and parsed_origin.netloc == host
        )
        if hostname not in hosts or (origin and not same_origin and origin not in origins):
            await websocket.close(code=1008)
            return False
        await websocket.accept()
        return True

    @live.websocket("/api/v1/telemetry")
    async def telemetry(websocket: WebSocket):
        if not await accept_live_socket(websocket):
            return
        try:
            while True:
                await websocket.send_json(await run_in_threadpool(app.runtime.telemetry))
                try:
                    message = await asyncio.wait_for(websocket.receive(), timeout=0.05)
                    if message["type"] == "websocket.disconnect":
                        break
                except asyncio.TimeoutError:
                    pass
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass

    @live.websocket("/api/v1/camera")
    async def camera_socket(websocket: WebSocket, camera: str | None = None):
        if not await accept_live_socket(websocket):
            return
        watch = app.runtime.watch_camera(camera) if camera is not None else nullcontext(True)
        async with contextmanager_in_threadpool(watch) as configured:
            if not configured:
                await websocket.close(code=1008)
                return
            await stream_camera(websocket, camera)

    async def stream_camera(websocket: WebSocket, camera: str | None):
        loop = asyncio.get_running_loop()
        preview_args = () if camera is None else (camera,)
        next_frame_at = loop.time()
        last_image = None
        unavailable = False
        try:
            while True:
                delay = next_frame_at - loop.time()
                if delay > 0:
                    try:
                        message = await asyncio.wait_for(websocket.receive(), timeout=delay)
                        if message["type"] == "websocket.disconnect":
                            break
                    except asyncio.TimeoutError:
                        pass
                    continue
                image = await run_in_threadpool(app.runtime.preview, *preview_args)
                if image is None:
                    if not unavailable:
                        await websocket.send_json({"available": False})
                        unavailable = True
                    last_image = None
                elif image is not last_image:
                    await websocket.send_bytes(image)
                    last_image = image
                    unavailable = False
                next_frame_at = loop.time() + 1 / CAMERA_PREVIEW_FPS
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass

    @live.get(
        "/api/v1/preview.jpg",
        tags=["Camera"],
        summary="Get the latest camera frame",
        responses={200: {"content": {"image/jpeg": {}}}, 404: {"description": "No fresh frame"}},
        response_class=Response,
    )
    def preview(camera: str | None = None):
        image = app.runtime.preview() if camera is None else app.runtime.preview(camera)
        return (
            Response(image, media_type="image/jpeg")
            if image
            else JSONResponse({"error": "No fresh camera frame."}, status_code=404)
        )

    @live.get("/api/v1/webrtc/status", tags=["Camera"], summary="Check the WebRTC bridge")
    def webrtc_status():
        return {"available": webrtc_available(), "mode": app.runtime.mode}

    @live.post("/api/v1/webrtc/offer", tags=["Camera"], summary="Create a viewer-only WebRTC connection")
    def offer(body: models.Offer):
        if not webrtc_available():
            raise AppError("WebRTC bridge is not installed. Use the JPEG preview or install aiortc.", 503)
        return webrtc.answer_sync(api_routes.body_data(body))

    api.include_router(live)
    api.include_router(api_routes.projects_and_cells(app))
    api.include_router(api_routes.recordings(app))
    api.include_router(api_routes.datasets(app))
    api.include_router(api_routes.training_and_models(app))
    api.include_router(api_routes.configuration(app))

    def openapi():
        if api.openapi_schema is None:
            schema = get_openapi(
                title=api.title, version=api.version, description=api.description, routes=api.routes
            )
            for path in schema["paths"].values():
                for operation in path.values():
                    responses = operation.get("responses", {})
                    if "422" in responses:
                        responses.pop("422")
                        responses.setdefault(
                            "400",
                            {
                                "description": "Invalid request",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"error": {"type": "string"}},
                                        }
                                    }
                                },
                            },
                        )
            api.openapi_schema = schema
        return api.openapi_schema

    api.openapi = openapi
    return api


class Server:
    """Uvicorn server with the lifecycle used by the CLI and integration tests."""

    def __init__(self, app, host, port, allowed_hosts, allowed_origins):
        self.api = create_api(app, allowed_hosts, allowed_origins)
        self.socket = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((host, port))
        self.socket.listen(2048)
        self.server_port = self.socket.getsockname()[1]
        self.done = threading.Event()
        self.running_thread = None
        self.server = uvicorn.Server(uvicorn.Config(self.api, log_level="warning", access_log=False))

    def serve_forever(self):
        self.running_thread = threading.current_thread()
        try:
            self.server.run(sockets=[self.socket])
        finally:
            self.done.set()

    def shutdown(self):
        self.server.should_exit = True
        if self.running_thread is not None and self.running_thread is not threading.current_thread():
            self.done.wait(timeout=15)

    def server_close(self):
        if self.running_thread is not None and not self.done.is_set():
            self.shutdown()
        self.socket.close()
        self.api.state.webrtc.close()


def make_server(app, host="127.0.0.1", port=8088, allowed_hosts=(), allowed_origins=()):
    return Server(app, host, port, allowed_hosts, allowed_origins)
