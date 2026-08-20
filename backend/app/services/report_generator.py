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
from app.services import chart_xml, pivot_engine, report_style as style

MAX_CHART_ROWS = 20

REPORT_NAME = "Eduka Report"  # standing report title/filename -- not derived from the uploaded source file's name

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


def _blank_label(value) -> str:
    """Mirrors Excel's own PivotChart convention: a missing group value reads
    as "(blank)" rather than the Python str() of None/NaN leaking through."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return style.BLANK_LABEL
    text = str(value).strip()
    if not text or text.lower() in ("none", "nan"):
        return style.BLANK_LABEL
    return text


def _grouped_bar_data(rows: list[dict], level1_col: str, level2_col: str, metric_label: str):
    """Shapes two-level pivot rows into level1 -> [(level2, value), ...]
    groups for a multi-level-category bar chart: one bar per (level1, level2)
    pair, grouped on the category axis by level1 -- this is an Excel
    PivotChart's own two-level axis, not a colour-coded legend, so every
    individual level2 value (e.g. grower) gets its own labelled bar instead
    of being folded into an "Other" series.

    Groups sort alphabetically with the blank/missing group pushed last;
    leaves within a group sort by value descending -- matches the reference
    deck's own ordering. Total bar count is capped at MULTI_LEVEL_MAX_LEAVES,
    dropping the lowest-value pairs first."""
    groups: "OrderedDict[str, list[tuple[str, float]]]" = OrderedDict()
    for r in _numeric_rows(rows, metric_label):
        l1, l2 = _blank_label(r.get(level1_col)), _blank_label(r.get(level2_col))
        groups.setdefault(l1, []).append((l2, r[metric_label]))

    ordered_keys = sorted(groups, key=lambda k: (k == style.BLANK_LABEL, k.lower()))
    result = [(key, sorted(groups[key], key=lambda pair: -pair[1])) for key in ordered_keys]

    leaf_total = sum(len(leaves) for _, leaves in result)
    if leaf_total > style.MULTI_LEVEL_MAX_LEAVES:
        flat = [(key, l2, v) for key, leaves in result for l2, v in leaves]
        kept = {(key, l2) for key, l2, v in sorted(flat, key=lambda t: -t[2])[: style.MULTI_LEVEL_MAX_LEAVES]}
        result = [(key, [(l2, v) for l2, v in leaves if (key, l2) in kept]) for key, leaves in result]
        result = [(key, leaves) for key, leaves in result if leaves]

    return result


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


# -- chart styling (module-level so report_template_builder.py can reuse it
# for the same look on a template-based deck) -------------------------------

def style_axes_grid(category_axis, value_axis):
    """Left value-axis line + bottom category-axis line, both made visible,
    plus horizontal (value) and vertical (category) major gridlines --
    frames the plot without a full boxed border."""
    grid_color = RGBColor.from_string(style.GRIDLINE_COLOR_HEX)
    for axis in (category_axis, value_axis):
        axis.has_major_gridlines = True
        axis.has_minor_gridlines = False
        axis.major_gridlines.format.line.color.rgb = grid_color
        axis.major_gridlines.format.line.width = Pt(0.75)
        axis.format.line.color.rgb = MUTED
        axis.format.line.width = Pt(1)


def set_axis_title(axis, text: str):
    axis.axis_title.text_frame.text = text
    axis.axis_title.text_frame.paragraphs[0].font.size = Pt(style.CHART_AXIS_TITLE_FONT_PT)
    axis.axis_title.text_frame.paragraphs[0].font.name = style.FONT_BODY


def style_native_chart(chart, number_format: str, single_series: bool):
    style.set_chart_default_font(chart, style.CHART_DATA_LABEL_FONT_PT, style.FONT_BODY)
    chart.has_title = False
    chart.has_legend = not single_series
    if chart.has_legend:
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(style.CHART_FONT_PT)
        chart.legend.font.name = style.FONT_BODY
    plot = chart.plots[0]
    plot.has_data_labels = True
    plot.data_labels.number_format = number_format
    plot.data_labels.number_format_is_linked = False
    plot.data_labels.font.size = Pt(style.CHART_DATA_LABEL_FONT_PT)
    plot.data_labels.font.name = style.FONT_BODY
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
    style_axes_grid(chart.category_axis, chart.value_axis)
    chart.category_axis.tick_labels.font.size = Pt(style.CHART_FONT_PT)
    chart.category_axis.tick_labels.font.name = style.FONT_BODY
    chart.value_axis.tick_labels.font.size = Pt(style.CHART_FONT_PT)
    chart.value_axis.tick_labels.font.name = style.FONT_BODY


class ReportBuilder:
    def __init__(self):
        self.prs = Presentation()
        self.prs.slide_width = style.SLIDE_W
        self.prs.slide_height = style.SLIDE_H
        self._blank = self.prs.slide_layouts[BLANK_LAYOUT]
        self.slide_count = 0

    def _new_slide(self, bordered: bool = True):
        slide = self.prs.slides.add_slide(self._blank)
        self.slide_count += 1
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = WHITE
        self._side_band(slide)
        if bordered:
            self._add_border(slide)
        return slide

    def _add_border(self, slide):
        # A thin dark-navy frame just inside the slide edges -- every
        # content slide (Slide 2 onward) gets one; the cover slide doesn't.
        border = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, style.BORDER_MARGIN, style.BORDER_MARGIN,
            style.SLIDE_W - 2 * style.BORDER_MARGIN, style.SLIDE_H - 2 * style.BORDER_MARGIN,
        )
        border.fill.background()
        border.line.color.rgb = PRIMARY
        border.line.width = style.BORDER_WEIGHT
        border.shadow.inherit = False

    def _side_band(self, slide):
        # Solid navy strip down the slide's right edge, matching the Carrier
        # template's own master slide -- every content box already keeps a
        # 0.5in right margin, well clear of this band.
        band = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, style.SLIDE_W - style.SIDE_BAND_WIDTH, 0, style.SIDE_BAND_WIDTH, style.SLIDE_H
        )
        band.fill.solid()
        band.fill.fore_color.rgb = PRIMARY
        band.line.fill.background()
        band.shadow.inherit = False

    def _header(self, slide, heading: str):
        # Plain left-aligned text on the white slide background -- no
        # full-width color band. A decorative bar spanning the slide reads
        # as filler, and the reference deck's own clean look skips it too.
        box = slide.shapes.add_textbox(Inches(0.5), Inches(0.22), style.SLIDE_W - Inches(1.0), style.HEADER_HEIGHT)
        tf = box.text_frame
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.text = heading
        p.font.size = Pt(24)
        p.font.bold = True
        p.font.color.rgb = PRIMARY
        p.font.name = style.FONT_TITLE

    def _footer(self, slide):
        logo_top = style.SLIDE_H - Inches(0.365)
        slide.shapes.add_picture(str(style.LOGO_PATH), Inches(0.4), logo_top, style.LOGO_WIDTH, style.LOGO_HEIGHT)

        tb = slide.shapes.add_textbox(Inches(1.25), style.SLIDE_H - Inches(0.35), Inches(2.5), Inches(0.25))
        p = tb.text_frame.paragraphs[0]
        p.text = style.PROGRAM_TITLE
        p.font.size = Pt(12)
        p.font.color.rgb = MUTED
        p.font.name = style.FONT_BODY

        proprietary = slide.shapes.add_textbox(Inches(3.85), style.SLIDE_H - Inches(0.35), Inches(2.3), Inches(0.25))
        pr = proprietary.text_frame.paragraphs[0]
        pr.text = style.PROPRIETARY_TEXT
        pr.font.size = Pt(12)
        pr.alignment = PP_ALIGN.CENTER
        pr.font.color.rgb = MUTED
        pr.font.name = style.FONT_BODY

        page = slide.shapes.add_textbox(Inches(8.6), style.SLIDE_H - Inches(0.35), Inches(0.9), Inches(0.25))
        pp = page.text_frame.paragraphs[0]
        pp.text = str(self.slide_count)
        pp.font.size = Pt(12)
        pp.alignment = PP_ALIGN.RIGHT
        pp.font.color.rgb = MUTED
        pp.font.name = style.FONT_BODY

    def _caption(self, slide, text: str, top):
        box = slide.shapes.add_textbox(Inches(0.5), top, style.SLIDE_W - Inches(1.0), Inches(0.35))
        tf = box.text_frame
        tf.word_wrap = True
        tf.text = text
        run = tf.paragraphs[0].runs[0]
        run.font.size = Pt(12)
        run.font.color.rgb = MUTED
        run.font.name = style.FONT_BODY

    # -- slides ---------------------------------------------------------------
    def add_title_slide(self, title: str, subtitle: str | None):
        """Cover slide: logo top-left, title/subtitle on the left, and a
        photo-collage-shaped block of flat colour on the right -- no actual
        photography is available for this deck, so solid colour panels stand
        in for where a Carrier-branded cover would place its imagery, rather
        than faking or downloading photos."""
        slide = self._new_slide(bordered=False)

        slide.shapes.add_picture(str(style.LOGO_PATH), Inches(0.4), Inches(0.35), style.TITLE_LOGO_WIDTH, style.TITLE_LOGO_HEIGHT)

        tf = slide.shapes.add_textbox(Inches(0.4), Inches(3.1), Inches(3.9), Inches(1.6)).text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(28)
        p.font.bold = True
        p.font.color.rgb = PRIMARY
        p.font.name = style.FONT_TITLE
        if subtitle:
            p2 = tf.add_paragraph()
            p2.text = subtitle
            p2.font.size = Pt(13)
            p2.font.color.rgb = MUTED
            p2.font.name = style.FONT_BODY

        # Photo-collage stand-in: one large panel above two smaller ones,
        # occupying the right half of the slide (clear of the side band).
        collage_x, collage_w = Inches(4.6), style.SLIDE_W - Inches(4.6) - Inches(0.3)
        large = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, collage_x, Inches(0.5), collage_w, Inches(3.6))
        large.fill.solid()
        large.fill.fore_color.rgb = PRIMARY
        large.line.fill.background()
        large.shadow.inherit = False

        gap = Inches(0.2)
        small_w = (collage_w - gap) / 2
        for i, hex_color in enumerate((style.BAR_PALETTE_HEX[3], style.BAR_PALETTE_HEX[4])):  # teal, amber
            small = slide.shapes.add_shape(
                MSO_SHAPE.ROUNDED_RECTANGLE, collage_x + i * (small_w + gap), Inches(4.3), small_w, Inches(2.4)
            )
            small.fill.solid()
            small.fill.fore_color.rgb = RGBColor.from_string(hex_color)
            small.line.fill.background()
            small.shadow.inherit = False

    def add_grouped_bar_slide(self, heading: str, description: str, groups: list[tuple[str, list[tuple[str, float]]]],
                               y_axis_title: str, category_axis_title: str):
        """`groups` is level1 -> [(level2, value), ...], as built by
        `_grouped_bar_data`. Rendered as a single-series, multi-level
        category-axis chart -- one navy bar per (level1, level2) pair,
        grouped visually by level1 -- matching an Excel PivotChart's own
        two-level axis rather than a colour-coded legend."""
        slide = self._new_slide()
        self._header(slide, heading)
        self._caption(slide, description, top=Inches(0.6))

        data = CategoryChartData()
        values = []
        for level1_label, leaves in groups:
            category = data.categories.add_category(level1_label)
            for level2_label, value in leaves:
                category.add_sub_category(level2_label)
                values.append(value)
        data.add_series(y_axis_title, values)

        gf = slide.shapes.add_chart(
            XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.5), style.CHART_TOP,
            style.SLIDE_W - Inches(1.0), style.SLIDE_H - style.CHART_TOP - Inches(0.6), data,
        )
        chart = gf.chart
        style_native_chart(chart, number_format="#,##0", single_series=True)
        set_axis_title(chart.value_axis, y_axis_title)
        set_axis_title(chart.category_axis, category_axis_title)
        self._footer(slide)

    def add_combo_slide(self, heading: str, description: str, categories: list[str], category_axis_title: str,
                         bar_name: str, bar_values: list[float], line_name: str, line_values: list[float]):
        slide = self._new_slide()
        self._header(slide, heading)
        self._caption(slide, description, top=Inches(0.6))

        gf = chart_xml.add_combo_chart(
            slide, Inches(0.5), style.CHART_TOP, style.SLIDE_W - Inches(1.0), style.SLIDE_H - style.CHART_TOP - Inches(0.6),
            categories=categories, bar_series_name=bar_name, bar_values=bar_values,
            line_series_name=line_name, line_values=line_values,
            bar_color_hex=style.BAR_COLOR_HEX, line_color_hex=style.LINE_COLOR_HEX,
            bar_axis_title=bar_name, line_axis_title=line_name,
        )
        chart = gf.chart
        chart.has_legend = True
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(style.CHART_FONT_PT)
        chart.legend.font.name = style.FONT_BODY
        for plot, fmt in zip(chart.plots, ('0"%"', "#,##0")):
            plot.has_data_labels = True
            plot.data_labels.number_format = fmt
            plot.data_labels.number_format_is_linked = False
            plot.data_labels.font.size = Pt(style.CHART_DATA_LABEL_FONT_PT)
            plot.data_labels.font.name = style.FONT_BODY
        # category_axis/tick fonts and the primary value axis's title,
        # gridlines, axis line, and tick font are ALL set inside
        # add_combo_chart -- once a secondary c:valAx exists, python-pptx's
        # own chart.value_axis resolves to the secondary one here, not the
        # primary, so touching axis styling from this side would silently
        # land on the wrong axis (see add_combo_chart's docstring).
        set_axis_title(chart.category_axis, category_axis_title)
        self._footer(slide)

    def add_simple_chart_slide(self, heading: str, description: str, categories: list[str], category_axis_title: str,
                                metric_label: str, values: list[float], is_trend: bool):
        slide = self._new_slide()
        self._header(slide, heading)
        self._caption(slide, description, top=Inches(0.6))

        data = CategoryChartData()
        data.categories = categories
        data.add_series(metric_label, values)

        chart_type = XL_CHART_TYPE.LINE_MARKERS if is_trend else XL_CHART_TYPE.COLUMN_CLUSTERED
        gf = slide.shapes.add_chart(
            chart_type, Inches(0.5), style.CHART_TOP, style.SLIDE_W - Inches(1.0), style.SLIDE_H - style.CHART_TOP - Inches(0.6), data,
        )
        chart = gf.chart
        style_native_chart(chart, number_format="#,##0.##", single_series=True)
        set_axis_title(chart.value_axis, metric_label)
        set_axis_title(chart.category_axis, category_axis_title)
        self._footer(slide)

    def add_summary_slide(self, heading: str, overall: OverallAnalysisReport | None):
        slide = self._new_slide()
        self._header(slide, heading)

        if overall is None:
            self._caption(slide, "No overall analysis had been generated for this session yet.", top=Inches(0.6))
            self._footer(slide)
            return

        box = slide.shapes.add_textbox(Inches(0.5), Inches(0.75), style.SLIDE_W - Inches(1.0), Inches(1.5))
        tf = box.text_frame
        tf.word_wrap = True
        tf.text = overall.narrative
        tf.paragraphs[0].font.size = Pt(12)
        tf.paragraphs[0].font.color.rgb = DARK_TEXT
        tf.paragraphs[0].font.name = style.FONT_BODY

        list_box = slide.shapes.add_textbox(Inches(0.5), Inches(2.4), style.SLIDE_W - Inches(1.0), style.SLIDE_H - Inches(2.9))
        tf2 = list_box.text_frame
        tf2.word_wrap = True
        for i, h in enumerate(overall.highlights):
            p = tf2.paragraphs[0] if i == 0 else tf2.add_paragraph()
            p.text = f"•  {h.label}: {h.value}"
            p.font.size = Pt(12)
            p.font.color.rgb = DARK_TEXT
            p.font.name = style.FONT_BODY
            p.space_after = Pt(8)
        self._footer(slide)

    def save_bytes(self) -> bytes:
        buffer = io.BytesIO()
        self.prs.save(buffer)
        return buffer.getvalue()


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
