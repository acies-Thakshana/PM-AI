"""Zero-code semantic onboarding for arbitrary tabular datasets."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pydantic import ValidationError

from ai4bi.config.settings import Settings
from ai4bi.data.preprocessing import drop_restricted, prepare_frames
from ai4bi.guardrails.sql_policy import SqlPolicy
from ai4bi.llm.client import LlmClient, complete_json
from ai4bi.metadata.extractor import extract_metadata
from ai4bi.semantic.loader import align_with_frames, package_from_frames
from ai4bi.semantic.models import (
    BusinessRule,
    DictionaryKpi,
    DomainPackage,
    GlossaryTerm,
    JoinKey,
    MetricVersion,
    RegisteredJoin,
)
from ai4bi.semantic.registry import SemanticArtifact, SemanticRegistry, schema_fingerprint
from ai4bi.sql.executor import SqliteFrameExecutor
from ai4bi.sql.grounding import result_is_vacuous
from ai4bi.sql.validator import SqlValidator
from ai4bi.utils.text import quote_ident, slug

SYSTEM_INSTRUCTION = """You are a BI semantic-model builder. Return one JSON object only.
Use only the supplied dataset and column names. Describe columns and entities, propose useful
business KPIs, exact SQLite aggregate expressions, synonyms, business rules, and joins.
Never infer a join without matching supplied columns. Never use restricted columns.
Metrics must contain: id, family, name, data_product_id, grain, aggregation, sql_expression,
unit, synonyms, confidence. Joins must contain: id, left_dataset, right_dataset,
left_column, right_column, join_type, cardinality, confidence, description.
Also return glossary and rules arrays. Do not return SQL statements; metric sql_expression
is an aggregate expression such as SUM("Revenue")."""

PII_NAME = re.compile(
    r"(^|_|\s)(email|e_mail|phone|mobile|ssn|social_security|passport|contact_email|"
    r"date_of_birth|dob|street_address|ip_address)(_|$|\s)",
    re.I,
)
FORBIDDEN_EXPRESSION = re.compile(
    r"\b(select|insert|update|delete|drop|alter|create|attach|detach|pragma|union|with)\b|;|--|/\*",
    re.I,
)


@dataclass
class OnboardingResult:
    package: DomainPackage
    registry: SemanticRegistry
    metadata: dict[str, Any]
    fingerprint: str
    semantic_version: str
    changed: bool
    audit: list[dict[str, Any]] = field(default_factory=list)


def inferred_restricted_columns(frames: dict[str, pd.DataFrame]) -> set[str]:
    """Conservative name-based PII detection before any value reaches a model."""
    return {
        str(column)
        for frame in frames.values()
        for column in frame.columns
        if PII_NAME.search(str(column).replace("-", "_"))
    }


def _safe_metadata(pkg: DomainPackage, frames: dict[str, pd.DataFrame], sample_limit: int) -> dict[str, Any]:
    metadata = extract_metadata(pkg, frames)
    for dataset in metadata.get("datasets") or []:
        for column in dataset.get("columns") or []:
            column["sample_values"] = list(column.get("sample_values") or [])[:sample_limit]
            if column.get("restricted"):
                column["sample_values"] = []
    return metadata


def _heuristic_payload(pkg: DomainPackage, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    metrics: list[dict[str, Any]] = []
    glossary: list[dict[str, Any]] = []
    for entity in pkg.entities:
        frame = frames[entity.physical_dataset]
        for column in entity.columns:
            if column.role != "measure" or column.name not in frame.columns:
                continue
            family = slug(column.name)
            metrics.append(
                {
                    "id": f"metric.{pkg.domain}.{family}",
                    "family": family,
                    "name": column.name,
                    "scope": "global",
                    "default_for_family": True,
                    "version": "1",
                    "status": "proposed",
                    "data_product_id": entity.data_product_id,
                    "grain": entity.grain,
                    "aggregation": "sum",
                    "sql_expression": f"SUM({quote_ident(column.name)})",
                    "compute": {"column": column.name, "aggregation": "sum"},
                    "synonyms": [column.name.replace("_", " ")],
                    "owner": "auto_onboarding",
                    "unit": "",
                    "confidence": 0.8,
                }
            )
            glossary.append(
                {
                    "term": column.name.replace("_", " "),
                    "kind": "domain_term",
                    "maps_to_kind": "metric_family",
                    "maps_to_id": family,
                }
            )
    joins: list[dict[str, Any]] = []
    entities = pkg.entities
    for left_index, left in enumerate(entities):
        left_frame = frames[left.physical_dataset]
        for right in entities[left_index + 1 :]:
            right_frame = frames[right.physical_dataset]
            common = [
                str(column)
                for column in left_frame.columns
                if column in right_frame.columns and str(column).lower().endswith(("_id", " key", "_key"))
            ]
            for column in common:
                joins.append(
                    {
                        "id": f"join.{pkg.domain}.{slug(left.physical_dataset)}.{slug(right.physical_dataset)}.{slug(column)}",
                        "left_dataset": left.physical_dataset,
                        "right_dataset": right.physical_dataset,
                        "left_column": column,
                        "right_column": column,
                        "join_type": "left",
                        "cardinality": "many_to_many",
                        "confidence": 0.8,
                        "description": f"Shared key {column}",
                    }
                )
    return {"metrics": metrics, "joins": joins, "glossary": glossary, "rules": [], "columns": []}


def _merge_payload(fallback: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    if not model:
        return fallback
    out: dict[str, Any] = {}
    for key in ("metrics", "joins", "glossary", "rules", "columns"):
        proposed = model.get(key)
        out[key] = proposed if isinstance(proposed, list) and proposed else fallback.get(key, [])
    return out


def _column_lookup(pkg: DomainPackage) -> dict[tuple[str, str], Any]:
    return {
        (entity.physical_dataset.lower(), column.name.lower()): (entity, column)
        for entity in pkg.entities
        for column in entity.columns
    }


def _apply_column_enrichment(pkg: DomainPackage, payload: dict[str, Any]) -> None:
    lookup = _column_lookup(pkg)
    for item in payload.get("columns") or []:
        target = lookup.get((str(item.get("dataset", "")).lower(), str(item.get("name", "")).lower()))
        if not target:
            continue
        _, column = target
        if item.get("description"):
            column.description = str(item["description"])
        role = item.get("role")
        if role in {"key", "foreign_key", "measure", "attribute", "timestamp", "flag", "degenerate"}:
            column.role = role


def _join_overlap(left: pd.Series, right: pd.Series) -> float:
    left_values = {str(v) for v in left.dropna().unique()}
    right_values = {str(v) for v in right.dropna().unique()}
    smaller = min(len(left_values), len(right_values))
    return len(left_values & right_values) / smaller if smaller else 0.0


def _join_cardinality(left: pd.Series, right: pd.Series) -> str:
    left_unique = not left.dropna().duplicated().any()
    right_unique = not right.dropna().duplicated().any()
    if left_unique and right_unique:
        return "one_to_one"
    if left_unique:
        return "one_to_many"
    if right_unique:
        return "many_to_one"
    return "many_to_many"


def _validate_join(
    item: dict[str, Any],
    pkg: DomainPackage,
    frames: dict[str, pd.DataFrame],
    settings: Settings,
) -> tuple[RegisteredJoin | None, bool, float, str]:
    left_name = str(item.get("left_dataset") or item.get("left_table") or "")
    right_name = str(item.get("right_dataset") or item.get("right_table") or "")
    left_column = str(item.get("left_column") or "")
    right_column = str(item.get("right_column") or "")
    if left_name not in frames or right_name not in frames:
        return None, False, 0.0, "join references an unavailable dataset"
    if left_column not in frames[left_name].columns or right_column not in frames[right_name].columns:
        return None, False, 0.0, "join references an unavailable column"
    left_entity = pkg.entity_for_dataset(left_name)
    right_entity = pkg.entity_for_dataset(right_name)
    if left_entity is None or right_entity is None:
        return None, False, 0.0, "join entity is not registered"
    left = frames[left_name][left_column]
    right = frames[right_name][right_column]
    overlap = _join_overlap(left, right)
    model_confidence = float(item.get("confidence") or 0.0)
    confidence = min(model_confidence or overlap, overlap)
    cardinality = _join_cardinality(left, right)
    allowed = (
        overlap >= settings.join_min_overlap
        and confidence >= settings.activation_confidence
        and cardinality != "many_to_many"
    )
    message = (
        f"overlap={overlap:.3f}, cardinality={cardinality}"
        if allowed
        else f"draft: overlap={overlap:.3f}, cardinality={cardinality}; "
        f"requires overlap>={settings.join_min_overlap} and a unique side"
    )
    join = RegisteredJoin(
        id=str(item.get("id") or f"join.{pkg.domain}.{slug(left_name)}.{slug(right_name)}"),
        left_entity=left_entity.logical_entity,
        right_entity=right_entity.logical_entity,
        join_type=str(item.get("join_type") or "left").lower(),
        cardinality=cardinality,
        keys=[
            JoinKey(
                left_entity=left_entity.logical_entity,
                left_column=left_column,
                right_entity=right_entity.logical_entity,
                right_column=right_column,
            )
        ],
        condition=f"{left_entity.logical_entity}.{left_column} = {right_entity.logical_entity}.{right_column}",
        grain_note=str(item.get("description") or message),
        allowed_for_nlq=allowed,
        approved_by="automatic_validation" if allowed else "",
        inferred=True,
    )
    return join, allowed, confidence, message


def _metric_from_item(item: dict[str, Any], pkg: DomainPackage) -> MetricVersion:
    payload = dict(item)
    payload.pop("confidence", None)
    payload.setdefault("scope", "global")
    payload.setdefault("default_for_family", True)
    payload.setdefault("version", "1")
    payload.setdefault("status", "proposed")
    payload.setdefault("owner", "auto_onboarding")
    payload.setdefault("unit", "")
    payload.setdefault("synonyms", [])
    payload.setdefault("compute", {})
    if not payload.get("id"):
        payload["id"] = f"metric.{pkg.domain}.{slug(str(payload.get('name') or payload.get('family') or 'metric'))}"
    return MetricVersion.model_validate(payload)


def _validate_metric(
    item: dict[str, Any],
    pkg: DomainPackage,
    frames: dict[str, pd.DataFrame],
    settings: Settings,
) -> tuple[MetricVersion | None, bool, float, str]:
    try:
        metric = _metric_from_item(item, pkg)
    except ValidationError as exc:
        return None, False, 0.0, f"invalid metric: {exc.errors()[0]['msg']}"
    entity = pkg.entity_for_product(metric.data_product_id)
    if entity is None or entity.physical_dataset not in frames:
        return metric, False, 0.0, "metric references an unavailable data product"
    expression = metric.sql_expression.strip()
    if not expression or FORBIDDEN_EXPRESSION.search(expression):
        return metric, False, 0.0, "metric expression contains forbidden SQL"
    sql = f"SELECT {expression} AS value FROM {quote_ident(entity.physical_dataset)}"
    policy = SqlPolicy.from_settings(settings).with_restricted(pkg.restricted_columns())
    candidate_pkg = pkg.model_copy(deep=True)
    candidate_pkg.metrics = [*candidate_pkg.metrics, metric]
    validation = SqlValidator(policy).validate(sql, candidate_pkg, list(frames))
    if not validation.ok:
        return metric, False, 0.0, "; ".join(validation.errors)
    result = SqliteFrameExecutor(policy).execute(validation.sql, frames)
    confidence = float(item.get("confidence") or 0.0)
    active = result.ok and not result_is_vacuous(result.frame) and confidence >= settings.activation_confidence
    message = "expression executed successfully" if active else result.error or "expression returned no value or low confidence"
    metric.status = "certified" if active else "proposed"
    return metric, active, confidence, message


def _artifact(
    *,
    domain: str,
    version: str,
    fingerprint: str,
    kind: str,
    artifact_id: str,
    payload: dict[str, Any],
    active: bool,
    confidence: float,
    message: str,
) -> SemanticArtifact:
    return SemanticArtifact(
        domain=domain,
        semantic_version=version,
        artifact_type=kind,
        artifact_id=artifact_id,
        status="active" if active else "draft",
        source="llm",
        confidence=max(0.0, min(1.0, confidence)),
        payload=payload,
        input_fingerprint=fingerprint,
        validation_message=message,
    )


def onboard_domain(
    domain: str,
    frames: dict[str, pd.DataFrame],
    *,
    llm: LlmClient,
    settings: Settings,
    registry: SemanticRegistry | None = None,
    base_package: DomainPackage | None = None,
    force: bool = False,
) -> OnboardingResult:
    """Learn semantics for connected datasets and append a validated registry version."""
    frames = prepare_frames(frames)
    registry = registry or SemanticRegistry()
    fingerprint = schema_fingerprint(frames)
    package = base_package or package_from_frames(
        domain, frames, pii_columns=sorted(inferred_restricted_columns(frames))
    )
    package = align_with_frames(package, frames)
    if registry.has_fingerprint(domain, fingerprint) and not force:
        overlaid = registry.overlay(package, include_drafts=settings.include_drafts)
        return OnboardingResult(
            overlaid,
            registry,
            _safe_metadata(overlaid, frames, settings.onboarding_sample_values),
            fingerprint,
            fingerprint[:12],
            False,
        )

    restricted = package.restricted_columns() | inferred_restricted_columns(frames)
    for entity in package.entities:
        for column in entity.columns:
            if column.name.lower() in {name.lower() for name in restricted}:
                column.pii_tag, column.sensitive = "restricted", True
    safe_frames = drop_restricted(frames, restricted)
    metadata = _safe_metadata(package, frames, settings.onboarding_sample_values)
    fallback = _heuristic_payload(package, safe_frames)
    model_payload = complete_json(
        llm,
        SYSTEM_INSTRUCTION,
        json.dumps(
            {
                "domain": domain,
                "metadata": metadata,
                "requirements": {
                    "dialect": settings.sql_dialect,
                    "activation_confidence": settings.activation_confidence,
                },
            },
            default=str,
        ),
        task="semantic_onboarding",
        fallback=fallback,
    )
    payload = _merge_payload(fallback, model_payload)
    _apply_column_enrichment(package, payload)
    version = fingerprint[:12]
    audit: list[dict[str, Any]] = []

    # Entities are always active after deterministic schema inference; enriched descriptions are included.
    for entity in package.entities:
        registry.append(
            _artifact(
                domain=domain,
                version=version,
                fingerprint=fingerprint,
                kind="entity",
                artifact_id=entity.physical_dataset,
                payload=entity.model_dump(),
                active=True,
                confidence=1.0,
                message="dataset and columns observed directly",
            )
        )

    for item in payload.get("metrics") or []:
        metric, active, confidence, message = _validate_metric(item, package, safe_frames, settings)
        artifact_id = str(item.get("id") or item.get("name") or "invalid_metric")
        if metric is not None:
            registry.append(
                _artifact(
                    domain=domain,
                    version=version,
                    fingerprint=fingerprint,
                    kind="metric",
                    artifact_id=metric.id,
                    payload=metric.model_dump(),
                    active=active,
                    confidence=confidence,
                    message=message,
                )
            )
            artifact_id = metric.id
        audit.append({"artifact_type": "metric", "artifact_id": artifact_id, "active": active, "detail": message})

    for item in payload.get("joins") or []:
        join, active, confidence, message = _validate_join(item, package, safe_frames, settings)
        artifact_id = str(item.get("id") or "invalid_join")
        if join is not None:
            registry.append(
                _artifact(
                    domain=domain,
                    version=version,
                    fingerprint=fingerprint,
                    kind="join",
                    artifact_id=join.id,
                    payload=join.model_dump(),
                    active=active,
                    confidence=confidence,
                    message=message,
                )
            )
            artifact_id = join.id
        audit.append({"artifact_type": "join", "artifact_id": artifact_id, "active": active, "detail": message})

    simple_models = {
        "glossary": (GlossaryTerm, lambda value: value.term.lower()),
        "rules": (BusinessRule, lambda value: value.id),
    }
    for source_key, (model, key) in simple_models.items():
        for item in payload.get(source_key) or []:
            try:
                value = model.model_validate(item)
                confidence = float(item.get("confidence") or settings.activation_confidence)
                active = confidence >= settings.activation_confidence
                registry.append(
                    _artifact(
                        domain=domain,
                        version=version,
                        fingerprint=fingerprint,
                        kind="rule" if source_key == "rules" else "glossary",
                        artifact_id=key(value),
                        payload=value.model_dump(),
                        active=active,
                        confidence=confidence,
                        message="valid structured semantic artifact",
                    )
                )
            except ValidationError as exc:
                audit.append(
                    {
                        "artifact_type": source_key.rstrip("s"),
                        "artifact_id": str(item.get("id") or item.get("term") or "invalid"),
                        "active": False,
                        "detail": str(exc),
                    }
                )

    # Dictionary KPI entries make learned metric families discoverable by the planner.
    active_metrics = [
        MetricVersion.model_validate(a.payload)
        for a in registry.latest(domain)
        if a.artifact_type == "metric"
    ]
    for metric in active_metrics:
        dictionary = DictionaryKpi(
            family=metric.family,
            name=metric.name,
            business_definition=f"Automatically learned metric using {metric.sql_expression}.",
            formula_hint=metric.sql_expression,
            grain=metric.grain,
            owner=metric.owner or "auto_onboarding",
            synonyms=metric.synonyms,
            scopes=[metric.scope],
        )
        registry.append(
            _artifact(
                domain=domain,
                version=version,
                fingerprint=fingerprint,
                kind="dictionary_kpi",
                artifact_id=dictionary.family,
                payload=dictionary.model_dump(),
                active=True,
                confidence=1.0,
                message="derived from an active metric",
            )
        )

    overlaid = registry.overlay(package, include_drafts=settings.include_drafts)
    metadata = _safe_metadata(overlaid, frames, settings.onboarding_sample_values)
    return OnboardingResult(overlaid, registry, metadata, fingerprint, version, True, audit)
