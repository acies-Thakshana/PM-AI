"""Frontend service client for local aibi backend."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aibi.ask_service import ask_business_data
from aibi.auth import authenticate, list_users
from aibi.kpi_analytics import dashboard_payload, money
from aibi.settings import get_settings, load_yaml
from aibi.semantic_service import (
    dashboard_cards,
    freshness_summary,
    load_semantic_core,
    sample_questions_for_user,
)


def get_filter_catalog() -> dict[str, Any]:
    cfg = load_yaml(get_settings().dashboard_config_path)
    return cfg.get("filter_catalog") or {}


def get_bootstrap(user_id: str) -> dict[str, Any]:
    user = authenticate(user_id)
    model = load_semantic_core()
    catalog = get_filter_catalog()
    # Live filter options from KPI cube, merged over static catalog.
    live = dashboard_payload(
        {
            "business_units": (
                list(user.authorized_bu_codes)
                if (user.authorized_bu_codes and not user.can_query_cross_bu)
                else None
            )
        }
    )
    live_opts = live.get("filter_options") or {}
    bu_options = list(live_opts.get("business_units") or catalog.get("business_units") or [])
    if user.authorized_bu_codes and not user.can_query_cross_bu:
        bu_options = [b for b in bu_options if b in user.authorized_bu_codes] or list(
            user.authorized_bu_codes
        )
    return {
        "user": user.model_dump(),
        "semantic_version": model.get("semantic_version"),
        "model_id": model.get("model_id"),
        "model_source": model.get("_source_path"),
        "kpi_cards": dashboard_cards(model, user.roles),
        "freshness": freshness_summary(model),
        "suggested_questions": [
            q.get("question") for q in sample_questions_for_user(model, user.roles)[:8]
        ],
        "users": [u.model_dump() for u in list_users()],
        "filter_catalog": {
            **catalog,
            "business_units": bu_options,
            "pillars": live_opts.get("pillars") or catalog.get("pillars"),
            "years": live_opts.get("years") or catalog.get("years"),
            "quarters": live_opts.get("quarters") or catalog.get("quarters"),
            "months": live_opts.get("months") or catalog.get("months"),
            "regions": live_opts.get("regions") or catalog.get("regions"),
            "categories": live_opts.get("categories") or catalog.get("categories"),
            "sites": live_opts.get("sites") or [],
        },
        "dimensions": [
            {
                "id": d.get("id"),
                "name": d.get("name"),
                "description": d.get("description"),
            }
            for d in (model.get("dimensions") or [])
        ],
    }


def get_dashboard(user_id: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    user = authenticate(user_id)
    scoped = dict(filters or {})
    if user.authorized_bu_codes and not user.can_query_cross_bu:
        requested = scoped.get("business_units") or []
        if requested:
            scoped["business_units"] = [b for b in requested if b in user.authorized_bu_codes]
        else:
            scoped["business_units"] = list(user.authorized_bu_codes)
    payload = dashboard_payload(scoped)
    summary = payload.get("summary") or {}
    cards = dashboard_cards(load_semantic_core(), user.roles)
    value_map = {
        "metric.ent.actual_productivity": summary.get("actual_productivity"),
        "metric.ent.forecast_productivity": summary.get("forecast_productivity"),
        "metric.ent.agg_productivity": summary.get("agg_productivity"),
        "metric.ent.performance_vs_target": summary.get("performance_vs_target"),
    }
    enriched = []
    for card in cards:
        mid = card["metric_id"]
        raw = value_map.get(mid)
        if mid == "metric.ent.performance_vs_target":
            display = f"{raw*100:.1f}%" if raw is not None else "n/a"
        else:
            display = money(raw)
        enriched.append({**card, "value": raw, "display_value": display})
    return {
        **payload,
        "kpi_cards": enriched,
        "user": user.model_dump(),
    }


def get_experience(domain: str = "service_ops") -> dict[str, Any]:
    """Hybrid shell contract: dashboard + copilot + drill + visuals."""
    from aibi.experience.drill import load_drills, project_only_config
    from aibi.experience.explain import load_explain_config
    from aibi.experience.visuals import load_bindings, render_visual, validate_visual_bindings

    errors = validate_visual_bindings(domain)
    return {
        "hybrid": {
            "dashboard": "orientation",
            "copilot": "exploration",
            "drill_down": "investigation",
            "visuals": "consumption",
        },
        "visuals": [render_visual(b) for b in load_bindings(domain)],
        "drills": project_only_config(load_drills(domain)),
        "explainability": load_explain_config(domain),
        "binding_errors": errors,
    }


def ask(
    question: str,
    user_id: str,
    visible_metric_ids: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    apply_dashboard_filters: bool = False,
) -> dict[str, Any]:
    return ask_business_data(
        question,
        user_id=user_id,
        ui_context={
            "visible_metric_ids": visible_metric_ids or [],
            "filters": filters or {},
            "apply_dashboard_filters": apply_dashboard_filters,
        },
    )
