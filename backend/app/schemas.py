"""Pydantic response models for the data audit API."""
from typing import Any, Literal

from pydantic import BaseModel

Severity = Literal["info", "warning", "critical"]
IssueStatus = Literal["pending", "resolved"]
ReportStatus = Literal["pending_review", "reviewed"]


class IssueOption(BaseModel):
    id: str
    label: str


class OutlierChart(BaseModel):
    """Box-plot data for one numeric column -- the standard chart for an
    IQR-based outlier finding, built from the exact same quartiles/fence the
    detector used, plus the real value of every row it flagged."""
    type: Literal["boxplot"] = "boxplot"
    column: str
    min: float
    max: float
    q1: float
    median: float
    q3: float
    lower_bound: float
    upper_bound: float
    outlier_values: list[float]


class AuditIssue(BaseModel):
    id: str
    category: str
    severity: Severity
    title: str
    description: str
    affected_row_count: int
    sample: list[dict[str, Any]] = []
    requires_decision: bool
    options: list[IssueOption] = []
    # Column names the user can individually pick for a "drop_selected"
    # decision (e.g. which of these 10 empty columns to actually drop).
    # Empty for row-level issues, which stay all-or-nothing.
    selectable_items: list[str] = []
    status: IssueStatus = "pending"
    resolution: str | None = None
    # Box-plot data for the underlying numeric column, for findings where a
    # chart says more than the description (currently: statistical_outliers).
    # None for every other category.
    chart: OutlierChart | None = None
    # Agent-written, per-finding recommendation -- set by
    # audit_agent.generate_audit_analysis after the deterministic findings are
    # computed. `recommended_action` is one of this issue's own `options` ids
    # (e.g. "drop_selected", "keep"); `recommendation` is the short why. Both
    # None if the agent didn't return a usable recommendation for this finding.
    recommended_action: str | None = None
    recommendation: str | None = None


class AuditReport(BaseModel):
    session_id: str
    source: str
    filename: str
    row_count: int
    column_count: int
    columns: list[str]
    summary: str
    issues: list[AuditIssue]
    status: ReportStatus
    # Id of the one data-mutating resolution (column drop / row removal) that
    # is currently safe to revert, i.e. the top of the undo stack. "Keep
    # as-is" resolutions aren't subject to this and can always be reverted.
    revertible_issue_id: str | None = None


class ResolveRequest(BaseModel):
    issue_id: str
    decision_id: str
    selected_items: list[str] | None = None


class FeatureResult(BaseModel):
    id: str
    name: str
    description: str
    output_column: str
    non_null_count: int
    null_count: int
    distribution: dict[str, int] = {}
    stats: dict[str, float] = {}


class FeatureReport(BaseModel):
    session_id: str
    row_count: int
    column_count: int
    columns: list[str]
    features: list[FeatureResult]
    skipped_notes: list[str] = []


class FeatureDefinitionsSummary(BaseModel):
    filename: str
    feature_count: int
    feature_names: list[str]


class FeatureSuggestion(BaseModel):
    """One AI-proposed feature -- shaped so the frontend can echo it straight
    back as an `extra_features` entry when the user accepts it, no
    reshaping needed. Only the fields relevant to `type` are populated."""
    id: str
    name: str
    description: str
    output_column: str
    type: str
    formula: str
    summary: str
    start_column: str | None = None
    end_column: str | None = None
    unit: str | None = None
    numerator_columns: list[str] | None = None
    denominator_columns: list[str] | None = None
    source_columns: list[str] | None = None


class SuggestFeaturesRequest(BaseModel):
    session_id: str


class FeatureSuggestionsResponse(BaseModel):
    session_id: str
    suggestions: list[FeatureSuggestion]


class ApplyFeaturesRequest(BaseModel):
    extra_features: list[dict[str, Any]] = []


AggType = Literal["sum", "mean", "count", "min", "max", "median", "distinct_count", "pct_of_total"]


class PivotMetricSpec(BaseModel):
    column: str
    agg: AggType
    output_label: str


class PivotFilterSpec(BaseModel):
    column: str
    op: Literal["eq", "neq", "gt", "gte", "lt", "lte", "in"]
    value: Any


class PivotSortSpec(BaseModel):
    metric: str
    direction: Literal["asc", "desc"] = "desc"


class PivotResult(BaseModel):
    id: str
    name: str
    description: str
    group_by: list[str]
    metric_labels: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    # Columns this pivot can be sliced by at runtime, and the distinct
    # values available for each -- lets the frontend render a slicer/filter
    # picker per column instead of baking one fixed value into the JSON spec.
    filterable_columns: list[str] = []
    filter_options: dict[str, list[str]] = {}
    # Deduplicated real combinations of the filterable columns (from the full,
    # unfiltered session data) -- lets the frontend narrow one slicer's
    # options to what actually co-occurs with the OTHER slicers' current
    # selections (e.g. picking Italy narrows Carrier to Italy's carriers)
    # without a round-trip to the backend.
    filter_combinations: list[dict[str, str]] = []


class ReportSlide(BaseModel):
    """One explicit slide in the downloaded report -- report-time only, never
    affects the pivot's own computed rows/table on the Analysis page. `title`
    is user-editable and defaults to the pivot's name. `parent_id` is set for
    a slide created by duplicating another ("+") to explore the same pivot
    with a different filter -- always points at the top-level slide for that
    pivot, so the hierarchy stays exactly two levels deep (no grandchildren)."""
    id: str
    title: str
    pivot_id: str
    filters: list[PivotFilterSpec] = []
    parent_id: str | None = None


class CreateReportSlideRequest(BaseModel):
    pivot_id: str
    title: str
    filters: list[PivotFilterSpec] = []
    parent_id: str | None = None


class UpdateReportSlideRequest(BaseModel):
    title: str | None = None
    filters: list[PivotFilterSpec] | None = None


class ReportSlidesResponse(BaseModel):
    session_id: str
    slides: list[ReportSlide]


class PivotReport(BaseModel):
    session_id: str
    row_count: int
    column_count: int
    columns: list[str]
    pivots: list[PivotResult]
    skipped_notes: list[str] = []
    # Currently-active runtime slicer filters per pivot id (same shape as
    # ApplyPivotsRequest.pivot_filters) -- lets a caller that didn't set
    # these itself (e.g. the Report page, on first load) know what's already
    # applied, so it can pre-populate its filter UI and merge in new filters
    # without clobbering the ones already saved.
    pivot_filters: dict[str, list[dict[str, Any]]] = {}


class PivotDefinitionsSummary(BaseModel):
    filename: str
    pivot_count: int
    pivot_names: list[str]


class PivotSuggestion(BaseModel):
    """One AI-proposed pivot table -- shaped so the frontend can echo it
    straight back as an `extra_pivots` entry when the user accepts it."""
    id: str
    name: str
    description: str
    group_by: list[str]
    metrics: list[PivotMetricSpec]
    filters: list[PivotFilterSpec] = []
    sort_by: PivotSortSpec | None = None
    top_n: int | None = None


class SuggestPivotsRequest(BaseModel):
    session_id: str


class SuggestPivotsResponse(BaseModel):
    session_id: str
    suggestions: list[PivotSuggestion]


class ApplyPivotsRequest(BaseModel):
    # None means "leave whatever AI/custom pivots were last applied for this
    # session alone" -- a caller that only wants to change slicer filters
    # (e.g. the Report page) can omit this instead of resending the Analysis
    # page's full accepted list. An explicit [] means "no extra pivots".
    extra_pivots: list[dict[str, Any]] | None = None
    # Runtime slicer selections, keyed by pivot id -- each value is a list of
    # filter dicts (same shape as a JSON-defined filter, typically {"column":
    # ..., "op": "in", "value": [...]}) applied IN ADDITION to that pivot's
    # own declared filters, without needing to edit/re-upload the profile.
    pivot_filters: dict[str, list[dict[str, Any]]] = {}


class OverallHighlight(BaseModel):
    label: str
    value: str


class OverallAnalysisReport(BaseModel):
    session_id: str
    row_count: int
    highlights: list[OverallHighlight]
    narrative: str
