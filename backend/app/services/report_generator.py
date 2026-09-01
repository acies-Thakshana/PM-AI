"""
Builds a downloadable .pptx report from the CURRENT session state: whatever
pivots are in `session.pivots` right now (with whatever slicer filters are
active) and the last-computed overall analysis. Every chart is a real,
native PowerPoint chart object -- never a picture, and never anything
carried over from a reference deck. No LLM decides slide content: every
slide, heading, and chart is 100% rule-driven from the pivot's own shape
(group_by column count, metric count) and its already-computed numbers.
The one exception is the narrative sentence on the summary slide, which is
already-computed prose handed in via `overall.narrative` -- this module
never reinterprets a raw number itself.

This module is the orchestrator only: chart data-shaping/styling lives in
report/chart_styling.py, the from-scratch pptx builder lives in
report/report_builder.py, and per-pivot slide-shape/filter-combo logic
lives in report/pivot_slides.py. Re-exports a few names below for backwards
compatibility with report_template_builder.py and routers/analysis.py,
which import them off this module directly.
"""
import pandas as pd

from app.schemas import OverallAnalysisReport, PivotResult
from app.services import pivot_engine, report_style as style
from app.services.report.chart_styling import (  # noqa: F401 -- re-exported for report_template_builder
    BAR_PALETTE,
    DARK_TEXT,
    LINE_COLOR,
    MUTED,
    PRIMARY,
    WHITE,
    _date_range_label,
    set_axis_title,
    style_axes_grid,
    style_native_chart,
)
from app.services.report.pivot_slides import (
    _add_pivot_slides,
    _combo_label,
    _report_filter_combos,
    resolve_default_scope,
)
from app.services.report.report_builder import ReportBuilder  # noqa: F401 -- re-exported

REPORT_NAME = "Eduka Report"  # standing report title/filename -- not derived from the uploaded source file's name


def build_report(
    source_label: str,
    df: pd.DataFrame,
    pivots: list[PivotResult],
    definitions: list[dict],
    report_filters: list[dict],
    pivot_filter_scope: dict[str, list[str]] | None,
    report_titles: dict[str, str] | None,
    overall: OverallAnalysisReport | None,
    template_bytes: bytes | None = None,
) -> bytes:
    """Builds the deck from EVERY current pivot, each recomputed fresh from
    the raw data using the one shared `report_filters` -- scoped down per
    pivot by `pivot_filter_scope` first (a pivot id absent there uses every
    active column, i.e. the same scope everywhere). A column with 2+
    selected values that survives scoping fans out into one slide per value
    for THAT pivot (see _report_filter_combos) -- e.g. pivot_1 scoped to
    just Country of Origin ignores an Origin multiplier entirely, while
    pivot_2 scoped to Country of Origin + Origin still multiplies by it. A
    pivot whose spec has gone missing, or that ends up with zero rows for a
    given combo, is silently skipped rather than breaking the whole export.

    `template_bytes` is an optional user-uploaded .pptx (see
    report_template_store.py) that overrides the permanent built-in default
    template (style.DEFAULT_TEMPLATE_PATH) -- either way, the deck is built
    with report_template_builder.TemplateReportBuilder, which places the
    exact same content into that file's own slide layouts/placeholders
    rather than this module's hand-positioned blank-layout shapes. Only if
    NEITHER is available (e.g. the bundled asset went missing) does this
    fall back to ReportBuilder's own from-scratch layout, so a broken/absent
    default can't take report generation down entirely. Both builders
    expose the same add_*_slide methods, so nothing below this line needs
    to know or care which one it's talking to.
    """
    if not template_bytes and style.DEFAULT_TEMPLATE_PATH.exists():
        template_bytes = style.DEFAULT_TEMPLATE_PATH.read_bytes()

    if template_bytes:
        from app.services.report_template_builder import TemplateReportBuilder
        builder = TemplateReportBuilder(template_bytes)
    else:
        builder = ReportBuilder()
    builder.add_title_slide(source_label, _date_range_label(df))

    defs_by_id = {d["id"]: d for d in definitions}
    pivot_filter_scope = pivot_filter_scope or {}
    report_titles = report_titles or {}

    for pivot in pivots:
        spec = defs_by_id.get(pivot.id)
        if not spec:
            continue
        allowed_columns = pivot_filter_scope.get(pivot.id)
        if allowed_columns is None:
            allowed_columns = resolve_default_scope(pivot.name, [f["column"] for f in report_filters])
        scoped_filters = (
            report_filters if allowed_columns is None else [f for f in report_filters if f["column"] in allowed_columns]
        )
        fixed_columns = {
            f["column"] for f in scoped_filters if not (f.get("op") == "in" and isinstance(f.get("value"), list) and len(f["value"]) > 1)
        }
        combos = _report_filter_combos(scoped_filters)
        for combo in combos:
            results, _ = pivot_engine.apply_pivots(df, [spec], pivot_filters={spec["id"]: combo})
            if not results:
                continue
            label = _combo_label(combo, fixed_columns)
            base_title = report_titles.get(pivot.id, pivot.name)
            title = f"{base_title} — {label}" if label else base_title
            pivot_result = results[0].model_copy(update={"name": title})
            _add_pivot_slides(builder, pivot_result)

    builder.add_summary_slide("Summary", overall)
    return builder.save_bytes()
