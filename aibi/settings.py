"""Local settings for the standalone AI-for-BI host."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LocalAuthUser(BaseModel):
    user_id: str
    display_name: str
    roles: list[str] = Field(default_factory=list)
    authorized_bu_codes: list[str] = Field(default_factory=list)
    can_query_cross_bu: bool = False


class AppSettings(BaseModel):
    project_root: Path = PROJECT_ROOT
    nl2sql_root: Path = Field(
        default_factory=lambda: Path(
            os.environ.get(
                "AI_BI_NL2SQL_ROOT",
                r"C:\Users\BharadNa\dataiku-langgraph-nlq",
            )
        )
    )
    semantic_core_path: Path = PROJECT_ROOT / "semantic" / "domains" / "kpi_productivity.yaml"
    enterprise_template_path: Path = (
        PROJECT_ROOT / "semantic" / "enterprise" / "enterprise_semantic_model.yaml"
    )
    users_path: Path = PROJECT_ROOT / "config" / "local_users.yaml"
    dashboard_config_path: Path = PROJECT_ROOT / "config" / "dashboard.yaml"
    audit_path: Path = PROJECT_ROOT / "logs" / "aibi_audit.jsonl"
    default_user_id: str = "local.cross_bu"
    data_products_path: Path = PROJECT_ROOT / "config" / "data_products.yaml"
    # When true, skip catalog/semantic answers and always call the LLM.
    force_llm: bool = Field(
        default_factory=lambda: os.environ.get("AIBI_FORCE_LLM", "true").lower()
        in {"1", "true", "yes", "y"}
    )
    enable_llm_fallback: bool = Field(
        default_factory=lambda: os.environ.get("AIBI_ENABLE_LLM_FALLBACK", "true").lower()
        in {"1", "true", "yes", "y"}
    )
    # Dataiku LLM Mesh connection id. Must contain/be the Opus connection.
    llm_connection: str = Field(
        default_factory=lambda: os.environ.get("AIBI_LLM_CONNECTION")
        or os.environ.get("NLQ_LLM_CONNECTION")
        or ""
    )
    llm_model_id: str = Field(
        default_factory=lambda: os.environ.get("AIBI_LLM_MODEL_ID")
        or os.environ.get("NLQ_LLM_MODEL_ID")
        or "claude-opus"
    )
    llm_mode: str = Field(
        default_factory=lambda: os.environ.get("NLQ_LLM_MODE", "mesh")
    )


def get_settings() -> AppSettings:
    return AppSettings()


def load_yaml(path: Path) -> Any:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
