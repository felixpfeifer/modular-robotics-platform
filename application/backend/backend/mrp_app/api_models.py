"""Request contracts used for validation and the interactive API reference."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ID = "123e4567-e89b-42d3-a456-426614174000"


class Body(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)


class Cell(Body):
    leader: str | None = Field(default=None, examples=["mock"])
    follower: str | None = Field(default=None, examples=["mock"])
    camera: str | None = Field(default=None, examples=["synthetic"])
    arms: list[dict] | None = None
    cameras: list[dict] | None = None
    task_id: str = Field(examples=["pipeline_check"])
    leader_model: str = Field(
        default="so101",
        examples=["so101"],
        description="Arm model id from catalog.arms.models; default so101.",
    )
    follower_model: str = Field(
        default="so101",
        examples=["so101"],
        description="Arm model id from catalog.arms.models; default so101.",
    )
    images: dict[str, str] | None = None


class Project(Body):
    name: str = Field(min_length=1, max_length=80, examples=["Tabletop collection"])
    cell: Cell | None = None


class Rename(Body):
    name: str = Field(min_length=1, max_length=80, examples=["Pick and place v2"])


class Confirm(Body):
    confirm: bool = Field(description="Must be true; deletion cannot be undone.")


class LayoutUpdate(Body):
    layout: dict = Field(
        description="Cell layout (mrp-cell-layout/v1): workspace size and a list of modules. "
        "See GET /api/v1/catalog for module types and templates."
    )


class CellUpdate(Body):
    cell: Cell


class Session(Body):
    request_id: str = Field(examples=[ID], description="Canonical UUID; reuse it when retrying.")
    project_id: str = Field(examples=[ID])


class Mark(Body):
    kind: Literal["success", "failure", "annotation", "cancel"]
    annotation: str = Field(default="", max_length=256)


class Control(Body):
    source: Literal["teleop", "policy", "none"]
    confirm_policy: bool = Field(default=False, description="Must be true to select policy control.")


class Export(Session):
    episode_ids: list[str] = Field(max_length=1000, examples=[[ID]])
    repo_id: str = Field(
        default="local/mock-so101", description="Local dataset identifier in namespace/name form."
    )
    downsample_hz_ratio: int = Field(
        default=1, ge=1, le=120, description="Keep every Nth frame; output FPS must be an integer."
    )


class TrainingSettings(Body):
    steps: int = Field(default=1000, ge=1, le=200000)
    batch_size: int = Field(default=8, ge=1, le=256)
    chunk_size: int = Field(default=100, ge=1, le=200)
    smoke: bool = False


class Training(Session):
    runtime: str = "lerobot_act"
    target: str = "local"
    export_id: str = Field(examples=[ID])
    settings: TrainingSettings | None = None
    base_model: str | None = None
    label: str = Field(default="", max_length=80)
    device: Literal["auto", "cuda", "cpu"] = "auto"
    confirm_cpu: bool = False


class Policy(Session):
    action: Literal["start", "stop"]
    model_id: str | None = None
    model_path: str | None = None
    runtime: str = "lerobot_act"
    target: str = "local"


class HubRef(Session):
    repo_id: str = Field(examples=["namespace/model"])
    runtime: str = Field(examples=["groot"])
    revision: str | None = None
    label: str = ""


class LaunchCommand(Body):
    purpose: Literal["serve", "train"]
    runtime: str
    image: str | None = None
    target: str | None = None
    repo_id: str | None = None
    revision: str | None = None
    steps: int = Field(default=1000, ge=1, le=200000)
    batch_size: int = Field(default=8, ge=1, le=256)
    include_token: bool = False
    confirm_token: bool = False


class Settings(Body):
    hf_token: str | None = Field(default=None, json_schema_extra={"writeOnly": True})
    hf_namespace: str | None = None
    clear_hf_token: bool = False
    target_upsert: dict | None = Field(
        default=None,
        description="Remote policy server: id, name, runtime, url, token_mode (saved|own|none), token.",
    )
    target_delete: str | None = None


class HubModel(Session):
    repo_id: str = Field(examples=["namespace/model"])
    revision: str | None = None
    subfolder: str = ""
    label: str = ""
    use_saved_token: bool = False


class Upload(Body):
    request_id: str = Field(examples=[ID])
    export_id: str = Field(examples=[ID])
    repo_id: str = Field(examples=["namespace/dataset"])
    visibility: Literal["private", "public"] = "private"
    token: str | None = Field(default=None, json_schema_extra={"writeOnly": True})
    use_saved_token: bool = False
    confirm_upload: bool = Field(description="Must be true to upload.")
    confirm_public: bool = Field(default=False, description="Must be true for public uploads.")


class ModelUpload(Body):
    request_id: str = Field(examples=[ID])
    model_id: str = Field(examples=[ID])
    repo_id: str = Field(examples=["namespace/model"])
    visibility: Literal["private", "public"] = "private"
    confirm_upload: bool
    confirm_public: bool = False


class DatasetValidation(Body):
    repo_id: str


class Offer(Body):
    type: Literal["offer"]
    sdp: str


class Result(BaseModel):
    model_config = ConfigDict(extra="allow")


class Annotation(Result):
    time: float
    text: str


class SessionResult(Result):
    id: str
    request_id: str
    project_id: str
    mode: str
    state: str
    started: float
    ended: float | None
    detail: str
    annotations: list[Annotation]
    snapshot: dict


class MarkResult(BaseModel):
    accepted: bool


class JobResult(Result):
    id: str
    request_id: str
    project_id: str | None
    state: str
    created: float
    payload: dict
    detail: str


class TrainingResult(JobResult):
    checkpoint: str | None


class UploadResult(JobResult):
    revision: str | None


class ImportedModelResult(Result):
    id: str
    project_id: str
    source: str
    label: str
    path: str
    state: str
    created: float
    detail: str
    payload: dict


class AbortResult(BaseModel):
    id: str
    state: Literal["aborting"]
