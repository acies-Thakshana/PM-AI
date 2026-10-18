"""Central configuration: environment variables, file paths and tuning defaults.

No business logic lives here. ``get_settings()`` builds one immutable ``Settings`` object from
``config/settings.yaml`` (non-secret defaults) and the environment (everything that differs per
deployment). With no AWS variables set the backend runs entirely on local files, with no login,
so ``uvicorn app.main:app`` works on a laptop. Setting the AWS variables switches every store to
S3 and DynamoDB without any code change.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from app.errors import ConfigError

BACKEND_DIR = Path(__file__).resolve().parents[1]

LLM_MODES = ("bedrock", "local")

# Every LLM call has a name. The name picks its system prompt (prompts/<name>.txt) and its model.
CALL_PLAN = "ai4bi_plan"
CALL_SQL = "ai4bi_sql"
CALL_SQL_REPAIR = "ai4bi_sql_repair"
CALL_ANSWER = "ai4bi_answer"
CALL_ONBOARDING = "ai4bi_semantic_onboarding"

# Which model tier each call uses. "strong" decides what gets built; "cheap" only writes prose.
MODEL_TIER_BY_CALL = {
    CALL_PLAN: "strong",
    CALL_SQL: "strong",
    CALL_SQL_REPAIR: "strong",
    CALL_ONBOARDING: "strong",
    CALL_ANSWER: "cheap",
}

UPLOAD_EXTENSIONS = (".csv", ".tsv", ".xlsx", ".xlsm", ".parquet", ".json", ".jsonl")

# A batch runs every question through the model, so its size is capped per request.
BATCH_MAX_QUESTIONS = 50


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    return default if not raw else raw.lower() in {"1", "true", "yes", "on"}


def _env_json(name: str) -> dict[str, Any]:
    raw = _env(name)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{name} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ConfigError(f"{name} must be a JSON object")
    return parsed


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Settings file not found: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Settings file is not valid YAML: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigError(f"Settings file must contain a mapping: {path}")
    return payload


@dataclass(frozen=True)
class Settings:
    # ----- paths ----------------------------------------------------------------------------
    data_dir: Path
    prompts_dir: Path
    visual_templates_path: Path

    # ----- AWS ------------------------------------------------------------------------------
    aws_region: str = "eu-north-1"
    bedrock_region: str = "eu-north-1"
    s3_bucket: str = ""
    ddb_registry: str = ""
    ddb_kg: str = ""
    ddb_history: str = ""
    ddb_jobs: str = ""
    ddb_audit: str = ""
    record_ttl_days: int = 30
    audit_ttl_days: int = 365

    # ----- authentication and authorization (Microsoft Entra ID) ----------------------------
    entra_tenant_id: str = ""
    entra_client_id: str = ""
    entra_required_scope: str = "access_as_user"
    allow_anon: bool = False
    role_user: str = "AI4BI.User"
    role_steward: str = "AI4BI.Steward"
    domain_groups: dict[str, tuple[str, ...]] = field(default_factory=dict)

    # ----- CORS -----------------------------------------------------------------------------
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)
    cors_allow_localhost: bool = True

    # ----- LLM ------------------------------------------------------------------------------
    llm_mode: str = "local"
    bedrock_default_model: str = ""
    bedrock_strong_model: str = ""
    bedrock_cheap_model: str = ""
    llm_max_tokens: int = 6000
    llm_temperature: float = 0.0
    bedrock_prompt_ids: dict[str, str] = field(default_factory=dict)
    prompt_cache_seconds: int = 300

    # ----- question pipeline ----------------------------------------------------------------
    default_domain: str = "service_ops"
    row_limit: int = 500
    preview_rows: int = 20
    max_repairs: int = 1
    history_turns: int = 3
    persist_episodes: bool = True
    graph_slice_limit: int = 40
    prior_sql_patterns: int = 8
    graph_max_episodes: int = 200

    # ----- onboarding -----------------------------------------------------------------------
    include_drafts: bool = False
    onboarding_sample_values: int = 10
    join_min_overlap: float = 0.8
    activation_confidence: float = 0.75
    job_workers: int = 2

    # ----- guardrails and SQL policy --------------------------------------------------------
    min_question_length: int = 3
    max_question_length: int = 1000
    blocked_patterns: tuple[dict[str, str], ...] = ()
    sql_dialect: str = "sqlite"
    forbidden_keywords: tuple[str, ...] = ()
    max_execution_steps: int = 50_000_000

    # ----- follow-ups, uploads, caching, logging --------------------------------------------
    followup_max: int = 3
    followup_templates: tuple[str, ...] = ()
    upload_max_bytes: int = 100 * 1024 * 1024
    presign_expiry_seconds: int = 900
    data_cache_seconds: int = 60
    data_cache_max_entries: int = 8
    log_level: str = "INFO"
    log_json: bool = False

    # ----- derived paths --------------------------------------------------------------------
    @property
    def samples_root(self) -> Path:
        return self.data_dir / "samples"

    @property
    def semantic_root(self) -> Path:
        return self.data_dir / "semantic"

    @property
    def local_state_root(self) -> Path:
        return self.data_dir / "local"

    @property
    def datasets_root(self) -> Path:
        return self.local_state_root / "datasets"

    # ----- derived modes --------------------------------------------------------------------
    @property
    def aws_resources(self) -> dict[str, str]:
        return {
            "S3_BUCKET": self.s3_bucket,
            "DDB_REGISTRY": self.ddb_registry,
            "DDB_KG": self.ddb_kg,
            "DDB_HISTORY": self.ddb_history,
            "DDB_JOBS": self.ddb_jobs,
            "DDB_AUDIT": self.ddb_audit,
        }

    @property
    def use_aws_storage(self) -> bool:
        return all(self.aws_resources.values())

    @property
    def storage_backend(self) -> str:
        return "aws" if self.use_aws_storage else "local"

    @property
    def auth_enabled(self) -> bool:
        return bool(self.entra_tenant_id and self.entra_client_id)

    def model_for(self, call_name: str) -> str:
        """The Bedrock model for one LLM call. ``MODEL_<CALL_NAME>`` in the environment wins."""
        override = _env("MODEL_" + call_name.upper())
        if override:
            return override
        tier = MODEL_TIER_BY_CALL.get(call_name)
        chosen = {"strong": self.bedrock_strong_model, "cheap": self.bedrock_cheap_model}.get(tier or "")
        return chosen or self.bedrock_default_model

    def validate(self) -> None:
        """Fail at startup, with every problem listed, instead of failing on the first request."""
        problems: list[str] = []
        configured = [name for name, value in self.aws_resources.items() if value]
        if configured and not self.use_aws_storage:
            missing = [name for name, value in self.aws_resources.items() if not value]
            problems.append(
                "AWS storage is partly configured. Set all of the AWS variables or none. "
                f"Missing: {', '.join(missing)}."
            )
        if bool(self.entra_tenant_id) != bool(self.entra_client_id):
            problems.append("Set both ENTRA_TENANT_ID and ENTRA_CLIENT_ID, or neither.")
        if self.use_aws_storage and not self.auth_enabled and not self.allow_anon:
            problems.append(
                "AWS storage is on but sign-in is not configured: every caller would share one identity. "
                "Set ENTRA_TENANT_ID and ENTRA_CLIENT_ID (or ALLOW_ANON=1 for a private demo)."
            )
        if self.llm_mode not in LLM_MODES:
            problems.append(f"LLM_MODE must be one of {', '.join(LLM_MODES)}, got {self.llm_mode!r}.")
        if self.llm_mode == "bedrock" and not self.bedrock_default_model:
            problems.append("LLM_MODE=bedrock needs BEDROCK_DEFAULT_MODEL (a model id or inference-profile id).")
        if problems:
            raise ConfigError(" ".join(problems))


def _tuning(settings_path: Path) -> dict[str, Any]:
    payload = _read_yaml(settings_path)
    return {
        section: payload.get(section) or {}
        for section in ("app", "knowledge_graph", "onboarding", "guardrails", "sql", "followups")
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build the settings once per process. Call ``get_settings.cache_clear()`` in tests."""
    load_dotenv(BACKEND_DIR / ".env")  # explicit path: never pick up a parent folder's .env
    data_dir = Path(_env("AI4BI_DATA_DIR") or BACKEND_DIR / "data")
    settings_path = Path(_env("AI4BI_SETTINGS_PATH") or BACKEND_DIR / "config" / "settings.yaml")
    tuning = _tuning(settings_path)
    app, graph, onboarding = tuning["app"], tuning["knowledge_graph"], tuning["onboarding"]
    guard, sql, follow = tuning["guardrails"], tuning["sql"], tuning["followups"]

    aws_region = _env("AWS_REGION", "eu-north-1")
    default_model = _env("BEDROCK_DEFAULT_MODEL")
    use_aws = all(
        _env(name) for name in ("S3_BUCKET", "DDB_REGISTRY", "DDB_KG", "DDB_HISTORY", "DDB_JOBS", "DDB_AUDIT")
    )
    cors = tuple(
        origin.strip()
        for origin in _env("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174").split(",")
        if origin.strip()
    )
    return Settings(
        data_dir=data_dir,
        prompts_dir=Path(_env("PROMPTS_DIR") or BACKEND_DIR / "prompts"),
        visual_templates_path=Path(_env("VISUAL_TEMPLATES_PATH") or BACKEND_DIR / "config" / "visual_templates.yaml"),
        aws_region=aws_region,
        bedrock_region=_env("BEDROCK_REGION", aws_region),
        s3_bucket=_env("S3_BUCKET"),
        ddb_registry=_env("DDB_REGISTRY"),
        ddb_kg=_env("DDB_KG"),
        ddb_history=_env("DDB_HISTORY"),
        ddb_jobs=_env("DDB_JOBS"),
        ddb_audit=_env("DDB_AUDIT"),
        record_ttl_days=_env_int("RECORD_TTL_DAYS", 30),
        audit_ttl_days=_env_int("AUDIT_LOG_TTL_DAYS", 365),
        entra_tenant_id=_env("ENTRA_TENANT_ID"),
        entra_client_id=_env("ENTRA_CLIENT_ID"),
        entra_required_scope=_env("ENTRA_REQUIRED_SCOPE", "access_as_user"),
        allow_anon=_env_bool("ALLOW_ANON", False),
        role_user=_env("ROLE_USER", "AI4BI.User"),
        role_steward=_env("ROLE_STEWARD", "AI4BI.Steward"),
        domain_groups={
            str(domain): tuple(str(group) for group in groups) for domain, groups in _env_json("DOMAIN_GROUPS").items()
        },
        cors_origins=cors,
        cors_allow_localhost=_env_bool("CORS_ALLOW_LOCALHOST", True),
        llm_mode=_env("LLM_MODE", "bedrock" if default_model else "local"),
        bedrock_default_model=default_model,
        bedrock_strong_model=_env("BEDROCK_STRONG_MODEL"),
        bedrock_cheap_model=_env("BEDROCK_CHEAP_MODEL"),
        llm_max_tokens=_env_int("LLM_MAX_TOKENS", 6000),
        llm_temperature=_env_float("LLM_TEMPERATURE", 0.0),
        bedrock_prompt_ids={str(k): str(v) for k, v in _env_json("BEDROCK_PROMPT_IDS").items()},
        prompt_cache_seconds=_env_int("PROMPT_CACHE_SECONDS", 300),
        default_domain=_env("DEFAULT_DOMAIN") or str(app.get("default_domain", "service_ops")),
        row_limit=_env_int("ROW_LIMIT", int(app.get("row_limit", 500))),
        preview_rows=_env_int("PREVIEW_ROWS", int(app.get("preview_rows", 20))),
        max_repairs=int(app.get("max_repairs", 1)),
        history_turns=int(app.get("history_turns", 3)),
        persist_episodes=_env_bool("PERSIST_EPISODES", bool(app.get("persist_episodes", True))),
        graph_slice_limit=int(graph.get("slice_limit", 40)),
        prior_sql_patterns=int(graph.get("prior_sql_patterns", 8)),
        graph_max_episodes=int(graph.get("max_episodes", 200)),
        include_drafts=_env_bool("INCLUDE_DRAFTS", bool(onboarding.get("include_drafts", False))),
        onboarding_sample_values=int(onboarding.get("sample_values_per_column", 10)),
        join_min_overlap=_env_float("JOIN_MIN_OVERLAP", float(onboarding.get("join_min_overlap", 0.8))),
        activation_confidence=_env_float("ACTIVATION_CONFIDENCE", float(onboarding.get("activation_confidence", 0.75))),
        job_workers=_env_int("JOB_WORKERS", 2),
        min_question_length=int(guard.get("min_question_length", 3)),
        max_question_length=int(guard.get("max_question_length", 1000)),
        blocked_patterns=tuple(guard.get("blocked_patterns") or ()),
        sql_dialect=str(sql.get("dialect") or "sqlite"),
        forbidden_keywords=tuple(str(k).lower() for k in sql.get("forbidden_keywords") or ()),
        max_execution_steps=int(sql.get("max_execution_steps", 50_000_000)),
        followup_max=int(follow.get("max_suggestions", 3)),
        followup_templates=tuple(follow.get("templates") or ()),
        upload_max_bytes=_env_int("UPLOAD_MAX_BYTES", 100 * 1024 * 1024),
        presign_expiry_seconds=_env_int("PRESIGN_EXPIRY_SECONDS", 900),
        data_cache_seconds=_env_int("DATA_CACHE_SECONDS", 60),
        data_cache_max_entries=_env_int("DATA_CACHE_MAX_ENTRIES", 8),
        log_level=_env("LOG_LEVEL", "INFO").upper(),
        log_json=_env_bool("LOG_JSON", use_aws),
    )
