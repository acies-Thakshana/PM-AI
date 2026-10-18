"""Application settings: config/settings.yaml, an optional overlay file, then env vars."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ai4bi.config.errors import ConfigError

SETTINGS_RELATIVE = Path("config") / "settings.yaml"


def resolve_project_root(start: Path | None = None) -> Path:
    """Find the folder that holds config/settings.yaml.

    Order: AIBI_PROJECT_ROOT, the package location, then the working directory.
    """
    explicit = os.environ.get("AIBI_PROJECT_ROOT")
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not (root / SETTINGS_RELATIVE).exists():
            raise ConfigError(
                f"AIBI_PROJECT_ROOT={root} has no {SETTINGS_RELATIVE}. "
                "Point it at the folder that contains config/settings.yaml."
            )
        return root
    candidates = [Path(__file__).resolve()]
    candidates.append((start or Path.cwd()).resolve())
    for origin in candidates:
        for folder in [origin, *origin.parents]:
            if (folder / SETTINGS_RELATIVE).exists():
                return folder
    raise ConfigError(
        f"Could not find {SETTINGS_RELATIVE}. Run from the project folder or set AIBI_PROJECT_ROOT."
    )


def load_dotenv(path: Path) -> None:
    """Read KEY=VALUE lines into os.environ without overriding existing values."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


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


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _require(section: dict[str, Any], key: str, where: str) -> Any:
    if key not in section or section[key] in (None, ""):
        raise ConfigError(f"Missing setting {where}.{key} in config/settings.yaml")
    return section[key]


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    project_root: Path
    default_domain: str
    row_limit: int
    preview_rows: int
    max_repairs: int
    history_turns: int
    semantic_root: Path
    metadata_root: Path
    semantic_registry_root: Path
    knowledge_graph_root: Path
    samples_root: Path
    history_root: Path
    visual_templates_path: Path
    logging_config_path: Path
    llm_mode: str
    llm_connection: str
    llm_temperature: float
    graph_slice_limit: int
    prior_sql_patterns: int
    auto_onboard: bool
    include_drafts: bool
    onboarding_sample_values: int
    join_min_overlap: float
    activation_confidence: float
    min_question_length: int
    max_question_length: int
    blocked_patterns: list[dict[str, str]]
    sql_dialect: str
    forbidden_keywords: list[str]
    max_execution_steps: int
    followup_max: int
    followup_templates: list[str]
    log_level: str = "INFO"
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def with_overrides(self, **values: Any) -> "Settings":
        data = dict(self.__dict__)
        data.update(values)
        return Settings(**data)


def load_settings(
    project_root: Path | None = None,
    *,
    settings_path: Path | None = None,
    env: bool = True,
) -> Settings:
    root = (project_root or resolve_project_root()).resolve()
    if env:
        load_dotenv(root / ".env")
    payload = _read_yaml(root / SETTINGS_RELATIVE)
    overlay_name = settings_path or (os.environ.get("AIBI_SETTINGS_PATH") if env else None)
    if overlay_name:
        overlay_path = Path(overlay_name)
        if not overlay_path.is_absolute():
            overlay_path = root / overlay_path
        if overlay_path.resolve() != (root / SETTINGS_RELATIVE).resolve():
            payload = _merge(payload, _read_yaml(overlay_path))

    app = payload.get("app") or {}
    paths = payload.get("paths") or {}
    llm = payload.get("llm") or {}
    graph = payload.get("knowledge_graph") or {}
    onboarding = payload.get("onboarding") or {}
    guard = payload.get("guardrails") or {}
    sql = payload.get("sql") or {}
    follow = payload.get("followups") or {}

    def path(key: str) -> Path:
        value = Path(str(_require(paths, key, "paths")))
        return value if value.is_absolute() else root / value

    domain = str(_require(app, "default_domain", "app"))
    mode = str(llm.get("mode") or "local")
    connection = str(llm.get("connection") or "")
    level = "INFO"
    if env:
        domain = os.environ.get("AIBI_DOMAIN") or domain
        mode = os.environ.get("AIBI_LLM_MODE") or mode
        connection = os.environ.get("AIBI_LLM_CONNECTION") or connection
        level = os.environ.get("AIBI_LOG_LEVEL") or level
    if mode not in {"local", "mesh"}:
        raise ConfigError(f"llm.mode must be 'local' or 'mesh', got {mode!r}")

    return Settings(
        project_root=root,
        default_domain=domain,
        row_limit=int(app.get("row_limit", 500)),
        preview_rows=int(app.get("preview_rows", 20)),
        max_repairs=int(app.get("max_repairs", 1)),
        history_turns=int(app.get("history_turns", 3)),
        semantic_root=path("semantic_root"),
        metadata_root=path("metadata_root"),
        semantic_registry_root=path("semantic_registry_root"),
        knowledge_graph_root=path("knowledge_graph_root"),
        samples_root=path("samples_root"),
        history_root=path("history_root"),
        visual_templates_path=path("visual_templates"),
        logging_config_path=path("logging_config"),
        llm_mode=mode,
        llm_connection=connection,
        llm_temperature=float(llm.get("temperature", 0.0)),
        graph_slice_limit=int(graph.get("slice_limit", 40)),
        prior_sql_patterns=int(graph.get("prior_sql_patterns", 8)),
        auto_onboard=_env_bool("AIBI_AUTO_ONBOARD", bool(onboarding.get("auto_onboard", True))) if env
        else bool(onboarding.get("auto_onboard", True)),
        include_drafts=_env_bool("AIBI_INCLUDE_DRAFTS", bool(onboarding.get("include_drafts", False))) if env
        else bool(onboarding.get("include_drafts", False)),
        onboarding_sample_values=int(
            os.environ.get("AIBI_ONBOARDING_SAMPLE_VALUES") or onboarding.get("sample_values_per_column", 10)
        ) if env else int(onboarding.get("sample_values_per_column", 10)),
        join_min_overlap=float(
            os.environ.get("AIBI_JOIN_MIN_OVERLAP") or onboarding.get("join_min_overlap", 0.8)
        ) if env else float(onboarding.get("join_min_overlap", 0.8)),
        activation_confidence=float(
            os.environ.get("AIBI_ACTIVATION_CONFIDENCE") or onboarding.get("activation_confidence", 0.75)
        ) if env else float(onboarding.get("activation_confidence", 0.75)),
        min_question_length=int(guard.get("min_question_length", 3)),
        max_question_length=int(guard.get("max_question_length", 1000)),
        blocked_patterns=list(guard.get("blocked_patterns") or []),
        sql_dialect=str(sql.get("dialect") or "sqlite"),
        forbidden_keywords=[str(k).lower() for k in sql.get("forbidden_keywords") or []],
        max_execution_steps=int(sql.get("max_execution_steps", 50_000_000)),
        followup_max=int(follow.get("max_suggestions", 3)),
        followup_templates=list(follow.get("templates") or []),
        log_level=level,
        raw=payload,
    )
