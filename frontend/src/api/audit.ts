import { API_BASE_URL, assertOk } from "./client";
import type { AuditReport, DataPreview, IssueRowsResponse } from "./types";

export async function uploadForAudit(source: string, file: File): Promise<AuditReport> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("source", source);

  const response = await fetch(`${API_BASE_URL}/api/audit/upload`, {
    method: "POST",
    body: formData,
  });

  await assertOk(response);
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

  await assertOk(response);
  return response.json();
}

export async function revertIssue(sessionId: string, issueId: string): Promise<AuditReport> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/issues/${issueId}/revert`, {
    method: "POST",
  });

  await assertOk(response);
  return response.json();
}

export function downloadCleansedFileUrl(sessionId: string): string {
  return `${API_BASE_URL}/api/audit/${sessionId}/download`;
}

export async function fetchIssueRows(sessionId: string, issueId: string): Promise<IssueRowsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/issues/${issueId}/rows`);
  await assertOk(response);
  return response.json();
}

export async function fetchPreview(sessionId: string, rows = 20): Promise<DataPreview> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/preview?rows=${rows}`);
  await assertOk(response);
  return response.json();
}
