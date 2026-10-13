"""Compile KPI formulae from the data dictionary.

The compiler may draft metric SQL and filters. It may not invent joins.
Output is a proposed metric catalog — stewards activate it.
"""

from __future__ import annotations

import os
import re
from typing import Any

from aibi.factory.models import DomainPackage, MetricVersion
from aibi.factory.security_tags import restricted_columns
from aibi.factory.validate import OnboardingError, validate_package

_FORBIDDEN = re.compile(
    r"\b(join|from|insert|update|delete|merge|drop|alter|create|truncate)\b",
    re.IGNORECASE,
)


def _assert_expression_only(sql: str, label: str) -> None:
    if _FORBIDDEN.search(sql or ""):
        raise OnboardingError(
            f"{label} must be an expression, not a query, and must not contain JOIN/DML: {sql}"
        )


def _draft_sql(kpi) -> tuple[str, str, dict[str, Any]]:
    """Deterministic draft from dictionary formula_hint. Optional LLM later."""
    hint = (kpi.formula_hint or "").strip()
    compute: dict[str, Any] = {"kind": "expression", "source": "dictionary"}
    aggregation = "formula"
    sql = hint
    lower = hint.lower()
    if lower.startswith("avg(") or "average" in lower:
        aggregation = "avg"
    elif lower.startswith("sum("):
        aggregation = "sum"
    elif lower.startswith("count("):
        aggregation = "count"
    if "hour" in lower and "opened" in lower:
        compute = {
            "kind": "duration_hours",
            "start_column": "opened_at",
            "end_column": "first_response_at",
            "aggregation": "avg",
            "source": "dictionary",
        }
        sql = "AVG(TIMESTAMPDIFF(HOUR, opened_at, first_response_at))"
        aggregation = "avg"
    return sql, aggregation, compute


def compile_domain(pkg: DomainPackage, *, activate: bool = False) -> list[MetricVersion]:
    errors = validate_package(pkg)
    if errors:
        raise OnboardingError("Cannot compile an incomplete package:\n- " + "\n- ".join(errors))

    transactional = next(
        (e for e in pkg.entities if e.entity_kind == "transactional"),
        pkg.entities[0],
    )
    blocked = restricted_columns(pkg)
    drafted: list[MetricVersion] = []

    for kpi in pkg.dictionary.kpis:
        sql, aggregation, compute = _draft_sql(kpi)
        _assert_expression_only(sql, f"KPI {kpi.family}")
        for col in blocked:
            if re.search(rf"\b{re.escape(col)}\b", sql):
                raise OnboardingError(
                    f"KPI {kpi.family} formula references restricted column {col}"
                )
        scopes = kpi.scopes or ["global"]
        for scope in scopes:
            filter_sql = None
            compute_scope = dict(compute)
            if scope != "global":
                filter_sql = f"region = '{scope.upper()}'"
                compute_scope["filter"] = {
                    "column": "region",
                    "op": "eq",
                    "value": scope.upper(),
                }
            metric_id = f"metric.{pkg.contract.domain}.{kpi.family}_{scope}"
            drafted.append(
                MetricVersion(
                    id=metric_id,
                    family=kpi.family,
                    name=f"{kpi.name} ({scope})",
                    scope=scope,
                    default_for_family=scope == "global" or (len(scopes) == 1),
                    version="1.0.0",
                    status="certified" if activate else "proposed",
                    data_product_id=transactional.data_product_id,
                    grain=kpi.grain,
                    aggregation=aggregation,  # type: ignore[arg-type]
                    sql_expression=sql,
                    filter_sql=filter_sql,
                    compute=compute_scope,
                    synonyms=list(kpi.synonyms) + [kpi.name, kpi.family],
                    owner=kpi.owner,
                )
            )
    return drafted


def maybe_llm_refine(formula_hint: str) -> str | None:
    """Optional LLM refinement. Disabled unless AIBI_COMPILE_LLM=true."""
    if os.environ.get("AIBI_COMPILE_LLM", "").lower() not in {"1", "true", "yes"}:
        return None
    return formula_hint
