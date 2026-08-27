const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

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

// Shape of a manually-defined custom KPI (see AddKpiForm) -- sent straight
// back to the backend as an `extra_features` entry when added.
export type CustomFeatureType = "duration_hours" | "ratio" | "extract_month" | "custom_formula";

export interface CustomFeature {
  id: string;
  name: string;
  description: string;
  output_column: string;
  type: CustomFeatureType;
  formula: string;
  summary: string;
  start_column: string | null;
  end_column: string | null;
  unit: string | null;
  numerator_columns: string[] | null;
  denominator_columns: string[] | null;
  source_columns: string[] | null;
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

// Shape of a manually-defined custom analysis (see AddPivotForm) -- sent
// straight back to the backend as an `extra_pivots` entry when added.
export interface CustomPivot {
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

export interface OverallHighlight {
  label: string;
  value: string;
}

export interface OverallAnalysisReport {
  session_id: string;
  row_count: number;
  highlights: OverallHighlight[];
  // AI-written (Groq) executive-summary paragraph, or its deterministic
  // fallback sentence if Groq isn't configured/available.
  narrative: string;
}

export interface LanguageOption {
  code: string;
  name: string;
}

export interface SupportedLanguagesResponse {
  languages: LanguageOption[];
}

export class AuditApiError extends Error {}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body.detail ?? response.statusText;
  } catch {
    return response.statusText;
  }
}

export async function uploadForAudit(source: string, file: File): Promise<AuditReport> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("source", source);

  const response = await fetch(`${API_BASE_URL}/api/audit/upload`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function resolveIssue(
  sessionId: string,
  issueId: string,
  decisionId: string,
  selectedItems?: string[]
): Promise<AuditReport> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ issue_id: issueId, decision_id: decisionId, selected_items: selectedItems ?? null }),
  });

  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function revertIssue(sessionId: string, issueId: string): Promise<AuditReport> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/issues/${issueId}/revert`, {
    method: "POST",
  });

  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export function downloadCleansedFileUrl(sessionId: string): string {
  return `${API_BASE_URL}/api/audit/${sessionId}/download`;
}

/** `language` is a code from fetchSupportedLanguages() (default "en", the
 * report's own no-translation language) -- appended as a query param only
 * when it isn't "en", so an unset/English selection hits the exact same
 * URL as before this existed. */
export function downloadReportUrl(sessionId: string, language: string = "en"): string {
  const base = `${API_BASE_URL}/api/analysis/${sessionId}/report`;
  return language === "en" ? base : `${base}?language=${encodeURIComponent(language)}`;
}

export async function applyFeatures(sessionId: string, extraFeatures: CustomFeature[] = []): Promise<FeatureReport> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/features`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ extra_features: extraFeatures }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function fetchFeatureReport(sessionId: string): Promise<FeatureReport> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/features`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export interface IssueRowsResponse {
  issue_id: string;
  total_matching: number;
  returned: number;
  columns: string[];
  rows: Record<string, unknown>[];
}

export async function fetchIssueRows(sessionId: string, issueId: string): Promise<IssueRowsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/issues/${issueId}/rows`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function fetchPreview(sessionId: string, rows = 20): Promise<DataPreview> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/preview?rows=${rows}`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function uploadFeatureDefinitions(file: File): Promise<FeatureDefinitionsSummary> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/features/definitions`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function uploadPivotDefinitions(file: File): Promise<PivotDefinitionsSummary> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/analysis/definitions`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function uploadReportTemplate(file: File): Promise<ReportTemplateSummary> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/analysis/report-template`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function applyPivots(
  sessionId: string,
  /** Omit (undefined) to leave whatever custom pivots were last applied
   * for this session alone -- e.g. the Report page changing only filters
   * shouldn't have to resend the Analysis page's full accepted list. */
  extraPivots?: CustomPivot[],
  pivotFilters: Record<string, PivotFilter[]> = {}
): Promise<PivotReport> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/pivots`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...(extraPivots !== undefined ? { extra_pivots: extraPivots } : {}),
      pivot_filters: pivotFilters,
    }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

// -- Overall report filter ---------------------------------------------------
// Report-time only -- never recomputes a pivot's own rows/table on the
// Analysis page. ONE shared filter set for the whole report: a column with
// 2+ selected values fans out into one slide per value, for every pivot.

export interface ReportFiltersResponse {
  session_id: string;
  filters: PivotFilter[];
}

export async function fetchReportFilters(sessionId: string): Promise<ReportFiltersResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/report-filters`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function saveReportFilters(sessionId: string, filters: PivotFilter[]): Promise<ReportFiltersResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/report-filters`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filters }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

// -- Per-pivot filter scope ---------------------------------------------------
// Which of the shared report_filters columns actually apply to ONE pivot --
// a pivot id absent from `scope` uses every active column (the default).

export interface ReportFilterScopeResponse {
  session_id: string;
  scope: Record<string, string[]>;
}

export async function fetchReportFilterScope(sessionId: string): Promise<ReportFilterScopeResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/report-filter-scope`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

/** `columns: null` clears the override (back to "every active column applies"). */
export async function saveReportFilterScope(
  sessionId: string,
  pivotId: string,
  columns: string[] | null
): Promise<ReportFilterScopeResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/report-filter-scope`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pivot_id: pivotId, columns }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

// -- Per-pivot report title ---------------------------------------------------
// Purely cosmetic -- renames a pivot's slide heading in the downloaded
// report. A pivot id absent from `titles` uses its own name (the default).

export interface ReportTitlesResponse {
  session_id: string;
  titles: Record<string, string>;
}

export async function fetchReportTitles(sessionId: string): Promise<ReportTitlesResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/report-titles`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

/** `title: null` (or blank) clears the override, back to the pivot's own name. */
export async function saveReportTitle(sessionId: string, pivotId: string, title: string | null): Promise<ReportTitlesResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/report-titles`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pivot_id: pivotId, title }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function fetchPivotReport(sessionId: string): Promise<PivotReport> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/pivots`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function fetchOverallAnalysis(sessionId: string): Promise<OverallAnalysisReport> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/overall`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

/** Languages the downloaded report can be translated into -- "en" (no
 * translation) is always first, followed by whatever the backend's
 * translation_service currently supports. */
export async function fetchSupportedLanguages(): Promise<SupportedLanguagesResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/languages`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}
