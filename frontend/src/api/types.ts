// Shared request/response and domain types for the api/* modules. Split out
// of the former single api/audit.ts so each domain module (audit, features,
// pivots, report, analysis) can import just the types it needs.

export type Severity = "info" | "warning" | "critical";
export type IssueStatus = "pending" | "resolved";
export type ReportStatus = "pending_review" | "reviewed";

export interface IssueOption {
  id: string;
  label: string;
}

export interface OutlierChart {
  type: "boxplot";
  column: string;
  min: number;
  max: number;
  q1: number;
  median: number;
  q3: number;
  lower_bound: number;
  upper_bound: number;
  outlier_values: number[];
}

export interface AuditIssue {
  id: string;
  category: string;
  severity: Severity;
  title: string;
  description: string;
  affected_row_count: number;
  sample: Record<string, unknown>[];
  requires_decision: boolean;
  options: IssueOption[];
  selectable_items: string[];
  status: IssueStatus;
  resolution: string | null;
  recommended_action: string | null;
  recommendation: string | null;
  chart: OutlierChart | null;
}

export interface AuditReport {
  session_id: string;
  source: string;
  filename: string;
  row_count: number;
  column_count: number;
  columns: string[];
  summary: string;
  issues: AuditIssue[];
  status: ReportStatus;
  revertible_issue_id: string | null;
}

export interface FeatureResult {
  id: string;
  name: string;
  description: string;
  output_column: string;
  non_null_count: number;
  null_count: number;
  distribution: Record<string, number>;
  stats: Record<string, number>;
  // Only set for an "ai_generated" feature -- the pandas code Groq wrote to
  // compute it, after it ran successfully through the backend's sandbox.
  generated_code?: string | null;
}

export interface FeatureReport {
  session_id: string;
  row_count: number;
  column_count: number;
  columns: string[];
  features: FeatureResult[];
  skipped_notes: string[];
}

export interface DataPreview {
  session_id: string;
  row_count: number;
  preview_row_count: number;
  columns: string[];
  rows: Record<string, unknown>[];
}

export interface FeatureDefinitionsSummary {
  filename: string;
  feature_count: number;
  feature_names: string[];
}

export type FeatureSuggestionType = "duration_hours" | "ratio" | "extract_month" | "custom_formula" | "ai_generated";

export interface FeatureSuggestion {
  id: string;
  name: string;
  description: string;
  output_column: string;
  type: FeatureSuggestionType;
  formula: string;
  summary: string;
  start_column: string | null;
  end_column: string | null;
  unit: string | null;
  numerator_columns: string[] | null;
  denominator_columns: string[] | null;
  source_columns: string[] | null;
  // Only used by type "ai_generated": the plain-English ask, and the
  // pandas code Groq wrote for it (filled in after the backend computes
  // it once -- not set when the KPI is first submitted).
  calculation_prompt?: string | null;
  generated_code?: string | null;
}

export interface FeatureSuggestionsResponse {
  session_id: string;
  suggestions: FeatureSuggestion[];
}

export type PivotAgg = "sum" | "mean" | "count" | "min" | "max" | "median" | "distinct_count" | "pct_of_total";

export interface PivotMetric {
  column: string;
  agg: PivotAgg;
  output_label: string;
}

export interface PivotFilter {
  column: string;
  op: "eq" | "neq" | "gt" | "gte" | "lt" | "lte" | "in";
  value: string | number | (string | number)[];
}

export interface PivotSort {
  metric: string;
  direction: "asc" | "desc";
}

export interface PivotSuggestion {
  id: string;
  name: string;
  description: string;
  group_by: string[];
  metrics: PivotMetric[];
  filters: PivotFilter[];
  sort_by: PivotSort | null;
  top_n: number | null;
}

export interface PivotResult {
  id: string;
  name: string;
  description: string;
  group_by: string[];
  metric_labels: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  filterable_columns: string[];
  filter_options: Record<string, string[]>;
  filter_combinations: Record<string, string>[];
}

export interface PivotReport {
  session_id: string;
  row_count: number;
  column_count: number;
  columns: string[];
  pivots: PivotResult[];
  skipped_notes: string[];
  pivot_filters: Record<string, PivotFilter[]>;
}

export interface PivotDefinitionsSummary {
  filename: string;
  pivot_count: number;
  pivot_names: string[];
}

export interface ReportTemplateSummary {
  filename: string | null;
}

export interface PivotSuggestionsResponse {
  session_id: string;
  suggestions: PivotSuggestion[];
}

export interface OverallHighlight {
  label: string;
  value: string;
}

export interface OverallAnalysisReport {
  session_id: string;
  row_count: number;
  highlights: OverallHighlight[];
  narrative: string;
}

export interface IssueRowsResponse {
  issue_id: string;
  total_matching: number;
  returned: number;
  columns: string[];
  rows: Record<string, unknown>[];
}

// -- Overall report filter ---------------------------------------------------
// Report-time only -- never recomputes a pivot's own rows/table on the
// Analysis page. ONE shared filter set for the whole report: a column with
// 2+ selected values fans out into one slide per value, for every pivot.

export interface ReportFiltersResponse {
  session_id: string;
  filters: PivotFilter[];
}

// -- Per-pivot filter scope ---------------------------------------------------
// Which of the shared report_filters columns actually apply to ONE pivot --
// a pivot id absent from `scope` uses every active column (the default).

export interface ReportFilterScopeResponse {
  session_id: string;
  scope: Record<string, string[]>;
}

// -- Per-pivot report title ---------------------------------------------------
// Purely cosmetic -- renames a pivot's slide heading in the downloaded
// report. A pivot id absent from `titles` uses its own name (the default).

export interface ReportTitlesResponse {
  session_id: string;
  titles: Record<string, string>;
}
