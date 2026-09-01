import { API_BASE_URL, assertOk } from "./client";
import type { OverallAnalysisReport } from "./types";

export async function fetchOverallAnalysis(sessionId: string): Promise<OverallAnalysisReport> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/overall`);
  await assertOk(response);
  return response.json();
}
