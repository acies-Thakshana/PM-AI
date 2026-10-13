"""Execute a certified catalog metric on a registered data product.

KPI math comes from metadata (`compute` / aggregation). No prompt changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from aibi.factory.catalog import resolve_metric
from aibi.factory.loader import load_domain
from aibi.factory.models import DomainPackage, MetricVersion
from aibi.factory.security_tags import strip_restricted
from aibi.settings import PROJECT_ROOT


def _product_path(data_product_id: str) -> Path | None:
    from aibi.data_product_registry import list_registered_products, resolve_product_path

    for entry in list_registered_products():
        if entry.get("id") == data_product_id:
            path = resolve_product_path(entry)
            return path if path.exists() else None
    return None


def _apply_compute(frame: pd.DataFrame, metric: MetricVersion) -> pd.Series:
    compute = metric.compute or {}
    kind = compute.get("kind")
    if kind == "duration_hours":
        start = pd.to_datetime(frame[compute["start_column"]], errors="coerce")
        end = pd.to_datetime(frame[compute["end_column"]], errors="coerce")
        return (end - start).dt.total_seconds() / 3600.0
    if metric.aggregation == "count":
        return pd.Series([1] * len(frame), index=frame.index)
    return pd.to_numeric(frame.iloc[:, 0], errors="coerce")


def execute_catalog_metric(
    question: str,
    *,
    domain: str | None = None,
    user_scope: str | None = None,
) -> dict[str, Any] | None:
    domains = [domain] if domain else _candidate_domains()
    for name in domains:
        pkg = load_domain(name)
        metric = resolve_metric(question, pkg, user_scope=user_scope)
        if metric is None:
            continue
        result = _run(pkg, metric)
        if result is not None:
            result["domain"] = name
            result["handled"] = True
            result["status"] = "success"
            return result
    return None


def _candidate_domains() -> list[str]:
    from aibi.factory.loader import list_domains

    return list_domains()


def _run(pkg: DomainPackage, metric: MetricVersion) -> dict[str, Any] | None:
    path = _product_path(metric.data_product_id)
    if path is None:
        # allow fixtures next to the onboarding package
        fallback = PROJECT_ROOT / "local_data" / "fixtures" / pkg.contract.domain / "cases.csv"
        if not fallback.exists():
            return None
        path = fallback
    frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    filt = (metric.compute or {}).get("filter") or {}
    if filt.get("column") and filt.get("column") in frame.columns:
        frame = frame[frame[filt["column"]].astype(str).str.upper() == str(filt.get("value", "")).upper()]
    if frame.empty:
        return {
            "answer": f"{metric.name} has no rows for the current scope.",
            "metric_ids": [metric.id],
            "table": {"columns": ["metric_id", "scope", "value"], "rows": []},
            "sql_query": metric.sql_expression,
            "datasets_used": [metric.data_product_id],
            "warnings": ["empty result"],
        }
    values = _apply_compute(frame, metric)
    agg = (metric.compute or {}).get("aggregation") or metric.aggregation
    if agg == "avg":
        value = float(values.mean())
    elif agg == "sum":
        value = float(values.sum())
    elif agg == "count":
        value = float(values.count())
    elif agg == "min":
        value = float(values.min())
    elif agg == "max":
        value = float(values.max())
    else:
        value = float(values.mean())
    visible = strip_restricted(list(frame.columns), pkg)
    preview = frame[visible].head(8)
    sql = metric.sql_expression + (f" WHERE {metric.filter_sql}" if metric.filter_sql else "")
    from aibi.experience.explain import explain_answer

    return {
        "answer": f"{metric.name} is {value:.2f} (metric {metric.id} v{metric.version}, scope={metric.scope}).",
        "metric_ids": [metric.id],
        "metric_versions": [metric.version],
        "table": {
            "columns": ["metric_id", "scope", "version", "value"],
            "rows": [[metric.id, metric.scope, metric.version, round(value, 4)]],
        },
        "preview_columns": list(preview.columns),
        "chart_spec": {"type": "kpi", "value": value, "title": metric.name},
        "sql_query": sql,
        "datasets_used": [metric.data_product_id],
        "warnings": [],
        "record_count": int(len(frame)),
        "explainability": explain_answer(
            domain=pkg.contract.domain,
            pkg=pkg,
            metric=metric,
            sql=sql,
            applied_filters=(metric.compute or {}).get("filter") or {},
        ),
    }
