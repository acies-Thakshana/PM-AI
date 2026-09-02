"""Turns one PivotResult into slide(s) on a builder, and the report-filter
combo/scope logic that decides how many times each pivot gets multiplied
across a shared filter set. This is the per-pivot "what slide shape fits
this data" decision layer, distinct from both the low-level chart styling
(chart_styling.py) and the pptx-builder mechanics (report_builder.py).
"""
from app.schemas import PivotResult
from app.services.report.chart_styling import (
    MAX_CHART_ROWS,
    _combo_data,
    _grouped_bar_data,
    _is_trend_pivot,
    _numeric_rows,
)
from app.services.report.report_builder import ReportBuilder


def _percent_metric(pivot: PivotResult) -> str | None:
    return next((m for m in pivot.metric_labels if "%" in m), None)


def _add_pivot_slides(builder: ReportBuilder, pivot: PivotResult) -> None:
    """Exactly ONE slide per pivot, whatever its shape -- mirrors the
    reference GenericReportBuilder, where a pivot maps to a single slide
    call (add_grouped_bar_slide / add_combo_slide / add_simple_chart_slide),
    never one slide per metric."""
    if pivot.row_count == 0:
        return

    if len(pivot.group_by) == 2:
        level1, level2 = pivot.group_by
        # One metric drives the chart -- a 2-level group-by already spends
        # its category+series axes on the two dimensions, so the first
        # metric is the one chart; the table (and the app's Chart tab) still
        # let a viewer switch metrics interactively.
        metric_label = pivot.metric_labels[0]
        groups = _grouped_bar_data(pivot.rows, level1, level2, metric_label)
        if groups:
            builder.add_grouped_bar_slide(
                heading=pivot.name,
                description=f"{pivot.description}  (grouped by {level2})",
                groups=groups, y_axis_title=metric_label, category_axis_title=level1,
            )
            return

    if len(pivot.group_by) == 1 and len(pivot.metric_labels) == 2:
        pct_label = _percent_metric(pivot)
        other_label = next(m for m in pivot.metric_labels if m != pct_label) if pct_label else pivot.metric_labels[1]
        bar_label = pct_label or pivot.metric_labels[0]
        categories, bar_values, line_values = _combo_data(
            pivot.rows, pivot.group_by[0], bar_label, other_label, sort_by_count=not _is_trend_pivot(pivot)
        )
        if categories:
            builder.add_combo_slide(
                heading=pivot.name, description=pivot.description, categories=categories,
                category_axis_title=pivot.group_by[0],
                bar_name=bar_label, bar_values=bar_values, line_name=other_label, line_values=line_values,
            )
            return

    # Fallback: a single simple chart on the first metric that actually has
    # numeric data -- covers a plain single-group-by/single-metric pivot,
    # and anything with a shape the two special cases above don't handle
    # (3+ group-by levels, 3+ metrics, or a 2-level/2-metric case that
    # produced no rows above).
    for metric_label in pivot.metric_labels:
        rows = _numeric_rows(pivot.rows, metric_label)[:MAX_CHART_ROWS]
        if not rows:
            continue
        categories = [" / ".join(str(r.get(c, "")) for c in pivot.group_by) for r in rows]
        values = [r[metric_label] for r in rows]
        builder.add_simple_chart_slide(
            heading=pivot.name, description=pivot.description,
            categories=categories, category_axis_title=" / ".join(pivot.group_by),
            metric_label=metric_label, values=values, is_trend=_is_trend_pivot(pivot),
        )
        return


MAX_COMBOS_PER_PIVOT = 12


def _report_filter_combos(report_filters: list[dict]) -> list[list[dict]]:
    """Splits the one shared report_filters list into (fixed_filters, one
    combo per multiplier value) -- an 'in' filter with 2+ selected values is
    a MULTIPLIER (one slide per value); everything else (a single-value
    'in', or a non-'in' op like the departure-time gte/lte) is just a fixed
    filter applied to every combo. Multiple multiplier columns cartesian-
    product together, capped at MAX_COMBOS_PER_PIVOT total combos."""
    fixed: list[dict] = []
    multipliers: list[list[dict]] = []  # each entry: [{"column": c, "op": "eq", "value": v}, ...] for one column's values
    for f in report_filters:
        if f.get("op") == "in" and isinstance(f.get("value"), list) and len(f["value"]) > 1:
            multipliers.append([{"column": f["column"], "op": "eq", "value": v} for v in f["value"]])
        else:
            fixed.append(f)

    if not multipliers:
        return [fixed]

    combos = [fixed]
    for axis in multipliers:
        combos = [combo + [choice] for combo in combos for choice in axis]
    return combos[:MAX_COMBOS_PER_PIVOT]


def _combo_label(combo: list[dict], fixed_columns: set[str]) -> str:
    extra = [f["value"] for f in combo if f["column"] not in fixed_columns]
    return " / ".join(str(v) for v in extra)


# Keyed by the pivot's own NAME (PivotResult.name) rather than its id --
# id is whatever the uploaded Analysis Profile happens to assign it (an
# implementation detail that can vary per profile/upload), while the name is
# the stable, visible identity a PM actually recognizes on the Report page.
# A pivot name absent here (or not currently loaded) normally means "every
# active report_filters column applies"; these default to a narrower scope
# instead. A user can still re-enable an excluded column for one of these via
# the Report page's per-pivot filter-scope toggle -- that's a real, explicit
# override and takes precedence over this default.
DEFAULT_SCOPE_EXCLUSIONS: dict[str, set[str]] = {
    # Shipments by Product & Origin reads best sliced by Country of Origin
    # alone -- Origin/Carrier/Product all still show up as columns IN the
    # table itself, so filtering by them too is redundant.
    "Shipments by Product & Origin": {"Origin", "Carrier", "Product"},
    # Carrier Compliance Ranking always defaults to just Country of Origin +
    # Origin -- Carrier is excluded because the pivot already groups BY
    # Carrier (filtering by it too is self-defeating), and Product is
    # excluded by explicit, standing choice, not just Carrier.
    "Carrier Compliance Ranking": {"Carrier", "Product"},
    # Monthly Compliance Trend and the mode-share breakdown default to every
    # active column (no exclusion) -- deliberately, by explicit standing
    # choice, unlike the two pivots above.
}


def resolve_default_scope(pivot_name: str, active_columns: list[str]) -> list[str] | None:
    """Returns None (no restriction -- every active column applies) unless
    `pivot_name` has a default exclusion, in which case it returns
    `active_columns` minus the excluded ones."""
    excluded = DEFAULT_SCOPE_EXCLUSIONS.get(pivot_name)
    if not excluded:
        return None
    return [c for c in active_columns if c not in excluded]
