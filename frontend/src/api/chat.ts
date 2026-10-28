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
  /** The conversation and this turn in it (made in the browser): the server records the turn under them. */
  chat_id?: string;
  turn_id?: string;
  /** The last message is the app's own prompt, not something the PM typed. */
  hidden?: boolean;
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

// ---------------------------------------------------------------------------------------- turn record
// A "turn" is one PM message and everything that followed it. The server stores the turns the model answers itself;
// the browser reports the rest (see backend routers/chat_turns.py). Recording never changes what the chat does:
// these calls are best effort and a failure is only logged.

/** Who answered a turn: the chat model, or the browser itself (a message the model never saw). */
export type HandledBy = "chat_model" | "shortcut_suggest" | "shortcut_own" | "brief_local";

export type ActionStatus = "applied" | "failed" | "blocked" | "skipped";

/** A short note the app said in the chat (not the model's reply). */
export interface TurnNote {
  content: string;
  kind: "notice" | "error";
}

/** What became of the model's action number `index` (its position in the reply's actions). */
export interface ActionOutcome {
  index: number;
  type: string;
  status: ActionStatus;
  entry_id?: string;
}

/** Something the browser did on its own, with no model action behind it. */
export interface AppAction {
  type: string;
  status: ActionStatus;
  page?: string;
  name?: string;
  entry_id?: string;
}

/** An analysis or calculation the AI offered in this turn, waiting for the PM's accept or reject. */
export interface SuggestionRef {
  kind: "analysis" | "feature";
  entry_id: string;
  name: string;
}

export interface TurnStart {
  chat_id: string;
  turn_id: string;
  user_text: string;
  handled_by: Exclude<HandledBy, "chat_model">;
  session_id: string | null;
  page: string;
  phase: string;
  hidden: boolean;
}

export interface TurnFinish {
  status: "completed" | "failed";
  error_code?: string;
  notes: TurnNote[];
  outcomes: ActionOutcome[];
  app_actions: AppAction[];
  suggestions: SuggestionRef[];
}

async function recordQuietly(path: string, body: unknown): Promise<void> {
  try {
    const res = await apiFetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) console.warn(`Could not record the chat turn (${res.status}).`);
  } catch (err) {
    console.warn("Could not record the chat turn:", err);
  }
}

/** Stores a turn the browser answers itself (the server stores the ones the model answers). */
export const recordTurn = (body: TurnStart): Promise<void> => recordQuietly("/api/chat/turns", body);

/** What happened after the PM's message: the app's notes, what became of each action, the suggestions made. */
export const finishTurn = (chatId: string, turnId: string, body: TurnFinish): Promise<void> =>
  recordQuietly(`/api/chat/turns/${chatId}/${turnId}/finish`, body);

/** The PM accepted or rejected a suggestion the turn made. */
export const markSuggestion = (chatId: string, turnId: string, entryId: string, status: "accepted" | "rejected"): Promise<void> =>
  recordQuietly(`/api/chat/turns/${chatId}/${turnId}/suggestions/${encodeURIComponent(entryId)}`, { status });

/** Undo for something the chat added: the entry is rejected (it leaves the report), never deleted. */
export async function rejectEntry(kind: "analysis" | "feature", sessionId: string, entryId: string): Promise<void> {
  const base = kind === "analysis" ? "analysis" : "features";
  const res = await apiFetch(`${API_BASE_URL}/api/${base}/repository/${sessionId}/entries/${entryId}/reject`, { method: "POST" });
  if (!res.ok) throw await failure(res, "Could not undo that");
}
