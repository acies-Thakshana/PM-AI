"""Load and slice local semantic YAML models (multi-domain / multi-BU)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aibi.semantic_merge import load_merged_semantic_model
from aibi.settings import get_settings, load_yaml


def load_semantic_core(path: Path | None = None) -> dict[str, Any]:
    """Load merged semantic model (domain pack + other domains + BU extensions)."""
    if path is not None:
        doc = load_yaml(path)
        doc["_source_path"] = str(path)
        return doc
    return load_merged_semantic_model()


def authorized_metrics(model: dict[str, Any], role_ids: list[str]) -> list[dict[str, Any]]:
    roles = {r.get("id"): r for r in (model.get("security") or {}).get("roles") or []}
    allowed: set[str] | None = None
    for rid in role_ids:
        role = roles.get(rid)
        if not role:
            continue
        metric_ids = role.get("metric_ids")
        if not metric_ids:
            return list(model.get("metrics") or [])
        allowed = (allowed or set()) | set(metric_ids)
    metrics = list(model.get("metrics") or [])
    if allowed is None:
        # Cross-BU / steward roles often omit metric_ids → all metrics
        if any(roles.get(rid, {}).get("can_query_cross_bu") for rid in role_ids):
            return metrics
        return []
    return [m for m in metrics if m.get("id") in allowed]


def metric_by_id(model: dict[str, Any], metric_id: str) -> dict[str, Any] | None:
    for metric in model.get("metrics") or []:
        if metric.get("id") == metric_id:
            return metric
    return None


def resolve_metrics_from_question(question: str, model: dict[str, Any], role_ids: list[str]) -> list[dict[str, Any]]:
    """Match certified metrics via name / synonyms (generic, dataset-agnostic)."""
    import re

    q = re.sub(r"\s+", " ", (question or "").strip().lower())
    allowed = authorized_metrics(model, role_ids)
    hits: list[dict[str, Any]] = []
    for metric in allowed:
        names = [metric.get("name", "")] + list(metric.get("synonyms") or [])
        for name in names:
            token = re.sub(r"\s+", " ", str(name).strip().lower())
            if token and token in q:
                hits.append(metric)
                break
    # synonym table
    by_id = {m["id"]: m for m in allowed}
    for syn in model.get("synonyms") or []:
        if syn.get("maps_to_kind") != "metric":
            continue
        term = str(syn.get("term") or "").strip().lower()
        mid = syn.get("maps_to_id")
        if term and term in q and mid in by_id:
            if by_id[mid] not in hits:
                hits.append(by_id[mid])
    return hits


def sample_questions_for_user(model: dict[str, Any], role_ids: list[str]) -> list[dict[str, Any]]:
    allowed_ids = {m["id"] for m in authorized_metrics(model, role_ids)}
    out = []
    for q in model.get("sample_questions") or []:
        mids = set(q.get("metric_ids") or [])
        if (
            not mids
            or mids & allowed_ids
            or q.get("expected_behavior")
            in {"clarify", "refuse_unsupported", "refuse_unauthorized"}
        ):
            out.append(q)
    return out


def freshness_summary(model: dict[str, Any]) -> list[dict[str, Any]]:
    return list(model.get("data_freshness") or [])


def dashboard_cards(model: dict[str, Any], role_ids: list[str]) -> list[dict[str, Any]]:
    settings = get_settings()
    cfg = load_yaml(settings.dashboard_config_path)
    configured = cfg.get("kpi_cards") or []
    auth = {m["id"]: m for m in authorized_metrics(model, role_ids)}
    cards = []
    for card in configured:
        mid = card.get("metric_id")
        metric = auth.get(mid)
        if not metric:
            continue
        cards.append(
            {
                "metric_id": mid,
                "title": card.get("title") or metric.get("name"),
                "description": metric.get("description"),
                "definition_status": metric.get("definition_status"),
                "unit_id": metric.get("unit_id"),
                "synonyms": metric.get("synonyms") or [],
                "data_product_ids": metric.get("data_product_ids") or [],
                "semantic_version": model.get("semantic_version"),
                "chart_hint": card.get("chart_hint") or "kpi",
            }
        )
    return cards
