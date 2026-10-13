"""Configurable explainability. Always available; depth is a domain setting."""

from __future__ import annotations

from typing import Any

from aibi.factory.models import DomainPackage, MetricVersion
from aibi.settings import PROJECT_ROOT, load_yaml


def load_explain_config(domain: str) -> dict[str, Any]:
    path = PROJECT_ROOT / "onboarding" / "domains" / domain / "explainability.yaml"
    return load_yaml(path) or {"default_level": "analyst", "levels": {}}


def explain_answer(
    *,
    domain: str,
    pkg: DomainPackage,
    metric: MetricVersion,
    sql: str,
    applied_filters: dict[str, Any] | None = None,
    level: str | None = None,
) -> dict[str, Any]:
    cfg = load_explain_config(domain)
    level_name = level or cfg.get("default_level") or "analyst"
    flags = dict((cfg.get("levels") or {}).get(level_name) or {})
    kpi = next((k for k in pkg.dictionary.kpis if k.family == metric.family), None)
    payload: dict[str, Any] = {"level": level_name, "metric_id": metric.id}
    if flags.get("metric_definition"):
        payload["metric_definition"] = {
            "name": metric.name,
            "family": metric.family,
            "scope": metric.scope,
            "version": metric.version,
            "grain": metric.grain,
            "business_definition": kpi.business_definition if kpi else "",
            "sql_expression": metric.sql_expression,
        }
    if flags.get("data_freshness"):
        payload["data_freshness"] = {
            "historical_from": pkg.contract.historical_from,
            "historical_to": pkg.contract.historical_to,
            "data_product_id": metric.data_product_id,
        }
    if flags.get("source_attribution"):
        payload["source_attribution"] = {
            "source_system": pkg.contract.source_system,
            "extracts": list(pkg.contract.extracts),
            "data_product_id": metric.data_product_id,
        }
    if flags.get("applied_filters"):
        payload["applied_filters"] = dict(applied_filters or {})
        if metric.filter_sql:
            payload["applied_filters"]["metric_filter_sql"] = metric.filter_sql
    if flags.get("sql_visibility"):
        payload["sql"] = sql
    else:
        payload["sql"] = None
    return payload
