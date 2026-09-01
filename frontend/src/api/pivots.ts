import { API_BASE_URL, assertOk } from "./client";
import type { PivotDefinitionsSummary, PivotFilter, PivotReport, PivotSuggestion, PivotSuggestionsResponse } from "./types";

export async function uploadPivotDefinitions(file: File): Promise<PivotDefinitionsSummary> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/analysis/definitions`, {
    method: "POST",
    body: formData,
  });

  await assertOk(response);
  return response.json();
}

export async function suggestPivots(sessionId: string): Promise<PivotSuggestionsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/suggest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  await assertOk(response);
  return response.json();
}

export async function applyPivots(
  sessionId: string,
  /** Omit (undefined) to leave whatever AI/custom pivots were last applied
   * for this session alone -- e.g. the Report page changing only filters
   * shouldn't have to resend the Analysis page's full accepted list. */
  extraPivots?: PivotSuggestion[],
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
  await assertOk(response);
  return response.json();
}

export async function fetchPivotReport(sessionId: string): Promise<PivotReport> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/pivots`);
  await assertOk(response);
  return response.json();
}
