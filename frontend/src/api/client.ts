// Shared fetch base + error handling for every api/* module.

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class AuditApiError extends Error {}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body.detail ?? response.statusText;
  } catch {
    return response.statusText;
  }
}

/** Throws AuditApiError with the backend's `detail` message if the response isn't ok. */
export async function assertOk(response: Response): Promise<void> {
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
}
