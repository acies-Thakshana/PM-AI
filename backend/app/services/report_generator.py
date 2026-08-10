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
"""
import io
import re
from collections import OrderedDict

import pandas as pd
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from app.schemas import OverallAnalysisReport, PivotResult
from app.services import chart_xml, report_style as style

MAX_CHART_ROWS = 20

PRIMARY = RGBColor.from_string(style.BAR_COLOR_HEX)
LINE_COLOR = RGBColor.from_string(style.LINE_COLOR_HEX)
WHITE = RGBColor.from_string(style.WHITE_HEX)
DARK_TEXT = RGBColor.from_string(style.DARK_TEXT_HEX)
MUTED = RGBColor.from_string(style.MUTED_TEXT_HEX)
BAR_PALETTE = [RGBColor.from_string(h) for h in style.BAR_PALETTE_HEX]

TITLE_LAYOUT = 0
BLANK_LAYOUT = 6

_ACTIVITY_DATE_HINTS = re.compile(r"arriv|depart|segment|trip create", re.IGNORECASE)


def _date_range_label(df: pd.DataFrame) -> str | None:
    date_cols = list(df.select_dtypes(include=["datetime64[ns]", "datetimetz"]).columns)
    if not date_cols:
        return None
    activity_cols = [c for c in date_cols if _ACTIVITY_DATE_HINTS.search(str(c))]
    date_cols = activity_cols or date_cols

    overall_min, overall_max = None, None
    for col in date_cols:
        col_min, col_max = df[col].min(), df[col].max()
        if pd.isna(col_min) or pd.isna(col_max):
            continue
        overall_min = col_min if overall_min is None or col_min < overall_min else overall_min
        overall_max = col_max if overall_max is None or col_max > overall_max else overall_max
    if overall_min is None or overall_max is None:
        return None
    return f"{overall_min:%d.%m.%Y} – {overall_max:%d.%m.%Y}"


def _is_trend_pivot(pivot: PivotResult) -> bool:
    return len(pivot.group_by) == 1 and "month" in pivot.group_by[0].lower()


def _numeric_rows(rows: list[dict], metric_label: str) -> list[dict]:
    return [r for r in rows if isinstance(r.get(metric_label), (int, float))]


def _grouped_bar_data(rows: list[dict], level1_col: str, level2_col: str, metric_label: str):
    """Shapes two-level pivot rows into (categories, series) for a clustered
    bar chart -- categories = level-1 values, one series per level-2 value.
    Caps series at MAX_GROUPED_SERIES by total contribution, folding the
    remainder into "Other" rather than generating more hues."""
    level1_totals: OrderedDict[str, float] = OrderedDict()
    level2_totals: dict[str, float] = {}
    matrix: dict[tuple[str, str], float] = {}

    for r in _numeric_rows(rows, metric_label):
        l1, l2, v = str(r.get(level1_col)), str(r.get(level2_col)), r[metric_label]
        level1_totals[l1] = level1_totals.get(l1, 0.0) + v
        level2_totals[l2] = level2_totals.get(l2, 0.0) + v
        matrix[(l1, l2)] = matrix.get((l1, l2), 0.0) + v

    categories = sorted(level1_totals, key=lambda l1: -level1_totals[l1])[:MAX_CHART_ROWS]
    top_level2 = sorted(level2_totals, key=lambda l2: -level2_totals[l2])[: style.MAX_GROUPED_SERIES]
    has_other = len(level2_totals) > len(top_level2)

    series = [{"name": l2, "values": [matrix.get((l1, l2), 0.0) for l1 in categories]} for l2 in top_level2]
    if has_other:
        other_values = [
            level1_totals[l1] - sum(matrix.get((l1, l2), 0.0) for l2 in top_level2) for l1 in categories
        ]
        series.append({"name": "Other", "values": other_values})
    return categories, series


def _combo_data(rows: list[dict], group_col: str, pct_label: str, count_label: str, sort_by_count: bool):
    scored = [r for r in rows if isinstance(r.get(pct_label), (int, float)) and isinstance(r.get(count_label), (int, float))]
    # A ranking pivot (e.g. carriers) reads best ordered by volume; a genuine
    # time trend (e.g. by month) would have that chronological order
    # scrambled by the same sort, so it keeps whatever order pivot_engine's
    # own sort_by already produced (chronological, per the Analysis Profile).
    if sort_by_count:
        scored.sort(key=lambda r: -r[count_label])
    scored = scored[:MAX_CHART_ROWS]
    categories = [str(r.get(group_col)) for r in scored]
    return categories, [r[pct_label] for r in scored], [r[count_label] for r in scored]


class ReportBuilder:
    def __init__(self):
        self.prs = Presentation()
        self.prs.slide_width = style.SLIDE_W
        self.prs.slide_height = style.SLIDE_H
        self._blank = self.prs.slide_layouts[BLANK_LAYOUT]
        self.slide_count = 0

    def _new_slide(self):
        slide = self.prs.slides.add_slide(self._blank)
        self.slide_count += 1
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = WHITE
        return slide

    def _header(self, slide, heading: str):
        band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, style.SLIDE_W, style.HEADER_HEIGHT)
        band.fill.solid()
        band.fill.fore_color.rgb = PRIMARY
        band.line.fill.background()
        band.shadow.inherit = False
        tf = band.text_frame
        tf.margin_left, tf.margin_top = Inches(0.4), Inches(0.12)
        p = tf.paragraphs[0]
        p.text = heading
        p.font.size = Pt(22)
        p.font.bold = True
        p.font.color.rgb = WHITE
        p.font.name = style.FONT_HEADING

    def _footer(self, slide):
        tb = slide.shapes.add_textbox(Inches(0.4), style.SLIDE_H - Inches(0.4), Inches(7), Inches(0.3))
        p = tb.text_frame.paragraphs[0]
        p.text = style.PROGRAM_TITLE
        p.font.size = Pt(9)
        p.font.color.rgb = MUTED
        p.font.name = style.FONT_HEADING

        page = slide.shapes.add_textbox(style.SLIDE_W - Inches(1.2), style.SLIDE_H - Inches(0.4), Inches(0.8), Inches(0.3))
        pp = page.text_frame.paragraphs[0]
        pp.text = str(self.slide_count)
        pp.font.size = Pt(9)
        pp.alignment = PP_ALIGN.RIGHT
        pp.font.color.rgb = MUTED
        pp.font.name = style.FONT_HEADING

    def _caption(self, slide, text: str, top):
        box = slide.shapes.add_textbox(Inches(0.5), top, style.SLIDE_W - Inches(1.0), Inches(0.4))
        tf = box.text_frame
        tf.word_wrap = True
        tf.text = text
        run = tf.paragraphs[0].runs[0]
        run.font.size = Pt(11)
        run.font.color.rgb = MUTED
        run.font.name = style.FONT_HEADING

    def _style_native_chart(self, chart, number_format: str, single_series: bool):
        chart.has_title = False
        chart.value_axis.has_major_gridlines = False
        chart.value_axis.has_minor_gridlines = False
        chart.has_legend = not single_series
        if chart.has_legend:
            chart.legend.position = XL_LEGEND_POSITION.BOTTOM
            chart.legend.include_in_layout = False
            chart.legend.font.size = Pt(10)
        plot = chart.plots[0]
        plot.has_data_labels = True
        plot.data_labels.number_format = number_format
        plot.data_labels.number_format_is_linked = False
        plot.data_labels.font.size = Pt(9)
        plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
        for i, series in enumerate(plot.series):
            color = BAR_PALETTE[i % len(BAR_PALETTE)]
            if chart.chart_type == XL_CHART_TYPE.LINE_MARKERS:
                series.format.line.color.rgb = color
                series.format.line.width = Pt(2.25)
                series.marker.format.fill.solid()
                series.marker.format.fill.fore_color.rgb = color
            else:
                series.format.fill.solid()
                series.format.fill.fore_color.rgb = color
        chart.category_axis.tick_labels.font.size = Pt(10)
        chart.value_axis.tick_labels.font.size = Pt(10)

    # -- slides ---------------------------------------------------------------
    def add_title_slide(self, title: str, subtitle: str | None):
        slide = self._new_slide()
        band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(2.6), style.SLIDE_W, Inches(2.3))
        band.fill.solid()
        band.fill.fore_color.rgb = PRIMARY
        band.line.fill.background()
        band.shadow.inherit = False
        tf = band.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(34)
        p.font.bold = True
        p.font.color.rgb = WHITE
        p.font.name = style.FONT_HEADING
        p.alignment = PP_ALIGN.CENTER
        if subtitle:
            p2 = tf.add_paragraph()
            p2.text = subtitle
            p2.font.size = Pt(16)
            p2.font.color.rgb = WHITE
            p2.font.name = style.FONT_HEADING
            p2.alignment = PP_ALIGN.CENTER

    def add_grouped_bar_slide(self, heading: str, description: str, categories: list[str], series: list[dict], y_axis_title: str):
        slide = self._new_slide()
        self._header(slide, heading)
        self._caption(slide, description, top=Inches(0.85))

        data = CategoryChartData()
        data.categories = categories
        for s in series:
            data.add_series(s["name"], s["values"])

        gf = slide.shapes.add_chart(
            XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.5), style.CHART_TOP,
            style.SLIDE_W - Inches(1.0), style.SLIDE_H - style.CHART_TOP - Inches(0.6), data,
        )
        chart = gf.chart
        self._style_native_chart(chart, number_format="#,##0", single_series=len(series) == 1)
        chart.value_axis.axis_title.text_frame.text = y_axis_title
        chart.value_axis.axis_title.text_frame.paragraphs[0].font.size = Pt(10)
        self._footer(slide)

    def add_combo_slide(self, heading: str, description: str, categories: list[str],
                         bar_name: str, bar_values: list[float], line_name: str, line_values: list[float]):
        slide = self._new_slide()
        self._header(slide, heading)
        self._caption(slide, description, top=Inches(0.85))

        gf = chart_xml.add_combo_chart(
            slide, Inches(0.5), style.CHART_TOP, style.SLIDE_W - Inches(1.0), style.SLIDE_H - style.CHART_TOP - Inches(0.6),
            categories=categories, bar_series_name=bar_name, bar_values=bar_values,
            line_series_name=line_name, line_values=line_values,
            bar_color_hex=style.BAR_COLOR_HEX, line_color_hex=style.LINE_COLOR_HEX,
        )
        chart = gf.chart
        chart.has_legend = True
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(10)
        for plot, fmt in zip(chart.plots, ('0"%"', "#,##0")):
            plot.has_data_labels = True
            plot.data_labels.number_format = fmt
            plot.data_labels.number_format_is_linked = False
            plot.data_labels.font.size = Pt(9)
        chart.category_axis.tick_labels.font.size = Pt(10)
        self._footer(slide)

    def add_simple_chart_slide(self, heading: str, description: str, categories: list[str], metric_label: str,
                                values: list[float], is_trend: bool):
        slide = self._new_slide()
        self._header(slide, heading)
        self._caption(slide, description, top=Inches(0.85))

        data = CategoryChartData()
        data.categories = categories
        data.add_series(metric_label, values)

        chart_type = XL_CHART_TYPE.LINE_MARKERS if is_trend else XL_CHART_TYPE.COLUMN_CLUSTERED
        gf = slide.shapes.add_chart(
            chart_type, Inches(0.5), style.CHART_TOP, style.SLIDE_W - Inches(1.0), style.SLIDE_H - style.CHART_TOP - Inches(0.6), data,
        )
        self._style_native_chart(gf.chart, number_format="#,##0.##", single_series=True)
        self._footer(slide)

    def add_summary_slide(self, heading: str, overall: OverallAnalysisReport | None):
        slide = self._new_slide()
        self._header(slide, heading)

        if overall is None:
            self._caption(slide, "No overall analysis had been generated for this session yet.", top=Inches(1.2))
            self._footer(slide)
            return

        box = slide.shapes.add_textbox(Inches(0.5), Inches(1.0), style.SLIDE_W - Inches(1.0), Inches(1.6))
        tf = box.text_frame
        tf.word_wrap = True
        tf.text = overall.narrative
        tf.paragraphs[0].font.size = Pt(14)
        tf.paragraphs[0].font.color.rgb = DARK_TEXT
        tf.paragraphs[0].font.name = style.FONT_HEADING

        list_box = slide.shapes.add_textbox(Inches(0.5), Inches(2.7), style.SLIDE_W - Inches(1.0), style.SLIDE_H - Inches(3.2))
        tf2 = list_box.text_frame
        tf2.word_wrap = True
        for i, h in enumerate(overall.highlights):
            p = tf2.paragraphs[0] if i == 0 else tf2.add_paragraph()
            p.text = f"•  {h.label}: {h.value}"
            p.font.size = Pt(13)
            p.font.color.rgb = DARK_TEXT
            p.font.name = style.FONT_HEADING
            p.space_after = Pt(10)
        self._footer(slide)

    def save_bytes(self) -> bytes:
        buffer = io.BytesIO()
        self.prs.save(buffer)
        return buffer.getvalue()


def _percent_metric(pivot: PivotResult) -> str | None:
    return next((m for m in pivot.metric_labels if "%" in m), None)


def _add_pivot_slides(builder: ReportBuilder, pivot: PivotResult) -> None:
    if pivot.row_count == 0:
        return

    if len(pivot.group_by) == 2:
        level1, level2 = pivot.group_by
        for metric_label in pivot.metric_labels:
            categories, series = _grouped_bar_data(pivot.rows, level1, level2, metric_label)
            if not categories:
                continue
            builder.add_grouped_bar_slide(
                heading=f"{pivot.name} — {metric_label}",
                description=f"{pivot.description}  (grouped by {level2})",
                categories=categories, series=series, y_axis_title=metric_label,
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
                bar_name=bar_label, bar_values=bar_values, line_name=other_label, line_values=line_values,
            )
            return

    # Fallback: one simple single-series chart per metric -- covers a single
    # group-by/single-metric pivot, and anything with a shape the two special
    # cases above don't handle (3+ group-by levels, 3+ metrics).
    for metric_label in pivot.metric_labels:
        rows = _numeric_rows(pivot.rows, metric_label)[:MAX_CHART_ROWS]
        if not rows:
            continue
        categories = [" / ".join(str(r.get(c, "")) for c in pivot.group_by) for r in rows]
        values = [r[metric_label] for r in rows]
        builder.add_simple_chart_slide(
            heading=f"{pivot.name} — {metric_label}", description=pivot.description,
            categories=categories, metric_label=metric_label, values=values, is_trend=_is_trend_pivot(pivot),
        )


def build_report(
    source_label: str,
    df: pd.DataFrame,
    pivots: list[PivotResult],
    overall: OverallAnalysisReport | None,
) -> bytes:
    builder = ReportBuilder()
    builder.add_title_slide(source_label, _date_range_label(df))

    for pivot in pivots:
        _add_pivot_slides(builder, pivot)

    builder.add_summary_slide("Summary", overall)
    return builder.save_bytes()
