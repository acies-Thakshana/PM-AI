// Ties the chat's messages to the turn record on the server (backend services/chat/chat_store.py).
//
// A turn is one PM message and everything that follows it. Its id is made here, because not every message goes
// to the chat model (a brief typed on the Configure page and "suggest an analysis" are answered by the browser),
// so the server cannot be the one to number them. Ids sort by the time they were made, so the turns of a chat
// come back in order without a counter.
import type { ActionOutcome, AppAction, HandledBy, SuggestionRef, TurnNote } from "../api/chat";

const RANDOM_CHARS = 8;
const TIME_DIGITS = 9;

function randomChars(count: number): string {
  const bytes = new Uint8Array(count);
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(bytes);
  else bytes.forEach((_, i) => (bytes[i] = Math.floor(Math.random() * 256)));
  return Array.from(bytes, (b) => (b % 36).toString(36)).join("");
}

/** `<prefix>_<clock in base 36><random>`: letters and digits only (the server accepts ids of that shape). */
function sortableId(prefix: string): string {
  return `${prefix}_${Date.now().toString(36).padStart(TIME_DIGITS, "0")}${randomChars(RANDOM_CHARS)}`;
}

export const newChatId = (): string => sortableId("c");
export const newTurnId = (): string => sortableId("t");

/** What the browser collects about one turn while it runs, and sends to the server when the turn is over. */
export class TurnTrace {
  readonly chatId: string;
  readonly turnId: string;
  readonly handledBy: HandledBy;
  readonly notes: TurnNote[] = [];
  readonly outcomes: ActionOutcome[] = [];
  readonly appActions: AppAction[] = [];
  readonly suggestions: SuggestionRef[] = [];
  /** An error code when the turn broke (the browser's own turns; the server settles the others). */
  failed: string | null = null;
  /** Resolves once the server has the turn: what comes after must not overtake it. */
  started: Promise<void> = Promise.resolve();

  constructor(chatId: string, handledBy: HandledBy) {
    this.chatId = chatId;
    this.turnId = newTurnId();
    this.handledBy = handledBy;
  }
}

// The PM cannot send a second message while one is being answered, so at most one turn is open at a time.
let open: TurnTrace | null = null;

export const activeTurn = (): TurnTrace | null => open;

export function beginTurn(chatId: string, handledBy: HandledBy): TurnTrace {
  open = new TurnTrace(chatId, handledBy);
  return open;
}

export function endTurn(turn: TurnTrace): void {
  if (open === turn) open = null;
}
