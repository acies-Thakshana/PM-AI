"""Build a semantic query plan before calling NL-to-SQL."""

from __future__ import annotations

import re
import uuid
from typing import Any

from aibi.auth import LocalAuthUser
from aibi.semantic_service import authorized_metrics, metric_by_id


AMBIGUOUS_PATTERNS = (
    r"^how are we performing\??$",
    r"^show me the numbers\??$",
    r"^why did it drop\??$",
    r"^compare performance\??$",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def detect_ambiguity(question: str, model: dict[str, Any]) -> list[str]:
    q = _normalize(question)
    ambiguities: list[str] = []
    for pat in AMBIGUOUS_PATTERNS:
        if re.match(pat, q):
            ambiguities.append(
                "Question is ambiguous. Specify a metric, business unit, and time period."
            )
            break
    # multiple metric synonym hits
    hits = []
    for metric in model.get("metrics") or []:
        names = [metric.get("name", "")] + list(metric.get("synonyms") or [])
        for name in names:
            token = _normalize(str(name))
            if token and token in q:
                hits.append(metric["id"])
                break
    if len(set(hits)) > 1 and "vs" not in q and "versus" not in q and "/" not in q:
        ambiguities.append(
            "Multiple metrics match this question. Choose one certified metric id."
        )
    return ambiguities


def resolve_metric_ids(question: str, model: dict[str, Any], role_ids: list[str]) -> list[str]:
    q = _normalize(question)
    allowed = authorized_metrics(model, role_ids)
    hits = []
    for metric in allowed:
        names = [metric.get("name", "")] + list(metric.get("synonyms") or [])
        for name in names:
            token = _normalize(str(name))
            if token and token in q:
                hits.append(metric["id"])
                break
    # stable unique
    seen = set()
    out = []
    for mid in hits:
        if mid not in seen:
            seen.add(mid)
            out.append(mid)
    return out


def build_semantic_query_plan(
    question: str,
    user: LocalAuthUser,
    model: dict[str, Any],
) -> dict[str, Any]:
    ambiguities = detect_ambiguity(question, model)
    metric_ids = resolve_metric_ids(question, model, user.roles)

    clarification_required = bool(ambiguities) or not metric_ids
    unsupported_reason = None
    unauthorized_reason = None

    # unauthorized cross-BU probe
    q = _normalize(question)
    if ("every business unit" in q or "all bus" in q or "across all bu" in q) and not user.can_query_cross_bu:
        unauthorized_reason = "Cross-BU questions are not authorized for this local user."
        clarification_required = False

    metrics_payload = []
    for mid in metric_ids:
        metric = metric_by_id(model, mid)
        if not metric:
            continue
        if metric.get("definition_status") == "unresolved":
            clarification_required = True
            ambiguities.append(
                f"Metric {mid} is not certified yet (definition_status=unresolved)."
            )
        metrics_payload.append(
            {
                "id": mid,
                "version": model.get("semantic_version"),
                "definition_status": metric.get("definition_status"),
                "name": metric.get("name"),
            }
        )

    products = []
    for m in metrics_payload:
        metric = metric_by_id(model, m["id"]) or {}
        products.extend(metric.get("data_product_ids") or [])

    plan = {
        "plan_id": str(uuid.uuid4()),
        "original_question": question,
        "rewritten_question": question.strip(),
        "authenticated_user": {
            "user_id": user.user_id,
            "display_name": user.display_name,
            "roles": user.roles,
        },
        "authorized_bu_scope": list(user.authorized_bu_codes),
        "intent": "unknown" if clarification_required else "analytics",
        "metrics": metrics_payload,
        "metric_versions": [model.get("semantic_version")],
        "dimensions": [],
        "entities": [],
        "requested_measures": [m["id"] for m in metrics_payload],
        "time_range": {},
        "fiscal_period": {},
        "filters": [],
        "ranking": None,
        "comparison": None,
        "variance": None,
        "grouping": [],
        "sorting": [],
        "currency": (model.get("currency_rules") or {}).get("reporting_currency"),
        "unit": None,
        "approved_data_product_ids": sorted(set(products)),
        "approved_join_ids": [
            j.get("id")
            for j in (model.get("approved_joins") or [])
            if j.get("allowed_for_nlq")
        ],
        "row_level_security_predicates": [],
        "sensitive_column_restrictions": [],
        "row_limit": ((model.get("security") or {}).get("max_rows") or 500),
        "expected_output_grain": "",
        "expected_result_schema": [],
        "visualization_intent": "auto",
        "ambiguities": ambiguities,
        "clarification_required": clarification_required and not unauthorized_reason,
        "unsupported_reason": unsupported_reason,
        "unauthorized_reason": unauthorized_reason,
        "semantic_version": model.get("semantic_version"),
        "prompt_bundle_version": (model.get("compatibility") or {}).get(
            "prompt_bundle_version"
        ),
        "dashboard_independent": True,
    }

    if user.authorized_bu_codes and not user.can_query_cross_bu:
        plan["row_level_security_predicates"] = [
            f"BU IN ({', '.join(repr(b) for b in user.authorized_bu_codes)})"
        ]
        plan["filters"].append(
            {
                "dimension_id": "dim.ent.business_unit",
                "op": "in",
                "values": list(user.authorized_bu_codes),
            }
        )

    return plan
