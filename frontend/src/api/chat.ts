import { API_BASE_URL, apiFetch } from "./apiFetch";

export type ChatPhase = "interview" | "readback" | "plan" | "build" | "refine";

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

export interface PlanItem {
  name: string;
  description: string;
}

export interface ChatPlan {
  analyses: PlanItem[];
  features: PlanItem[];
}

export type ChatAction =
  | { type: "set_brief"; text: string }
  | { type: "approve_plan" }
  | { type: "navigate"; page: "upload" | "planner" | "audit" | "features" | "analysis" | "report" }
  | { type: "add_analysis"; name: string; description: string }
  | { type: "add_feature"; name: string; description: string }
  | { type: "explain"; target: string }
  | { type: "check_ready" }
  | { type: "continue_build" };

export interface ChatTurnRequest {
  session_id: string | null;
  brief: string;
  messages: ChatTurnMessage[];
  state: Record<string, unknown>;
}

export interface ChatTurnResponse {
  reply: string;
  phase: ChatPhase;
  understanding: Understanding;
  assumptions: Assumption[];
  quick_replies: string[];
  plan: ChatPlan | null;
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
  understanding: Understanding;
  assumptions: Assumption[];
  plan: ChatPlan | null;
  transcript: ChatTurnMessage[];
}

/** Keeps the interview with the session, next to the brief (and tells the Planner what was approved). */
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
