"""Strong semantic executor over the curated KPI cube (deterministic)."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from aibi.auth import LocalAuthUser
from aibi.data_product_registry import (
    bu_column_for_product,
    load_frame_for_product,
    product_for_metric,
)
from aibi.kpi_analytics import apply_filters, money
from aibi.kpi_data import (
    ACTUAL_COL,
    AGG_COL,
    BU_COL,
    FORECAST_COL,
    INIT_ID_COL,
    INIT_NAME_COL,
    PILLAR_COL,
    QUARTER_COL,
    SITE_COL,
    load_kpi_frame,
)
from aibi.semantic_service import metric_by_id, resolve_metrics_from_question


def _sum(series: pd.Series) -> float:
    return float(pd.to_numeric(series, errors="coerce").fillna(0).sum())


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _initiative_label(frame: pd.DataFrame) -> pd.Series:
    iid = frame[INIT_ID_COL].fillna("").astype(str) if INIT_ID_COL in frame.columns else ""
    name = frame[INIT_NAME_COL].fillna("").astype(str) if INIT_NAME_COL in frame.columns else ""
    return (iid.astype(str) + " - " + name.astype(str)).str.strip(" -")


def detect_intent(question: str) -> str:
    q = _norm(question)
    if re.search(r"\b(why did|root cause|miss the plan)\b", q):
        return "unsupported"
    if re.search(r"\b(how are we performing|show me the numbers)\b", q) and not re.search(
        r"\b(target|productivity|csa|climate|q[1-4]|bu)\b", q
    ):
        return "ambiguous"
    if re.search(r"\b(difference|diff)\b", q) and re.search(
        r"probab|non[\s-]*probab|\bagg\b", q
    ):
        return "prob_diff"
    if re.search(r"\b(not achieved|under|below)\b", q) and re.search(
        r"\b(50%|50 %|half|target)\b", q
    ):
        return "under_target"
    if re.search(
        r"\b(every business unit|all bus|across all bu|all business units|rank the bus)\b", q
    ):
        return "cross_bu"
    if re.search(r"\b(split|breakdown|break down|across direct|direct,? indirect)\b", q):
        return "split"
    if re.search(r"\b(top|highest|lowest|rank|ranking)\b", q):
        return "ranking"
    if re.search(
        r"\b(vs target|versus target|against the target|preforming|performing against|achievement)\b",
        q,
    ):
        return "performance"
    if re.search(r"\b(target|plan|forecast)\b", q) and re.search(
        r"\b(productivity|q[1-4]|csa|climate)\b", q
    ):
        return "forecast"
    if re.search(r"\b(probability|weighted|agg productivity|probablity)\b", q):
        return "agg"
    if re.search(r"\b(trend|over time|by quarter|by month)\b", q):
        return "trend"
    if re.search(r"\b(productivity|actual|achieved|total)\b", q):
        return "actual"
    if re.search(r"\b(target|plan|forecast)\b", q):
        return "forecast"
    if re.search(r"\b(performance)\b", q):
        return "performance"
    return "unknown"


def extract_filters_from_question(question: str, model: dict[str, Any]) -> dict[str, Any]:
    q = question or ""
    filters: dict[str, Any] = {}
    for item in model.get("synonyms") or []:
        term = str(item.get("term") or "")
        canonical = str(item.get("canonical_value") or "")
        if item.get("maps_to_kind") == "filter_value" and canonical and term:
            if re.search(rf"\b{re.escape(term)}\b", q, flags=re.IGNORECASE):
                if item.get("maps_to_id") == "dim.ent.pillar":
                    filters.setdefault("pillars", [])
                    if canonical not in filters["pillars"]:
                        filters["pillars"].append(canonical)
                else:
                    filters.setdefault("business_units", [])
                    if canonical not in filters["business_units"]:
                        filters["business_units"].append(canonical)
    frame = load_kpi_frame()
    for bu in frame[BU_COL].dropna().astype(str).unique().tolist():
        if bu and re.search(rf"\b{re.escape(bu)}\b", q, flags=re.IGNORECASE):
            filters.setdefault("business_units", [])
            if bu not in filters["business_units"]:
                filters["business_units"].append(bu)
    for pillar in ("Direct", "Indirect", "Logistics"):
        if re.search(rf"\b{pillar}s?\b", q, flags=re.IGNORECASE):
            filters.setdefault("pillars", [])
            if pillar not in filters["pillars"]:
                filters["pillars"].append(pillar)
    for quarter in ("Q1", "Q2", "Q3", "Q4"):
        if re.search(rf"\b{quarter}\b", q, flags=re.IGNORECASE):
            filters.setdefault("quarters", [])
            if quarter not in filters["quarters"]:
                filters["quarters"].append(quarter)
    year = re.search(r"\b(20\d{2})\b", q)
    if year:
        filters["years"] = [year.group(1)]
    return filters


def resolve_metric_for_intent(intent: str, model: dict[str, Any]) -> dict[str, Any] | None:
    mapping = {
        "actual": "metric.ent.actual_productivity",
        "forecast": "metric.ent.forecast_productivity",
        "performance": "metric.ent.performance_vs_target",
        "agg": "metric.ent.agg_productivity",
        "split": "metric.ent.actual_productivity",
        "ranking": "metric.ent.actual_productivity",
        "trend": "metric.ent.actual_productivity",
        "cross_bu": "metric.ent.performance_vs_target",
        "prob_diff": "metric.ent.actual_productivity",
        "under_target": "metric.ent.performance_vs_target",
    }
    mid = mapping.get(intent)
    return metric_by_id(model, mid) if mid else None


def _ok(
    *,
    answer: str,
    sql: str,
    table: dict[str, Any],
    chart_spec: dict[str, Any] | None = None,
    metric_ids: list[str] | None = None,
    warnings: list[str] | None = None,
    record_count: int = 0,
    datasets_used: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "handled": True,
        "status": "success",
        "answer": answer,
        "clarification": None,
        "sql_query": sql,
        "table": table,
        "chart_spec": chart_spec or {},
        "metric_ids": metric_ids or [],
        "warnings": warnings or [],
        "datasets_used": datasets_used or ["KPI_data"],
        "record_count": record_count,
    }


def _refuse(status: str, message: str, metric_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "handled": True,
        "status": status,
        "answer": message if status != "clarification_needed" else "",
        "clarification": message if status == "clarification_needed" else None,
        "sql_query": "",
        "table": {"columns": [], "rows": []},
        "chart_spec": {},
        "metric_ids": metric_ids or [],
        "warnings": [],
        "datasets_used": [],
    }


def _merge_ask_filters(
    *,
    question: str,
    model: dict[str, Any],
    user: LocalAuthUser,
    ui_filters: dict[str, Any] | None,
    apply_ui_filters: bool,
) -> dict[str, Any]:
    """Question text drives filters. Dashboard filters are optional and never override RLS."""
    q_filters = extract_filters_from_question(question, model)
    merged: dict[str, Any] = dict(q_filters)

    # Dashboard filters are presentation context only — off by default for Ask.
    if apply_ui_filters and ui_filters:
        for key in ("pillars", "quarters", "years", "months", "regions", "categories", "sites"):
            if not merged.get(key) and ui_filters.get(key):
                merged[key] = ui_filters[key]
        # Only apply dashboard BU filter when the question did not name a BU
        # and the user is not a cross-BU analyst asking enterprise-wide.
        if not merged.get("business_units") and ui_filters.get("business_units"):
            if not user.can_query_cross_bu:
                merged["business_units"] = list(ui_filters["business_units"])

    # RLS: BU-bound users stay in their authorized list.
    if not user.can_query_cross_bu and user.authorized_bu_codes:
        requested = merged.get("business_units") or []
        if requested:
            allowed = [b for b in requested if b in user.authorized_bu_codes]
            if not allowed:
                return {"__unauthorized__": True}
            merged["business_units"] = allowed
        else:
            merged["business_units"] = list(user.authorized_bu_codes)
    # Cross-BU users: no default BU filter → all BUs unless question names one.
    return merged


def execute_semantic_question(
    question: str,
    *,
    user: LocalAuthUser,
    model: dict[str, Any],
    ui_filters: dict[str, Any] | None = None,
    apply_ui_filters: bool = False,
) -> dict[str, Any]:
    """Answer using certified semantic metrics over registered curated data products."""
    intent = detect_intent(question)
    if intent == "unsupported":
        return _refuse(
            "refuse_unsupported",
            "Narrative root-cause questions are not supported by curated fact tables. "
            "Ask for totals, targets, performance ratios, splits, or rankings instead.",
        )
    if intent == "ambiguous":
        # Truly underspecified — do not invent; do not call LLM to guess metrics.
        return _refuse(
            "clarification_needed",
            "Please specify a certified metric (for example actual productivity, "
            "target/forecast, or performance vs target). Name a business unit only "
            "when you want a BU-scoped answer; otherwise all authorized BUs are used.",
        )
    if intent == "unknown":
        # No deterministic intent match. If synonyms still resolve a metric, continue
        # on the semantic path; otherwise defer to LLM NL-to-SQL (second stage).
        hits = resolve_metrics_from_question(question, model, user.roles)
        if hits:
            intent = "actual"
        else:
            return {
                "handled": False,
                "delegate_to_llm": True,
                "status": "delegate_llm",
                "answer": "",
                "clarification": None,
                "sql_query": "",
                "table": {"columns": [], "rows": []},
                "chart_spec": {},
                "metric_ids": [],
                "warnings": [
                    "No certified semantic intent matched; delegating to LLM NL-to-SQL "
                    "on allowlisted curated data products only."
                ],
                "datasets_used": [],
            }

    if intent == "cross_bu" and not user.can_query_cross_bu:
        return _refuse(
            "refuse_unauthorized",
            "Cross-BU questions are not authorized for this local user. "
            "Switch to local.cross_bu or ask within your authorized BU.",
            ["metric.ent.performance_vs_target"],
        )

    merged = _merge_ask_filters(
        question=question,
        model=model,
        user=user,
        ui_filters=ui_filters,
        apply_ui_filters=apply_ui_filters,
    )
    if merged.get("__unauthorized__"):
        return _refuse(
            "refuse_unauthorized",
            "Requested business unit is outside your authorized scope.",
        )

    metric = resolve_metric_for_intent(intent, model)
    if not metric:
        hits = resolve_metrics_from_question(question, model, user.roles)
        metric = hits[0] if hits else None
    metric_ids = [metric["id"]] if metric else []

    # Generic multi-dataset load via registry (KPI is one registered product).
    dataset_name = "KPI_data"
    try:
        product = product_for_metric(model, metric)
        frame = apply_filters(load_frame_for_product(product["id"]), merged)
        dataset_name = str(product.get("physical_dataset") or product["id"])
        # Keep BU_COL aligned if product uses a different column name
        bu_col = bu_column_for_product(product)
        if bu_col != BU_COL and bu_col in frame.columns and BU_COL not in frame.columns:
            frame = frame.rename(columns={bu_col: BU_COL})
    except Exception:
        frame = apply_filters(load_kpi_frame(), merged)

    n = int(len(frame))
    q = _norm(question)

    if intent == "split":
        grouped = (
            frame.groupby(PILLAR_COL, dropna=False)[ACTUAL_COL]
            .apply(_sum)
            .reset_index()
            .rename(columns={ACTUAL_COL: "actual_productivity"})
            .sort_values("actual_productivity", ascending=False)
        )
        rows = grouped.to_dict(orient="records")
        parts = [f"{r[PILLAR_COL]}: {money(r['actual_productivity'])}" for r in rows]
        return _ok(
            answer="Productivity split by pillar - " + "; ".join(parts) if parts else "No rows matched.",
            sql=f'SELECT "{PILLAR_COL}", SUM("{ACTUAL_COL}") AS actual_productivity FROM {dataset_name} GROUP BY 1',
            table={"columns": [PILLAR_COL, "actual_productivity"], "rows": rows},
            chart_spec={"type": "bar", "x": PILLAR_COL, "y": "actual_productivity", "title": "By pillar"},
            metric_ids=metric_ids,
            record_count=n,
            datasets_used=[dataset_name],
        )

    if intent == "prob_diff":
        actual = _sum(frame[ACTUAL_COL])
        agg = _sum(frame[AGG_COL])
        diff = actual - agg
        return _ok(
            answer=(
                f"Non-probability (actual) {money(actual)} vs probability-weighted "
                f"{money(agg)}; difference (actual - weighted) is {money(diff)}."
            ),
            sql=(
                f'SELECT SUM("{ACTUAL_COL}") AS actual, SUM("{AGG_COL}") AS weighted, '
                f'SUM("{ACTUAL_COL}") - SUM("{AGG_COL}") AS diff FROM KPI_data'
            ),
            table={
                "columns": ["actual", "weighted", "difference"],
                "rows": [{"actual": actual, "weighted": agg, "difference": diff}],
            },
            metric_ids=["metric.ent.actual_productivity", "metric.ent.agg_productivity"],
            record_count=n,
        )

    if intent == "under_target":
        site_g = (
            frame.groupby(SITE_COL, dropna=False)
            .agg(
                **{
                    "actual": (ACTUAL_COL, _sum),
                    "forecast": (FORECAST_COL, _sum),
                }
            )
            .reset_index()
        )
        # Meaningful under-target: positive forecast, performance in [0, 0.5).
        site_g = site_g[site_g["forecast"] > 0].copy()
        site_g["performance"] = site_g["actual"] / site_g["forecast"]
        under = site_g[(site_g["performance"] >= 0) & (site_g["performance"] < 0.5)].copy()
        under = under.sort_values("performance", ascending=True).head(5)
        rows = under.to_dict(orient="records")
        parts = [
            f"{r[SITE_COL]} ({r['performance']*100:.1f}% | actual {money(r['actual'])} / target {money(r['forecast'])})"
            for r in rows
        ]
        return _ok(
            answer="Top 5 sites under 50% of target - "
            + ("; ".join(parts) if parts else "none found with positive target."),
            sql=(
                f'SELECT "{SITE_COL}", SUM("{ACTUAL_COL}")/NULLIF(SUM("{FORECAST_COL}"),0) AS perf '
                f'FROM KPI_data GROUP BY 1 HAVING SUM("{FORECAST_COL}") > 0 AND perf >= 0 AND perf < 0.5 '
                f"ORDER BY perf ASC LIMIT 5"
            ),
            table={"columns": list(under.columns), "rows": rows},
            chart_spec={"type": "bar", "orientation": "h", "x": "performance", "y": SITE_COL},
            metric_ids=["metric.ent.performance_vs_target"],
            record_count=n,
        )

    if intent == "ranking" or intent == "cross_bu":
        lowest = bool(re.search(r"\blowest\b", q))
        ascending = lowest
        limit_m = re.search(r"\btop\s+(\d+)\b", q)
        limit = int(limit_m.group(1)) if limit_m else (3 if re.search(r"\btop\b", q) else 10)
        if re.search(r"\b20\b", q) and re.search(r"\b(project|initiative)", q):
            limit = 20

        use_perf = bool(re.search(r"\bperformance\b", q)) or intent == "cross_bu"

        # Compound: "Which BU has highest productivity in Q3? Name top 3 projects"
        if re.search(r"\bbu\b", q) and re.search(r"\b(project|initiative)", q):
            bu_rank = (
                frame.groupby(BU_COL, dropna=False)[ACTUAL_COL]
                .apply(_sum)
                .reset_index()
                .rename(columns={ACTUAL_COL: "actual_productivity"})
                .sort_values("actual_productivity", ascending=False)
            )
            top_bu = bu_rank.iloc[0][BU_COL] if not bu_rank.empty else None
            tmp = frame[frame[BU_COL] == top_bu].copy() if top_bu is not None else frame.copy()
            tmp["_initiative"] = _initiative_label(tmp)
            projects = (
                tmp.groupby("_initiative", dropna=False)[ACTUAL_COL]
                .apply(_sum)
                .reset_index()
                .rename(columns={"_initiative": "initiative", ACTUAL_COL: "actual_productivity"})
                .sort_values("actual_productivity", ascending=False)
                .head(3)
            )
            rows = projects.to_dict(orient="records")
            proj_bits = "; ".join(
                f"{i+1}. {r['initiative']} ({money(r['actual_productivity'])})"
                for i, r in enumerate(rows)
            )
            bu_val = float(bu_rank.iloc[0]["actual_productivity"]) if not bu_rank.empty else 0.0
            answer = (
                f"Highest BU is {top_bu} ({money(bu_val)}). Top 3 projects: {proj_bits}"
                if top_bu
                else "No rows matched."
            )
            return _ok(
                answer=answer,
                sql=(
                    f'SELECT "{BU_COL}", SUM("{ACTUAL_COL}") FROM KPI_data GROUP BY 1 ORDER BY 2 DESC; '
                    f'SELECT initiative, SUM("{ACTUAL_COL}") FROM KPI_data WHERE "{BU_COL}" = :top_bu GROUP BY 1 ORDER BY 2 DESC LIMIT 3'
                ),
                table={
                    "columns": ["initiative", "actual_productivity", "top_bu"],
                    "rows": [{**r, "top_bu": top_bu} for r in rows],
                },
                chart_spec={"type": "bar", "x": "actual_productivity", "y": "initiative"},
                metric_ids=["metric.ent.actual_productivity"],
                record_count=n,
            )

        if re.search(r"\b(project|initiative)", q):
            tmp = frame.copy()
            tmp["_initiative"] = _initiative_label(tmp)
            if re.search(r"\b(site|bu)\b", q):
                grouped = tmp.groupby("_initiative", dropna=False).agg(
                    actual_productivity=(ACTUAL_COL, _sum),
                    site=(SITE_COL, lambda s: s.mode().iloc[0] if len(s.mode()) else ""),
                    bu=(BU_COL, lambda s: s.mode().iloc[0] if len(s.mode()) else ""),
                ).reset_index().rename(columns={"_initiative": "initiative"})
            else:
                grouped = (
                    tmp.groupby("_initiative", dropna=False)[ACTUAL_COL]
                    .apply(_sum)
                    .reset_index()
                    .rename(columns={"_initiative": "initiative", ACTUAL_COL: "actual_productivity"})
                )
            grouped = grouped.sort_values("actual_productivity", ascending=ascending).head(limit)
            dim_name = "initiative"
            value_col = "actual_productivity"
            metric_ids = ["metric.ent.actual_productivity"]
        elif use_perf:
            dim = BU_COL if (intent == "cross_bu" or re.search(r"\bbu", q)) else SITE_COL
            grouped = (
                frame.groupby(dim, dropna=False)
                .agg(actual=(ACTUAL_COL, _sum), forecast=(FORECAST_COL, _sum))
                .reset_index()
            )
            grouped["performance"] = grouped.apply(
                lambda r: (r["actual"] / r["forecast"]) if r["forecast"] else None, axis=1
            )
            grouped = grouped.dropna(subset=["performance"]).sort_values(
                "performance", ascending=ascending
            ).head(limit)
            dim_name = dim
            value_col = "performance"
            metric_ids = ["metric.ent.performance_vs_target"]
        else:
            dim = SITE_COL if re.search(r"\bsites?\b", q) else BU_COL
            if re.search(r"\bbus?\b", q) and not re.search(r"\bsites?\b", q):
                dim = BU_COL
            grouped = (
                frame.groupby(dim, dropna=False)[ACTUAL_COL]
                .apply(_sum)
                .reset_index()
                .rename(columns={ACTUAL_COL: "actual_productivity"})
                .sort_values("actual_productivity", ascending=ascending)
                .head(limit)
            )
            dim_name = dim
            value_col = "actual_productivity"
            metric_ids = ["metric.ent.actual_productivity"]

        rows = grouped.to_dict(orient="records")

        def _fmt(r: dict[str, Any]) -> str:
            label = r.get(dim_name) or r.get("initiative")
            val = r.get(value_col)
            if value_col == "performance":
                return f"{label} ({val*100:.1f}%)"
            extra = ""
            if "site" in r and "bu" in r:
                extra = f" | {r.get('site')} / {r.get('bu')}"
            return f"{label}{extra} ({money(val)})"

        top = rows[: min(5, len(rows))]
        direction = "lowest" if ascending else "top"
        pretty = "; ".join(f"{i+1}. {_fmt(r)}" for i, r in enumerate(top))
        answer = f"{direction.title()} {dim_name} - {pretty}" if top else "No rows matched."
        return _ok(
            answer=answer,
            sql=f'SELECT "{dim_name}", metric FROM KPI_data GROUP BY 1 ORDER BY 2 {"ASC" if ascending else "DESC"} LIMIT {limit}',
            table={"columns": list(grouped.columns), "rows": rows},
            chart_spec={"type": "bar", "orientation": "h", "x": value_col, "y": dim_name},
            metric_ids=metric_ids,
            record_count=n,
        )

    if intent == "trend":
        grouped = (
            frame.groupby(QUARTER_COL, dropna=False)[ACTUAL_COL]
            .apply(_sum)
            .reset_index()
            .rename(columns={ACTUAL_COL: "actual_productivity"})
        )
        order = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}
        grouped["_ord"] = grouped[QUARTER_COL].map(lambda x: order.get(str(x), 99))
        grouped = grouped.sort_values("_ord").drop(columns=["_ord"])
        rows = grouped.to_dict(orient="records")
        parts = [f"{r[QUARTER_COL]}: {money(r['actual_productivity'])}" for r in rows]
        return _ok(
            answer="Actual productivity by quarter — " + "; ".join(parts),
            sql=f'SELECT "{QUARTER_COL}", SUM("{ACTUAL_COL}") FROM KPI_data GROUP BY 1',
            table={"columns": [QUARTER_COL, "actual_productivity"], "rows": rows},
            chart_spec={"type": "line", "x": QUARTER_COL, "y": "actual_productivity"},
            metric_ids=metric_ids,
            record_count=n,
        )

    # Scalar / combined target+performance (CSA Q3 style)
    actual = _sum(frame[ACTUAL_COL]) if ACTUAL_COL in frame.columns else 0.0
    forecast = _sum(frame[FORECAST_COL]) if FORECAST_COL in frame.columns else 0.0
    agg = _sum(frame[AGG_COL]) if AGG_COL in frame.columns else 0.0
    ratio = (actual / forecast) if forecast else None
    scope = ", ".join(merged.get("business_units") or ["all BUs"])
    qtr = ", ".join(merged.get("quarters") or ["all quarters"])

    wants_both = bool(
        re.search(r"\b(target|forecast|plan)\b", q)
        and re.search(r"\b(performance|preforming|performing|against|achievement)\b", q)
    )
    if wants_both:
        pct = f"{ratio*100:.1f}%" if ratio is not None else "n/a"
        return _ok(
            answer=(
                f"Q3 target for {scope} is {money(forecast)}; "
                f"performance vs target is {pct} "
                f"(actual {money(actual)} / target {money(forecast)})."
                if "q3" in q
                else (
                    f"Target for {scope} ({qtr}) is {money(forecast)}; "
                    f"performance vs target is {pct} "
                    f"(actual {money(actual)} / target {money(forecast)})."
                )
            ),
            sql=(
                f'SELECT SUM("{FORECAST_COL}") AS target, '
                f'SUM("{ACTUAL_COL}")/NULLIF(SUM("{FORECAST_COL}"),0) AS performance FROM KPI_data'
            ),
            table={
                "columns": ["target", "actual", "performance"],
                "rows": [{"target": forecast, "actual": actual, "performance": ratio}],
            },
            metric_ids=[
                "metric.ent.forecast_productivity",
                "metric.ent.actual_productivity",
                "metric.ent.performance_vs_target",
            ],
            record_count=n,
        )

    if intent == "forecast":
        answer = f"Forecast / target productivity for {scope} ({qtr}) is {money(forecast)}."
        value, col, mid = forecast, FORECAST_COL, "metric.ent.forecast_productivity"
    elif intent == "agg":
        answer = f"Probability-weighted productivity for {scope} ({qtr}) is {money(agg)}."
        value, col, mid = agg, AGG_COL, "metric.ent.agg_productivity"
    elif intent == "performance":
        pct = f"{ratio*100:.1f}%" if ratio is not None else "n/a"
        answer = (
            f"Performance vs target for {scope} ({qtr}) is {pct} "
            f"(actual {money(actual)} / target {money(forecast)})."
        )
        value, col, mid = ratio, "performance_vs_target", "metric.ent.performance_vs_target"
    else:
        answer = f"Total actual productivity for {scope} ({qtr}) is {money(actual)}."
        value, col, mid = actual, ACTUAL_COL, "metric.ent.actual_productivity"

    sql = (
        f'SELECT SUM("{ACTUAL_COL}") / NULLIF(SUM("{FORECAST_COL}"),0) AS performance FROM KPI_data'
        if col == "performance_vs_target"
        else f'SELECT SUM("{col}") AS value FROM KPI_data'
    )
    return _ok(
        answer=answer,
        sql=sql,
        table={
            "columns": ["metric", "value", "rows"],
            "rows": [{"metric": mid, "value": value, "rows": n}],
        },
        metric_ids=[mid],
        record_count=n,
    )
