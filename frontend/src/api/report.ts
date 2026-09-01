import { API_BASE_URL, assertOk } from "./client";
import type {
  PivotFilter,
  ReportFilterScopeResponse,
  ReportFiltersResponse,
  ReportTemplateSummary,
  ReportTitlesResponse,
} from "./types";

export function downloadReportUrl(sessionId: string): string {
  return `${API_BASE_URL}/api/analysis/${sessionId}/report`;
}

export async function uploadReportTemplate(file: File): Promise<ReportTemplateSummary> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/analysis/report-template`, {
    method: "POST",
    body: formData,
  });

  await assertOk(response);
  return response.json();
}

export async function fetchReportFilters(sessionId: string): Promise<ReportFiltersResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/report-filters`);
  await assertOk(response);
  return response.json();
}

export async function saveReportFilters(sessionId: string, filters: PivotFilter[]): Promise<ReportFiltersResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/report-filters`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filters }),
  });
  await assertOk(response);
  return response.json();
}

export async function fetchReportFilterScope(sessionId: string): Promise<ReportFilterScopeResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/report-filter-scope`);
  await assertOk(response);
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
  await assertOk(response);
  return response.json();
}

export async function fetchReportTitles(sessionId: string): Promise<ReportTitlesResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/report-titles`);
  await assertOk(response);
  return response.json();
}

/** `title: null` (or blank) clears the override, back to the pivot's own name. */
export async function saveReportTitle(sessionId: string, pivotId: string, title: string | null): Promise<ReportTitlesResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/report-titles`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pivot_id: pivotId, title }),
  });
  await assertOk(response);
  return response.json();
}
