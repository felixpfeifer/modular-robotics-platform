"""HTTP routes grouped by the application workflows they serve."""

import logging
import os
import threading
import zipfile

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import api_models as models
from . import configbundle, dataset_validation
from .api_boundary import archive_upload
from .errors import AppError
from .service import Application
from .storage import Row

ZIP_MEDIA_TYPES = ("application/zip",)
BUNDLE_MEDIA_TYPES = ("application/gzip", "application/x-gzip", "application/octet-stream")
ZIP_LIMIT = 8 * 1024**3


def body_data(body: BaseModel) -> Row:
    return body.model_dump(exclude_unset=True)


def write_zip(out, folder):
    """Stream a dataset folder as an uncompressed zip."""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path in sorted(folder.rglob("*")):
            if not path.is_symlink() and path.is_file():
                archive.write(path, path.relative_to(folder).as_posix())


def projects_and_cells(app: Application) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/catalog", tags=["Projects"], summary="List supported cell components and tasks")
    def catalog():
        return app.catalog()

    @router.get(
        "/api/v1/cameras", tags=["Cameras"], summary="List camera models: built-in, discovered, custom"
    )
    def cameras(refresh: bool = Query(False)):
        return app.cameras(refresh=refresh)

    @router.post("/api/v1/cameras", tags=["Cameras"], summary="Add or replace a custom camera model")
    def add_camera(
        body: dict = Body(
            ...,
            examples=[
                {
                    "id": "acme_x1",
                    "label": "Acme X1",
                    "image": "acme/camera-x1:1.0",
                    "access": "usb_bus",
                    "probe_command": ["ros2", "run", "camera_acme", "camera_node"],
                    "trusted": True,
                    "pull": True,
                }
            ],
        ),
    ):
        return app.add_camera_model(body)

    @router.post(
        "/api/v1/cameras/{model_id}/delete", tags=["Cameras"], summary="Remove a custom camera model"
    )
    def delete_camera(model_id: str):
        return app.delete_camera_model(model_id)

    @router.post(
        "/api/v1/cameras/{model_id}/pull", tags=["Cameras"], summary="Pull a camera model's driver image"
    )
    def pull_camera(model_id: str):
        return app.pull_camera_model(model_id)

    @router.post("/api/v1/projects", tags=["Projects"], summary="Create a project")
    def create_project(body: models.Project):
        return app.create_project(body_data(body))

    @router.post(
        "/api/v1/projects/{project_id}/cell", tags=["Projects"], summary="Configure a project's cell"
    )
    def set_cell(project_id: str, body: models.CellUpdate):
        return app.set_cell(project_id, body_data(body))

    @router.get(
        "/api/v1/projects/{project_id}/workflow", tags=["Projects"], summary="Get a project's workflow"
    )
    def workflow(project_id: str):
        return app.workflow(project_id)

    @router.post("/api/v1/projects/{project_id}/rename", tags=["Projects"], summary="Rename a project")
    def rename_project(project_id: str, body: models.Rename):
        return app.rename_project(project_id, body_data(body))

    @router.post(
        "/api/v1/projects/{project_id}/delete",
        tags=["Projects"],
        summary="Delete a project and its derived data (recordings are kept)",
    )
    def delete_project(project_id: str, body: models.Confirm):
        return app.delete_project(project_id, body_data(body))

    @router.post(
        "/api/v1/projects/{project_id}/layout",
        tags=["Projects"],
        summary="Save a project's modular cell layout",
    )
    def set_layout(project_id: str, body: models.LayoutUpdate):
        return app.set_layout(project_id, body_data(body))

    @router.get("/api/v1/cell/plan", tags=["Cell"], summary="Review the cell deployment plan")
    def cell_plan(project_id: str | None = Query(None)):
        return app.cell("plan", project_id)

    @router.get("/api/v1/cell/status", tags=["Cell"], summary="Inspect cell container status")
    def cell_status(project_id: str | None = Query(None)):
        return app.cell("status", project_id)

    @router.post("/api/v1/cell/up", tags=["Cell"], summary="Start the cell")
    def cell_up(body: dict = Body(..., examples=[{"project_id": "…", "operator_confirmed": False}])):
        return app.cell("up", body.get("project_id"), body)

    @router.post("/api/v1/cell/down", tags=["Cell"], summary="Stop the cell, retaining volumes")
    def cell_down(body: dict = Body(..., examples=[{}])):
        return app.cell("down", body.get("project_id"), body)

    @router.get("/api/v1/devices/scan", tags=["Devices"], summary="List serial ports and cameras")
    def devices_scan():
        return app.devices("scan")

    @router.get("/api/v1/network", tags=["Devices"], summary="Show the cell's ROS domain and router address")
    def network():
        return app.devices("network")

    @router.post(
        "/api/v1/devices/{operation}",
        tags=["Devices"],
        summary="Probe an arm, identify the leader, snapshot a camera or step the calibration wizard",
    )
    def devices_operation(operation: str, body: dict = Body(...)):
        return app.devices(operation, body)

    @router.post(
        "/api/v1/projects/{project_id}/cell/test",
        tags=["Cell"],
        summary="Read-only connection test of the project's real devices",
    )
    def cell_test(project_id: str):
        return app.cell_test(project_id)

    @router.post("/api/v1/control", tags=["Cell"], summary="Select the command source")
    def control(body: models.Control):
        return app.select_source(body_data(body))

    return router


def recordings(app: Application) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/episodes", tags=["Recordings"], summary="List recorder artifacts")
    def episodes():
        return app.episodes()

    @router.get(
        "/api/v1/episodes/{episode_id}",
        tags=["Recordings"],
        summary="Get an episode and its validation findings",
    )
    def episode(episode_id: str):
        return app.episode_detail(episode_id)

    @router.get(
        "/api/v1/episodes/{episode_id}/recording.mcap",
        tags=["Recordings"],
        summary="Download an episode's raw MCAP file",
        response_class=FileResponse,
        responses={200: {"content": {"application/octet-stream": {}}}},
    )
    def episode_mcap(episode_id: str):
        path = app.episode_mcap(episode_id)
        return FileResponse(path, media_type="application/octet-stream", filename=f"{episode_id}.mcap")

    @router.post(
        "/api/v1/episodes/{episode_id}/delete",
        tags=["Recordings"],
        summary="Delete a recorded episode from disk",
    )
    def delete_episode(episode_id: str, body: models.Confirm):
        return app.delete_episode(episode_id, body_data(body))

    @router.post(
        "/api/v1/sessions",
        tags=["Recordings"],
        summary="Start a recording",
        response_model=models.SessionResult,
    )
    def start(body: models.Session):
        return app.start(body_data(body))

    @router.post(
        "/api/v1/sessions/{episode_id}/mark",
        tags=["Recordings"],
        summary="Mark, annotate or cancel a recording",
        response_model=models.MarkResult,
    )
    def mark(episode_id: str, body: models.Mark):
        return app.mark(episode_id, body_data(body))

    return router


def datasets(app: Application) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/v1/exports",
        tags=["Datasets"],
        summary="Export accepted recordings",
        response_model=models.JobResult,
    )
    def export(body: models.Export):
        return app.export(body_data(body))

    @router.get(
        "/api/v1/exports/{export_id}/dataset.zip",
        tags=["Datasets"],
        summary="Download an exported dataset",
        response_class=StreamingResponse,
        responses={200: {"content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}}},
    )
    def dataset(export_id: str):
        folder, _ = app.dataset_folder(export_id)
        read_fd, write_fd = os.pipe()

        def produce():
            try:
                with os.fdopen(write_fd, "wb") as output:
                    write_zip(output, folder)
            except (BrokenPipeError, ConnectionResetError):
                pass  # The client stopped downloading.
            except Exception:
                logging.exception("Dataset ZIP streaming failed")

        def chunks():
            with os.fdopen(read_fd, "rb") as source:
                while chunk := source.read(1024 * 1024):
                    yield chunk

        threading.Thread(target=produce, daemon=True, name="dataset-zip").start()
        return StreamingResponse(
            chunks(),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="lerobot-dataset.zip"'},
        )

    @router.post(
        "/api/v1/uploads",
        tags=["Datasets"],
        summary="Upload an exported dataset to Hugging Face",
        response_model=models.UploadResult,
    )
    def upload(body: models.Upload):
        return app.upload(body_data(body))

    @router.post("/api/v1/datasets/validate-hub", tags=["Datasets"])
    def validate_hub_dataset(body: models.DatasetValidation):
        try:
            return dataset_validation.validate_hub(body.repo_id, app._hub_token())
        except dataset_validation.hub.HubError as exc:
            raise AppError(str(exc), 502) from exc

    @router.post("/api/v1/datasets/validate-zip", tags=["Datasets"])
    async def validate_dataset_zip(request: Request):
        async with archive_upload(
            request,
            app.data_dir,
            filename="dataset.zip",
            media_types=ZIP_MEDIA_TYPES,
            limit=ZIP_LIMIT,
            label="ZIP",
        ) as archive:
            return await run_in_threadpool(dataset_validation.validate_zip, archive)

    return router


def training_and_models(app: Application) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/v1/model-uploads",
        tags=["Models and policy"],
        summary="Upload a local model to Hugging Face",
        response_model=models.UploadResult,
    )
    def upload_model(body: models.ModelUpload):
        return app.upload_model(body_data(body))

    @router.post(
        "/api/v1/trainings",
        tags=["Training"],
        summary="Start training from an export",
        response_model=models.TrainingResult,
    )
    def train(body: models.Training):
        return app.train(body_data(body))

    @router.get(
        "/api/v1/trainings/{training_id}/progress",
        tags=["Training"],
        summary="Step, loss and ETA of a training",
    )
    def training_progress(training_id: str):
        return app.training_progress(training_id)

    @router.post(
        "/api/v1/trainings/{training_id}/abort",
        tags=["Training"],
        summary="Abort a running training",
        response_model=models.AbortResult,
    )
    def abort_training(training_id: str):
        return app.abort_training(training_id)

    @router.get(
        "/api/v1/projects/{project_id}/notebook.ipynb",
        tags=["Training"],
        summary="Download a training notebook",
        response_class=Response,
        responses={200: {"content": {"application/x-ipynb+json": {}}}},
    )
    def notebook(
        project_id: str,
        source: str = "zip",
        repo_id: str = "",
        steps: int = 1000,
        batch_size: int = 8,
        chunk_size: int = 100,
    ):
        params = {
            "source": [source],
            "repo_id": [repo_id],
            "steps": [str(steps)],
            "batch_size": [str(batch_size)],
            "chunk_size": [str(chunk_size)],
        }
        return Response(
            app.notebook_for(project_id, params),
            media_type="application/x-ipynb+json",
            headers={"Content-Disposition": 'attachment; filename="mrp-train-act.ipynb"'},
        )

    @router.post("/api/v1/policy", tags=["Models and policy"], summary="Start or stop policy deployment")
    def policy(body: models.Policy):
        return app.policy(body_data(body))

    @router.post(
        "/api/v1/models/hub",
        tags=["Models and policy"],
        summary="Import a model from Hugging Face",
        response_model=models.ImportedModelResult,
    )
    def hub_model(body: models.HubModel):
        return app.import_hub_model(body_data(body))

    @router.post(
        "/api/v1/models/import",
        tags=["Models and policy"],
        summary="Import a checkpoint ZIP",
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
            }
        },
    )
    async def import_model(request: Request, project_id: str = Query(...), label: str = ""):
        async with archive_upload(
            request,
            app.data_dir,
            filename="checkpoint.zip",
            media_types=ZIP_MEDIA_TYPES,
            limit=ZIP_LIMIT,
            label="Upload",
        ) as archive:
            return await run_in_threadpool(app.import_model_zip, project_id, label, archive)

    @router.get("/api/v1/hub/models", tags=["Hugging Face"], summary="List your Hub models")
    def hub_models(runtime: str | None = None):
        return {"items": app.hub_repos("models", runtime)}

    @router.get("/api/v1/hub/datasets", tags=["Hugging Face"], summary="List your Hub datasets")
    def hub_datasets():
        return {"items": app.hub_repos("datasets")}

    @router.post(
        "/api/v1/models/hub-ref",
        tags=["Models and policy"],
        summary="Register a Hub model without downloading",
    )
    def hub_ref(body: models.HubRef):
        return app.register_hub_model(body_data(body))

    @router.post(
        "/api/v1/launch-command", tags=["Models and policy"], summary="Docker command for a remote host"
    )
    def launch_command(body: models.LaunchCommand):
        return app.launch_command(body_data(body))

    return router


def configuration(app: Application) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/config/backups", tags=["Configuration"], summary="List saved configuration bundles")
    def config_backups():
        return app.config_backups()

    @router.post(
        "/api/v1/config/export",
        tags=["Configuration"],
        summary="Save calibration, robot profiles and cell configs as a .tar.gz in the user data volume",
    )
    def config_export(body: dict = Body(..., examples=[{}])):
        return app.config_export()

    @router.get(
        "/api/v1/config/backups/{name}", tags=["Configuration"], summary="Download a configuration bundle"
    )
    def config_download(name: str):
        return FileResponse(app.config_backup_path(name), media_type="application/gzip", filename=name)

    @router.post(
        "/api/v1/config/backups/{name}/delete", tags=["Configuration"], summary="Delete a saved bundle"
    )
    def config_delete(name: str, body: dict = Body(..., examples=[{}])):
        return app.delete_config_backup(name)

    @router.post(
        "/api/v1/config/validate",
        tags=["Configuration"],
        summary="Check a configuration bundle without importing it",
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/gzip": {"schema": {"type": "string", "format": "binary"}}},
            }
        },
    )
    async def config_validate(request: Request):
        async with archive_upload(
            request,
            app.data_dir,
            filename="bundle.tar.gz",
            media_types=BUNDLE_MEDIA_TYPES,
            limit=configbundle.MAX_COMPRESSED,
            label="Bundle",
        ) as archive:
            return await run_in_threadpool(app.config_import, archive)

    @router.post(
        "/api/v1/config/import",
        tags=["Configuration"],
        summary="Import a configuration bundle (all checks must pass; projects are added, never replaced)",
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/gzip": {"schema": {"type": "string", "format": "binary"}}},
            }
        },
    )
    async def config_import(request: Request, overwrite_calibrations: bool = Query(False)):
        async with archive_upload(
            request,
            app.data_dir,
            filename="bundle.tar.gz",
            media_types=BUNDLE_MEDIA_TYPES,
            limit=configbundle.MAX_COMPRESSED,
            label="Bundle",
        ) as archive:
            return await run_in_threadpool(
                app.config_import, archive, apply=True, overwrite_calibrations=overwrite_calibrations
            )

    @router.get("/api/v1/settings", tags=["Settings"], summary="Read public settings")
    def settings():
        return app.settings.public()

    @router.post("/api/v1/settings", tags=["Settings"], summary="Update settings; tokens are write-only")
    def update_settings(body: models.Settings):
        return app.update_settings(body_data(body))

    return router
