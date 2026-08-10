const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export type Severity = "info" | "warning" | "critical";
export type IssueStatus = "pending" | "resolved";
export type ReportStatus = "pending_review" | "reviewed";

export interface IssueOption {
  id: string;
  label: string;
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

export type FeatureSuggestionType = "duration_hours" | "ratio" | "extract_month";

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
}

export interface PivotReport {
  session_id: string;
  row_count: number;
  column_count: number;
  columns: string[];
  pivots: PivotResult[];
  skipped_notes: string[];
}

export interface PivotDefinitionsSummary {
  filename: string;
  pivot_count: number;
  pivot_names: string[];
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

export async function applyFeatures(sessionId: string, extraFeatures: FeatureSuggestion[] = []): Promise<FeatureReport> {
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

export async function suggestFeatures(sessionId: string): Promise<FeatureSuggestionsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/features/suggest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
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

export async function suggestPivots(sessionId: string): Promise<PivotSuggestionsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/suggest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function applyPivots(
  sessionId: string,
  extraPivots: PivotSuggestion[] = [],
  pivotFilters: Record<string, PivotFilter[]> = {}
): Promise<PivotReport> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/pivots`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ extra_pivots: extraPivots, pivot_filters: pivotFilters }),
  });
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
