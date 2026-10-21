import { API_BASE_URL, apiFetch } from "./apiFetch";

export type ChatPhase = "interview" | "readback" | "ready" | "build" | "refine";

export interface ChatTurnMessage {
  role: "user" | "assistant";
  content: string;
}

/** "What I understand so far": short plain phrases, "" while still unknown. */
export interface Understanding {
  goal: string;
  scope: string;
  period: string;
  limits: string;
  output: string;
  kpis: string;
}

export const EMPTY_UNDERSTANDING: Understanding = { goal: "", scope: "", period: "", limits: "", output: "", kpis: "" };

export interface Assumption {
  id: string;
  text: string;
}

export type ChatAction =
  | { type: "set_brief"; text: string }
  /** `open` is the id of an analysis (on "analysis") or a calculation (on "features") to open on that page. */
  | { type: "navigate"; page: "upload" | "planner" | "audit" | "features" | "analysis" | "report"; open?: string }
  | { type: "add_analysis"; name: string; description: string }
  | { type: "add_feature"; name: string; description: string }
  | { type: "check_ready" }
  | { type: "continue_build" };

export interface ChatTurnRequest {
  session_id: string | null;
  brief: string;
  messages: ChatTurnMessage[];
  state: Record<string, unknown>;
}

export type ChatIntent = "interview" | "ask" | "change" | "generate" | "other";

export interface ChatTurnResponse {
  reply: string;
  intent: ChatIntent;
  phase: ChatPhase;
  understanding: Understanding;
  assumptions: Assumption[];
  quick_replies: string[];
  /** Follow-up questions the PM could ask next (never during the interview). */
  next_questions: string[];
  actions: ChatAction[];
}

async function failure(res: Response, what: string): Promise<Error> {
  const text = await res.text().catch(() => "");
  let detail = text;
  try {
    detail = JSON.parse(text).detail ?? text;
  } catch {
    // not JSON: keep the raw text
  }
  return new Error(`${what}: ${detail || res.status}`);
}

export async function chatTurn(body: ChatTurnRequest): Promise<ChatTurnResponse> {
  const res = await apiFetch(`${API_BASE_URL}/api/chat/turn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await failure(res, "The assistant could not answer");
  return res.json();
}

export interface InterviewRecord {
  brief: string;
  /** Where the brief came from: the chat (the Planner uses it) or the Configure page. */
  brief_source?: "chat" | "upload";
  understanding: Understanding;
  assumptions: Assumption[];
  transcript: ChatTurnMessage[];
}

/** Keeps the interview with the session, next to the brief: the Planner reads it when it suggests features and analyses. */
export async function saveInterview(sessionId: string, record: InterviewRecord): Promise<void> {
  const res = await apiFetch(`${API_BASE_URL}/api/chat/interview/${sessionId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(record),
  });
  if (!res.ok) throw await failure(res, "Could not save the interview");
}

/** Undo for something the chat added: the entry is rejected (it leaves the report), never deleted. */
export async function rejectEntry(kind: "analysis" | "feature", sessionId: string, entryId: string): Promise<void> {
  const base = kind === "analysis" ? "analysis" : "features";
  const res = await apiFetch(`${API_BASE_URL}/api/${base}/repository/${sessionId}/entries/${entryId}/reject`, { method: "POST" });
  if (!res.ok) throw await failure(res, "Could not undo that");
}
