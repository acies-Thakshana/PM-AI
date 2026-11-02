// The assistant's rules, kept free of React so they are easy to read and test.
//
//  * Stage: which wizard page the PM is on decides what the assistant shows and may do.
//  * Gate: features and analyses are built on the audited data, so the assistant refuses to add or compute them
//    until the data is loaded and every audit decision is made (the model cannot talk its way past this).
//  * Brief: only what the PM typed as the brief may become the brief; the assistant never invents one.

export type Stage = "configure" | "planner" | "audit" | "features" | "analysis" | "report" | "other";

export interface ChatLink {
  label: string;
  path: string;
}

/** Page name used by the model's navigate action -> route. */
export const PAGE_PATH: Record<string, string> = {
  upload: "/upload",
  planner: "/planner",
  audit: "/audit",
  features: "/features",
  analysis: "/analysis",
  report: "/report",
};

const STAGE_BY_PATH: Record<string, Stage> = {
  "/upload": "configure",
  "/planner": "planner",
  "/audit": "audit",
  "/features": "features",
  "/analysis": "analysis",
  "/report": "report",
};

export function stageOf(pathname: string): Stage {
  return STAGE_BY_PATH[pathname] ?? "other";
}

const PAGE_LABEL: Record<string, string> = {
  "/upload": "Configure",
  "/planner": "Planner",
  "/audit": "Audit",
  "/features": "Features",
  "/analysis": "Analysis",
  "/report": "Report",
};

export const pageLabel = (path: string): string => PAGE_LABEL[path.split("?")[0]] ?? "page";

// ------------------------------------------------------------------------------------------------ gate
export interface GateInput {
  hasSession: boolean;
  /** The audit report says every decision is made. */
  auditReviewed: boolean;
  /** Audit decisions still waiting for the PM. */
  pendingDecisions: number;
}

export type Gate = { ok: true } | { ok: false; reason: string; link: ChatLink };

/** Can features and analyses be added, suggested, accepted or computed right now? */
export function dataGate(input: GateInput): Gate {
  if (!input.hasSession) {
    return {
      ok: false,
      reason: "I need the data first. Load it on the Configure page, then finish the data audit.",
      link: { label: "Open Configure", path: "/upload" },
    };
  }
  if (!input.auditReviewed) {
    const left = input.pendingDecisions;
    return {
      ok: false,
      reason:
        left > 0
          ? `Finish the data audit first (${left} decision${left > 1 ? "s" : ""} left). Features and analyses are built on the audited data.`
          : "Finish the data audit first. Features and analyses are built on the audited data.",
      link: { label: "Open the audit", path: "/audit" },
    };
  }
  return { ok: true };
}

// ------------------------------------------------------------------------------------------------ brief
const squash = (text: string) => text.replace(/\s+/g, " ").trim().toLowerCase();

/** Fewer words than this is too short to be sure it is a brief: the assistant asks the PM. */
export const MIN_BRIEF_WORDS = 5;

export type BriefQuality = "junk" | "short" | "ok";

/** A run of letters that could be a word: two or more, not one letter repeated, and (Latin letters) with a vowel. */
const isRealWord = (run: string): boolean => {
  const letters = [...run.toLowerCase()];
  if (letters.length < 2 || new Set(letters).size < 2) return false;
  return !/^[\x00-\x7f]+$/.test(run) || /[aeiouy]/.test(run.toLowerCase());
};

/**
 * What can be told about a brief without asking a model: "junk" (no real word in it, e.g. "xxx": never a brief),
 * "short" (under MIN_BRIEF_WORDS words: the assistant asks the PM) or "ok". The server applies the same rule
 * (backend/app/services/common/brief_rules.py), so keep the two in step.
 */
export function briefQuality(text: string): BriefQuality {
  if (!(text.match(/\p{L}+/gu) ?? []).some(isRealWord)) return "junk";
  return text.trim().split(/\s+/).length < MIN_BRIEF_WORDS ? "short" : "ok";
}

/** Said when a message offered as the brief is not one (the server's BRIEF_NOT_A_BRIEF says the same). */
export const NOT_A_BRIEF =
  "That doesn't look like a client brief. Please write what the client needs: which shipments to look at and what to find out (a sentence or two is enough).";

/** The answers to "Is this your client brief?": the server offers "Yes, that's my brief" and "No, I'll rewrite it" as buttons; typing yes or no works too. */
const YES = /^\s*(yes|yep|yeah|correct|right|it is|it's|that is|that's)\b/i;
const NO = /^\s*(no|nope|not)\b/i;
export const isBriefYes = (text: string): boolean => YES.test(text);
export const isBriefNo = (text: string): boolean => NO.test(text);

/**
 * May the model's `set_brief` action store `text` as the client brief?
 * Only when the text is the PM's own words from the message just sent (never a rewrite) and is not junk. Once a
 * brief exists it stays the brief: it is changed in the Client Brief box on the Configure page, never from the chat,
 * so an interview answer (or a second pasted brief) cannot replace it.
 */
export function canSetBrief(text: string, lastUserMessage: string, currentBrief: string): boolean {
  const brief = squash(text);
  if (!brief || !squash(lastUserMessage).includes(brief)) return false;
  return !currentBrief.trim() && briefQuality(text) !== "junk";
}

/** Is this message the client brief (a few sentences), rather than a short answer or a question? */
export function looksLikeBrief(text: string): boolean {
  const clean = text.trim();
  return clean.split(/\s+/).length >= 12 && !clean.endsWith("?");
}

// ------------------------------------------------------------------------------------------ page links
const PAGE_WORDS: [RegExp, string][] = [
  [/\b(upload|configure)\b/i, "/upload"],
  [/\bplanner\b/i, "/planner"],
  [/\baudit\b/i, "/audit"],
  [/\bfeatures?\b/i, "/features"],
  [/\banalys[ei]s\b/i, "/analysis"],
  [/\breport\b/i, "/report"],
];
const OPEN_VERBS = /\b(open|opening|take you to|go to|head to|switch to|move to|navigate to)\b/i;

/**
 * Links for the pages a reply says it will open. A sentence is only a promise; the model has to return a
 * navigate action to actually move the PM. When it did not, the reply gets a button so the promise is not empty.
 */
export function pageLinksIn(reply: string): ChatLink[] {
  const links: ChatLink[] = [];
  for (const sentence of reply.split(/(?<=[.!?])\s+/)) {
    if (!OPEN_VERBS.test(sentence)) continue;
    for (const [word, path] of PAGE_WORDS) {
      if (word.test(sentence) && !links.some((l) => l.path === path)) {
        links.push({ label: `Open ${PAGE_LABEL[path]}`, path });
      }
    }
  }
  return links;
}

// ------------------------------------------------------------------------------------------------ messages
/** `text` cut to about `max` characters at a word end, with an ellipsis when something was left out. */
export function shorten(text: string, max: number): string {
  const clean = text.replace(/\s+/g, " ").trim();
  if (clean.length <= max) return clean;
  const cut = clean.slice(0, max);
  return `${cut.slice(0, Math.max(cut.lastIndexOf(" "), max / 2))}…`;
}

/**
 * A failure from the backend, said so the PM can act on it. An AI provider that refuses because its key or quota
 * is used up is not something the PM did wrong, and is not fixed by trying again.
 */
export function explainFailure(raw: string | null | undefined): string {
  const message = (raw ?? "").trim();
  if (!message) return "it did not finish and gave no reason";
  if (/key limit exceeded|insufficient (credits|quota)|quota exceeded|payment required|returned 402/i.test(message)) {
    return "the AI service refused the request because its key or quota is used up. Raise the limit with the provider (OpenRouter), or switch the backend to another model, then try again";
  }
  if (/returned 429|rate limit/i.test(message)) return "the AI service is rate limiting requests. Wait a minute and try again";
  return shorten(message, 220);
}

// ------------------------------------------------------------------------------------------------ shortcuts
/** What the PM asked for in words the app can read without asking the model (one AI call saved each time). */
export type Shortcut =
  | { type: "suggest"; kind: "feature" | "analysis" | "both" }
  | { type: "own"; kind: "feature" | "analysis"; text: string };

/**
 * "Add an analysis: <what I want>" (the My-own chips) goes straight to the drafting agent with the PM's own words;
 * "suggest / add another analysis" with nothing specific goes to the suggestion agent. Anything else is left to the
 * model (null), which also decides what to do with a question.
 */
export function shortcutFor(text: string): Shortcut | null {
  const own = text.match(/^add (?:an? )?(analysis|calculation|feature)\s*:\s*(\S[\s\S]*)$/i);
  if (own) return { type: "own", kind: /analysis/i.test(own[1]) ? "analysis" : "feature", text: own[2].trim() };
  if (text.includes(":") || text.trim().split(/\s+/).length > 14 || /\b(?:explain|why|how|what does|what is)\b/i.test(text)) return null;
  const analysis = /analys/i.test(text);
  const feature = /feature|calculation|kpi|metric/i.test(text);
  const kind = analysis && feature ? "both" : analysis ? "analysis" : feature ? "feature" : null;
  const generic = /\b(?:suggest|recommend|propose|another|more|other|suitable|something|anything|on (?:your|ur) own)\b/i.test(text);
  const adding = /\b(?:add|suggest|recommend|propose|give|create|need|want)\b/i.test(text);
  return kind && generic && adding ? { type: "suggest", kind } : null;
}
