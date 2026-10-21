import { API_BASE_URL, apiFetch } from "./apiFetch";

export type AssistantStage = "audit" | "features" | "analysis" | "report";

export interface AssistantTurn {
  role: "user" | "assistant";
  text: string;
}

/** Asks the stage assistant a question about the program. It answers from the brief, the audit and the plan, and
 * changes nothing. */
export async function askAssistant(
  sessionId: string,
  stage: AssistantStage,
  message: string,
  history: AssistantTurn[]
): Promise<string> {
  const res = await apiFetch(`${API_BASE_URL}/api/assistant/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, stage, message, history }),
  });
  if (!res.ok) {
    let detail = `The assistant could not answer (${res.status}).`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* keep the default */
    }
    throw new Error(detail);
  }
  const data = (await res.json()) as { reply: string };
  return data.reply;
}
