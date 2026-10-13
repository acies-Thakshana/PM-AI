"""Deterministic KPI analytics for dashboard cards and charts."""

from __future__ import annotations

from typing import Any

import pandas as pd

from aibi.kpi_data import (
    ACTUAL_COL,
    AGG_COL,
    BU_COL,
    CATEGORY_COL,
    FORECAST_COL,
    FRESH_COL,
    MONTH_COL,
    PILLAR_COL,
    QUARTER_COL,
    REGION_COL,
    SITE_COL,
    YEAR_COL,
    load_kpi_frame,
    unique_values,
)


def apply_filters(frame: pd.DataFrame, filters: dict[str, Any] | None) -> pd.DataFrame:
    out = frame
    filters = filters or {}

    def _in(column: str, values: list[Any] | None) -> None:
        nonlocal out
        if values and column in out.columns:
            cleaned = [str(v).strip() for v in values if str(v).strip()]
            if cleaned:
                out = out[out[column].astype(str).isin(cleaned)]

    _in(BU_COL, filters.get("business_units") or filters.get("bu"))
    _in(PILLAR_COL, filters.get("pillars"))
    _in(QUARTER_COL, filters.get("quarters"))
    _in(MONTH_COL, filters.get("months"))
    _in(REGION_COL, filters.get("regions"))
    _in(CATEGORY_COL, filters.get("categories"))
    _in(SITE_COL, filters.get("sites"))

    years = filters.get("years") or []
    if years and YEAR_COL in out.columns:
        year_nums = []
        for y in years:
            try:
                year_nums.append(float(y))
            except (TypeError, ValueError):
                continue
        if year_nums:
            out = out[out[YEAR_COL].isin(year_nums)]
    return out


def _sum(series: pd.Series) -> float:
    return float(pd.to_numeric(series, errors="coerce").fillna(0).sum())


def kpi_summary(filters: dict[str, Any] | None = None) -> dict[str, Any]:
    frame = apply_filters(load_kpi_frame(), filters)
    actual = _sum(frame[ACTUAL_COL]) if ACTUAL_COL in frame.columns else 0.0
    forecast = _sum(frame[FORECAST_COL]) if FORECAST_COL in frame.columns else 0.0
    agg = _sum(frame[AGG_COL]) if AGG_COL in frame.columns else 0.0
    performance = (actual / forecast) if forecast else None
    as_of = None
    if FRESH_COL in frame.columns and frame[FRESH_COL].notna().any():
        as_of = str(pd.to_datetime(frame[FRESH_COL], errors="coerce").max())
    return {
        "row_count": int(len(frame)),
        "actual_productivity": actual,
        "forecast_productivity": forecast,
        "agg_productivity": agg,
        "performance_vs_target": performance,
        "as_of": as_of,
    }


def series_by(frame: pd.DataFrame, group_col: str, value_col: str) -> pd.DataFrame:
    if group_col not in frame.columns or value_col not in frame.columns:
        return pd.DataFrame(columns=[group_col, value_col])
    grouped = (
        frame.groupby(group_col, dropna=False)[value_col]
        .apply(lambda s: _sum(s))
        .reset_index()
        .rename(columns={value_col: "value"})
    )
    grouped = grouped.sort_values("value", ascending=False)
    return grouped


def dashboard_payload(filters: dict[str, Any] | None = None) -> dict[str, Any]:
    base = load_kpi_frame()
    filtered = apply_filters(base, filters)
    summary = kpi_summary(filters)
    return {
        "summary": summary,
        "by_pillar": series_by(filtered, PILLAR_COL, ACTUAL_COL).to_dict(orient="records"),
        "by_bu": series_by(filtered, BU_COL, ACTUAL_COL).head(15).to_dict(orient="records"),
        "by_quarter": series_by(filtered, QUARTER_COL, ACTUAL_COL).to_dict(orient="records"),
        "by_region": series_by(filtered, REGION_COL, ACTUAL_COL).head(15).to_dict(orient="records"),
        "filter_options": {
            "business_units": unique_values(base, BU_COL),
            "pillars": unique_values(base, PILLAR_COL),
            "years": _year_options(base),
            "quarters": unique_values(base, QUARTER_COL),
            "months": unique_values(base, MONTH_COL),
            "regions": unique_values(base, REGION_COL),
            "categories": unique_values(base, CATEGORY_COL),
            "sites": unique_values(base, SITE_COL, limit=40),
        },
    }


def _year_options(frame: pd.DataFrame) -> list[str]:
    if YEAR_COL not in frame.columns:
        return []
    years: list[str] = []
    for value in frame[YEAR_COL].dropna().unique().tolist():
        try:
            years.append(str(int(float(value))))
        except (TypeError, ValueError):
            continue
    return sorted(set(years))


def money(value: float | None) -> str:
    if value is None:
        return "n/a"
    abs_v = abs(value)
    if abs_v >= 1_000_000:
        return f"{value/1_000_000:,.2f}M"
    if abs_v >= 1_000:
        return f"{value/1_000:,.1f}K"
    return f"{value:,.2f}"
