"""Request and response models of the HTTP API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.semantic.registry import ArtifactSource, ArtifactStatus, ArtifactType

# ----- ask ---------------------------------------------------------------------------------------


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=5000)
    domain: str | None = Field(default=None, description="Defaults to the server's default domain.")
    session_id: str | None = Field(
        default=None,
        max_length=100,
        description="Groups questions into a conversation so follow-ups can refer to earlier answers.",
    )


class TableData(BaseModel):
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
    n: int = 0


class AskResponse(BaseModel):
    request_id: str
    domain: str
    question: str
    status: str = Field(description="success, validation_failed, execution_failed, clarification_needed, ...")
    answer_path: Literal["llm", "deterministic"]
    answer: str
    key_findings: list[str]
    intent: str | None
    confidence: float | None = Field(description="Set only when the model produced it.")
    interpreted_question: str
    metrics: list[Any]
    calculations: list[Any]
    sql_query: str
    sql_rationale: str
    datasets_used: list[str]
    joins_used: list[str]
    table: TableData
    truncated: bool
    chart: dict[str, Any]
    follow_up_questions: list[str]
    warnings: list[str]
    explainability: dict[str, Any]
    llm: dict[str, str | None]
    repairs: int
    latency_seconds: float


# ----- domains and data ----------------------------------------------------------------------------


class DomainSummary(BaseModel):
    id: str
    tables: list[str]
    has_baseline_package: bool


class ColumnInfo(BaseModel):
    name: str
    dtype: str
    role: str
    restricted: bool


class TableInfo(BaseModel):
    name: str
    rows: int
    columns: list[ColumnInfo]


class DomainDetail(BaseModel):
    id: str
    has_baseline_package: bool
    tables: list[TableInfo]
    counts: dict[str, int]
    starter_questions: list[str]


class CheckResult(BaseModel):
    name: str
    ok: bool
    detail: str


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)


class UploadTargetResponse(BaseModel):
    mode: Literal["presigned", "direct"]
    table: str
    filename: str
    url: str = ""
    fields: dict[str, str] = {}
    max_bytes: int


class UploadedDataset(BaseModel):
    table: str
    filename: str
    rows: int
    columns: list[str]


# ----- onboarding ----------------------------------------------------------------------------------


class OnboardRequest(BaseModel):
    force: bool = Field(default=False, description="Run again even if the data's structure is unchanged.")


class JobResponse(BaseModel):
    job_id: str
    domain: str
    status: Literal["queued", "running", "succeeded", "failed"]
    created_at: str
    updated_at: str
    result: dict[str, Any] = {}
    error: str = ""


# ----- stewardship ---------------------------------------------------------------------------------


class RegistryArtifact(BaseModel):
    artifact_type: ArtifactType
    artifact_id: str
    status: ArtifactStatus
    source: ArtifactSource
    confidence: float
    semantic_version: str
    created_at: str
    validation_message: str
    payload: dict[str, Any]


class ArtifactRef(BaseModel):
    artifact_type: ArtifactType
    artifact_id: str = Field(min_length=1, max_length=300)


# ----- batch and evaluation ------------------------------------------------------------------------


class BatchResponse(BaseModel):
    questions: int
    rows: list[dict[str, Any]]


class EvaluateResponse(BaseModel):
    summary: dict[str, Any]
    detail: list[dict[str, Any]]


# ----- system --------------------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class InfoResponse(BaseModel):
    version: str
    storage_backend: Literal["local", "aws"]
    llm_mode: str
    auth_enabled: bool
    default_domain: str
    user: str
    roles: list[str]
