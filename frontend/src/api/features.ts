import { API_BASE_URL, assertOk } from "./client";
import type { FeatureDefinitionsSummary, FeatureReport, FeatureSuggestion, FeatureSuggestionsResponse } from "./types";

export async function applyFeatures(sessionId: string, extraFeatures: FeatureSuggestion[] = []): Promise<FeatureReport> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/features`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ extra_features: extraFeatures }),
  });
  await assertOk(response);
  return response.json();
}

export async function fetchFeatureReport(sessionId: string): Promise<FeatureReport> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/features`);
  await assertOk(response);
  return response.json();
}

export async function suggestFeatures(sessionId: string): Promise<FeatureSuggestionsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/features/suggest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  await assertOk(response);
  return response.json();
}

export async function uploadFeatureDefinitions(file: File): Promise<FeatureDefinitionsSummary> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/features/definitions`, {
    method: "POST",
    body: formData,
  });

  await assertOk(response);
  return response.json();
}
