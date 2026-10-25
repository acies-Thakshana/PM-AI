import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  EMPTY_UNDERSTANDING,
  chatTurn,
  rejectEntry,
  saveInterview,
} from "../api/chat";
import type { Assumption, ChatAction, ChatPhase, ChatTurnMessage, InterviewRecord, Understanding } from "../api/chat";
import {
  acceptAnalysisEntry,
  acceptFeatureEntry,
  addCustomAnalysis,
  addCustomFeature,
  applyFeatures,
  draftAnalysis,
  draftCustomFeature,
  fetchAnalysisRepository,
  fetchFeatureRepository,
  runAnalysisEntry,
  selectRequiredFeature,
  suggestAnalysisEntries,
  suggestFeatureEntries,
} from "../api/audit";
import type { AnalysisRepositoryEntry, AuditReport } from "../api/audit";
import type { FilesState } from "../App";
import type { BriefState } from "../components/ClientBriefInput";
import { announceChatChange, usePageChangeCount, useStoredRef, useStoredState } from "../state/sessionStore";
import { persistDecisions } from "../api/planner";
import type { PlannerSuggestResponse, PmDecisionValue } from "../api/planner";
import { hasFormula, plannerDecisionsKey, plannerResultKey } from "../utils/plannerRecs";
import { PAGE_PATH, canSetBrief, dataGate, explainFailure, looksLikeBrief, pageLabel, pageLinksIn, shortcutFor, shorten, stageOf } from "./rules";
import { INTERVIEW_DONE_KEY } from "./signals";
import type { ChatLink, Gate } from "./rules";

// The chat assistant: one conversation that interviews the PM about the client brief and, once the PM presses
// "Build the report", computes and runs what was accepted, then refines the report on request. The chat does
// not plan: the Planner page does, from the brief and the saved interview. The model only talks and proposes
// actions (see routers/chat.py); everything that changes data happens here, through the same endpoints the
// pages use, so the pages show the result when opened.
//
// The assistant never acts on its own: it changes data, stores a brief or moves the PM only when the PM
// asked for it (see rules.ts for the stage, gate and brief rules).

export type { ChatLink };

export interface ChatMsg {
  id: string;
  role: "user" | "assistant";
  text: string;
  error?: boolean;
  links?: ChatLink[];
  /** Label and value rows shown as a neat list inside the bubble (what the assistant understood from the brief). */
  facts?: { label: string; value: string }[];
}

export type BuildStatus = "idle" | "waiting_data" | "running" | "paused_audit" | "done" | "error";

export interface BuildState {
  status: BuildStatus;
  /** One live line: "Building analyses: 2 of 4 finished." */
  line: string;
}

export interface ChatChange {
  id: string;
  kind: "analysis" | "feature";
  label: string;
  entryId: string;
  sessionId: string;
  state: "added" | "undone";
}

/** One analysis the assistant is building (or just added), shown live in the panel while it works. */
export interface BuildItem {
  id: string;
  /** Which page it opens on; an item without one is an analysis. */
  kind?: "feature" | "analysis";
  name: string;
  state: "queued" | "running" | "done" | "failed";
  error?: string;
}

export type ReviewStage = "planner" | "features" | "analysis";

/** A suggestion waiting for the PM's accept or reject: decided here or on its page (both see the same record). */
export interface ReviewItem {
  id: string;
  /** The wizard page this suggestion belongs to: the chat shows it only while the PM is on that page. */
  stage: ReviewStage;
  kind: "feature" | "analysis";
  name: string;
  description: string;
  state: "pending" | "working" | "accepted" | "rejected" | "error";
  error?: string;
}

export interface AuditStatus {
  reviewed: boolean;
  /** Audit decisions still waiting for the PM, who decides them on the Audit page only. */
  pending: number;
}

/** Per page: does the PM decide each suggestion ("user", the default) or are they accepted as they arrive? */
export type AutoAccept = Record<ReviewStage, boolean>;

interface ChatValue {
  review: ReviewItem[];
  /** The page whose suggestions the PM just asked for (their card is open there), or null. */
  suggestedFor: ReviewStage | null;
  audit: AuditStatus;
  autoAccept: AutoAccept;
  setAutoAccept: (stage: ReviewStage, on: boolean) => void;
  decide: (id: string, accept: boolean) => void;
  acceptAll: (stage: ReviewStage) => void;
  inspect: (item: ReviewItem) => void;
  buildItems: BuildItem[];
  open: boolean;
  setOpen: (open: boolean) => void;
  messages: ChatMsg[];
  busy: boolean;
  phase: ChatPhase;
  /** The Planner has produced its suggestions (the way on to the audit is open). */
  plannerReady: boolean;
  understanding: Understanding;
  assumptions: Assumption[];
  quickReplies: string[];
  /** Follow-up questions the PM could ask next, after an answer about the report. */
  nextQuestions: string[];
  build: BuildState;
  changes: ChatChange[];
  hasSession: boolean;
  /** Opens the panel and begins the interview. */
  startInterview: () => void;
  /** The PM pressed "Build the report": computes the accepted features and runs the accepted analyses. */
  startBuild: () => void;
  /** Saves the interview with the session so the Planner can read it. Never throws; does nothing without answers. */
  persistInterview: (sessionId: string) => Promise<void>;
  suggestWithAi: (kind: "feature" | "analysis") => void;
  /** Opens a page (or an item on it: "/analysis?open=<id>"); on the current page it refreshes it. */
  openPage: (path: string) => void;
  send: (text: string, opts?: { hidden?: boolean }) => void;
  editAssumption: (id: string, text: string) => void;
  removeAssumption: (id: string) => void;
  undoChange: (id: string) => void;
  reset: () => void;
}

const ChatContext = createContext<ChatValue | null>(null);

export function useChat(): ChatValue {
  const value = useContext(ChatContext);
  if (!value) throw new Error("useChat must be used inside ChatProvider");
  return value;
}

/** How much of a calculation's step-by-step text the chat repeats; the opened calculation shows all of it. */
const FEATURE_SUMMARY_CHARS = 260;

/** Sent to the model, never shown, when the PM presses "Build the report": it asks for the first question. */
const START_INTERVIEW_TURN = "Begin the interview: ask your first question about the client brief.";

const GREETING: ChatMsg = {
  id: "greeting",
  role: "assistant",
  text:
    "Hi, I'm Polar, your Program Manager assistant. Paste the client brief here (or in the box on the page), then load your data. " +
    "Once the data is in, I'll ask a few quick questions about the brief on the Planner page, with examples taken from your data.",
};

const SKIP_REPLY = "Skip the questions, use your best guess";

const UNDERSTANDING_ROWS: [keyof Understanding, string][] = [
  ["goal", "Goal"],
  ["scope", "Scope"],
  ["period", "Period"],
  ["limits", "Limits"],
  ["output", "Output"],
  ["kpis", "Client KPIs"],
];

/** What the assistant took from the brief: the rows, and the same as text for the conversation record. */
function understandingReply(u: Understanding): { text: string; facts: { label: string; value: string }[] } | null {
  const facts = UNDERSTANDING_ROWS.filter(([key]) => u[key]).map(([key, label]) => ({ label, value: u[key] }));
  if (!facts.length) return null;
  const heading = "Here is what I picked up from the brief:";
  return { text: [heading, ...facts.map((f) => `• ${f.label}: ${f.value}`)].join("\n"), facts };
}

/** A brief written from the PM's answers, for when the interview happened with no brief on the Configure page. */
function briefFromAnswers(u: Understanding): string {
  return UNDERSTANDING_ROWS.filter(([key]) => u[key])
    .map(([key, label]) => `${label}: ${u[key]}`)
    .join("\n");
}

let idCounter = 0;
const nextId = () => `m${Date.now().toString(36)}${(idCounter++).toString(36)}`;

function errorText(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

interface ProviderProps {
  brief: BriefState;
  onBriefChange: (brief: BriefState) => void;
  files: FilesState;
  sessionId: string | null;
  auditReport: AuditReport | undefined;
  children: ReactNode;
}

export function ChatProvider({ brief, onBriefChange, files, sessionId, auditReport, children }: ProviderProps) {
  const navigate = useNavigate();
  const location = useLocation();

  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMsg[]>([GREETING]);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<ChatPhase>("interview");
  const [understanding, setUnderstanding] = useState<Understanding>(EMPTY_UNDERSTANDING);
  const [assumptions, setAssumptions] = useState<Assumption[]>([]);
  const [quickReplies, setQuickReplies] = useState<string[]>([]);
  const [nextQuestions, setNextQuestions] = useState<string[]>([]);
  const [build, setBuild] = useState<BuildState>({ status: "idle", line: "" });
  const [changes, setChanges] = useState<ChatChange[]>([]);
  const [autoAccept, setAutoAcceptState] = useState<AutoAccept>({ planner: false, features: false, analysis: false });
  const [buildItems, setBuildItems] = useState<BuildItem[]>([]);
  // The page whose suggestions the PM just asked for: their card is open there, and folded away everywhere else.
  const [suggestedFor, setSuggestedFor] = useState<ReviewStage | null>(null);
  const [repoReview, setReview] = useState<ReviewItem[]>([]);
  // The analysis or calculation open on its page (set by the page): "this graph" in a question means this one.
  const [chatFocus] = useStoredState<string | null>("chat.focus", null);
  // The interview is over (confirmed or skipped): the Planner page waits for this before it plans.
  const [interviewDone, setInterviewDone] = useStoredState<boolean>(INTERVIEW_DONE_KEY, false);

  // The Planner's suggestions and the PM's decisions on them live in the shared store: the PM decides here in
  // the chat, the Planner page shows the details.
  const [plannerResult] = useStoredState<PlannerSuggestResponse | null>(plannerResultKey(sessionId), null);
  const [plannerDecisions, setPlannerDecisions] = useStoredState<Record<number, PmDecisionValue>>(plannerDecisionsKey(sessionId), {});
  const plannerItems = useMemo<ReviewItem[]>(
    () =>
      (plannerResult?.recommendations ?? []).flatMap((r, i) =>
        hasFormula(r)
          ? [
              {
                id: `planner:${i}`,
                stage: "planner" as const,
                kind: (r.type === "analysis" || r.type === "feature_and_analysis" ? "analysis" : "feature") as ReviewItem["kind"],
                name: r.name,
                description: r.reason || r.description || "",
                state: (plannerDecisions[i] === "accepted" ? "accepted" : plannerDecisions[i] === "rejected" ? "rejected" : "pending") as ReviewItem["state"],
              },
            ]
          : []
      ),
    [plannerResult, plannerDecisions]
  );
  const review = useMemo(() => [...plannerItems, ...repoReview], [plannerItems, repoReview]);
  const audit = useMemo<AuditStatus>(
    () => ({
      reviewed: auditReport?.status === "reviewed",
      pending: (auditReport?.issues ?? []).filter((i) => i.requires_decision && i.status === "pending").length,
    }),
    [auditReport]
  );

  // The decisions are saved on the server each time, so they hold even after the Planner page was left.
  const savePlannerDecisions = (next: Record<number, PmDecisionValue>) => {
    const sid = live.current.sessionId;
    if (!sid || !plannerResult) return;
    persistDecisions(sid, plannerResult.recommendations, next).catch((err) =>
      say(`I could not save that decision: ${errorText(err, "unknown error")}`, { error: true })
    );
  };

  const patchItem = (id: string, patch: Partial<BuildItem>) =>
    setBuildItems((prev) => (prev.some((i) => i.id === id) ? prev.map((i) => (i.id === id ? { ...i, ...patch } : i)) : [...prev, { id, name: "", state: "queued", ...patch }]));

  /**
   * The assistant starts working on one item. Calculations and analyses share this, so both show the same progress.
   * A single item (accepted or added on its own) starts a fresh list instead of joining the last build's.
   */
  const beginItem = (id: string, name: string, kind: NonNullable<BuildItem["kind"]>) => {
    setBuildItems((prev) => (prev.some((i) => i.state === "queued" || i.state === "running") ? prev : []));
    patchItem(id, { name, kind, state: "running" });
  };

  // Analyses started here must not be started a second time by the Analysis page's own auto-run.
  const analysisStarted = useStoredRef<{ current: Set<string> }>("analysis.autoStarted", () => ({ current: new Set<string>() }));

  // Latest values for the async code (a build outlives the render that started it).
  const pendingSuggestions = review.filter((r) => r.state === "pending").length;
  const live = useRef({ brief, files, sessionId, auditReport, understanding, assumptions, phase, build, messages, pendingSuggestions, chatFocus, pathname: location.pathname });
  live.current = { brief, files, sessionId, auditReport, understanding, assumptions, phase, build, messages, pendingSuggestions, chatFocus, pathname: location.pathname };

  const building = useRef(false);
  // The PM gave the brief in the chat: then it, not the one on the Configure page, is what the Planner plans from.
  const chatBrief = useRef(false);
  const interviewBegan = useRef(false);

  const briefText = () => (live.current.brief.rawText || live.current.brief.finalText || "").trim();

  /** What the interview settled so far, as saved with the session (the Planner reads it). */
  const interviewRecord = (): InterviewRecord => ({
    brief: briefText(),
    brief_source: chatBrief.current ? "chat" : "upload",
    understanding: live.current.understanding,
    assumptions: live.current.assumptions,
    transcript: transcriptOf(live.current.messages),
  });

  const persistInterview = useCallback(async (sid: string): Promise<void> => {
    const { understanding: u, assumptions: a } = live.current;
    if (!Object.values(u).some(Boolean) && a.length === 0) return; // no interview happened: nothing to save
    try {
      await saveInterview(sid, interviewRecord());
    } catch (err) {
      // Saving is best effort: the Planner then plans from the brief alone.
      console.warn("Could not save the interview:", errorText(err, "unknown error"));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const say = useCallback((text: string, extra?: Partial<ChatMsg>) => {
    setMessages((prev) => [...prev, { id: nextId(), role: "assistant", text, ...extra }]);
  }, []);

  const setLine = (status: BuildStatus, line: string) => setBuild({ status, line });

  const gateNow = (): Gate => {
    const report = live.current.auditReport;
    return dataGate({
      hasSession: Boolean(live.current.sessionId),
      auditReviewed: report?.status === "reviewed",
      pendingDecisions: (report?.issues ?? []).filter((i) => i.requires_decision && i.status === "pending").length,
    });
  };

  /** The session features and analyses may be changed on, or null after telling the PM why not and where to go. */
  const readySession = (): string | null => {
    const gate = gateNow();
    if (!gate.ok) {
      say(gate.reason, { links: [gate.link] });
      return null;
    }
    return live.current.sessionId;
  };

  // While the assistant builds, the page follows it: the item that just finished opens (graph and all) and the
  // next one runs behind it. Only on the wizard pages, so a PM who went to look at something else is not pulled back.
  const follow = (path: string) => {
    if (["/planner", "/audit", "/features", "/analysis"].includes(live.current.pathname)) navigate(path);
  };

  // ------------------------------------------------------------------------------------------ build
  const analysesOf = (entries: AnalysisRepositoryEntry[]) =>
    entries.filter((e) => e.status === "approved" && e.source !== "drilldown");

  const runAnalyses = async (sid: string): Promise<{ done: number; failed: { name: string; error: string }[]; total: number }> => {
    let entries = analysesOf((await fetchAnalysisRepository(sid)).entries);

    // Required calculations of an analysis must be approved and computed first (the Analysis page does the same).
    let needCompute = false;
    for (const entry of entries) {
      for (const req of entry.required_features ?? []) {
        if (req.feature_id && req.state === "not_approved") {
          await selectRequiredFeature(sid, entry.id, req.feature_id).catch(() => undefined);
          needCompute = true;
        } else if (req.state === "not_computed") {
          needCompute = true;
        }
      }
    }
    if (needCompute) {
      setLine("running", "Calculating the features the analyses need…");
      await applyFeatures(sid).catch(() => undefined);
      entries = analysesOf((await fetchAnalysisRepository(sid)).entries);
    }

    const total = entries.length;
    let finished = entries.filter((e) => e.run_status === "done").length;
    const failed: { name: string; error: string }[] = [];
    const queue = entries.filter((e) => e.run_status !== "done");
    setBuildItems(entries.map((e) => ({ id: e.id, kind: "analysis" as const, name: e.name, state: e.run_status === "done" ? ("done" as const) : ("queued" as const) })));
    setLine("running", `Building analyses: ${finished} of ${total} finished.`);

    const worker = async () => {
      for (let entry = queue.shift(); entry; entry = queue.shift()) {
        const outcome = await runAnalysis(sid, entry.id, entry.name);
        announceChatChange();
        if (outcome.ok) {
          finished += 1;
          follow(`/analysis?open=${entry.id}`);
        } else {
          failed.push({ name: entry.name, error: outcome.reason });
        }
        setLine("running", `Building analyses: ${finished} of ${total} finished.`);
      }
    };
    // One at a time, so each finished analysis is on screen while the next one runs.
    await worker();
    return { done: finished, failed, total };
  };

  const finishBuild = async (sid: string) => {
    setLine("running", "Building analyses…");
    const { done, failed, total } = await runAnalyses(sid);
    const report = live.current.auditReport;
    const sensorIssues = (report?.issues ?? []).filter((i) => i.severity === "critical" && i.status !== "resolved");

    const attention: string[] = [];
    if (sensorIssues.length) attention.push(`${sensorIssues.length} data issue${sensorIssues.length > 1 ? "s" : ""} were flagged as critical in the audit`);
    for (const f of failed) attention.push(`"${f.name}" could not be built (${f.error.slice(0, 140)})`);

    const links: ChatLink[] = [{ label: "Add drill-downs on the Analysis page", path: "/analysis" }];
    if (sensorIssues.length) links.unshift({ label: "Open the audit", path: "/audit" });
    links.push({ label: "Open the report", path: "/report" });

    const head = `Report ready: ${done} of ${total} analyses built.`;
    const tail = attention.length
      ? ` ${attention.length === 1 ? "One thing needs" : `${attention.length} things need`} your attention: ${attention.join("; ")}.`
      : " Nothing needs your attention.";
    say(head + tail + " You can add drill-downs on the Analysis page, tell me what to change, or ask whether it is ready to send.", { links });
    setLine("done", `Report ready: ${done} of ${total} analyses built.`);
    setPhase("refine");
    // The report is the last step: the build ends there.
    navigate("/report");
  };

  /**
   * The PM pressed "Build the report". Whatever was accepted (on the Planner, Features or Analysis pages, or in
   * the chat) is computed and run, one analysis at a time, and the report is reviewed.
   */
  const runBuild = async () => {
    const sid = live.current.sessionId;
    if (!sid || building.current) return;
    // Features and analyses are built on the audited data: wait until the PM has made the audit decisions
    // (a decision changes the data and would throw the build away).
    const report = live.current.auditReport;
    if (report?.status !== "reviewed") {
      const pending = (report?.issues ?? []).filter((i) => i.requires_decision && i.status === "pending").length;
      setLine("paused_audit", pending ? `Waiting for your ${pending} audit decision${pending > 1 ? "s" : ""}.` : "Waiting for the data audit to finish.");
      say(
        "I'll start building as soon as the audit decisions are done" + (pending ? ` (${pending} still open).` : "."),
        { links: [{ label: "Open the audit", path: "/audit" }] }
      );
      return;
    }
    building.current = true;
    try {
      const [featureRepo, analysisRepo] = await Promise.all([fetchFeatureRepository(sid), fetchAnalysisRepository(sid)]);
      const firstFeature = featureRepo.entries.find((e) => e.status === "approved");
      if (!firstFeature && analysesOf(analysisRepo.entries).length === 0) {
        setLine("idle", "");
        setPhase("ready");
        say("There is nothing to build yet: accept some suggestions first, on the Planner page or here.", {
          links: [{ label: "Open the Planner", path: "/planner" }],
        });
        return;
      }
      setLine("running", "Calculating the features…");
      try {
        await applyFeatures(sid);
      } catch (err) {
        say(`Some calculations could not be computed (${errorText(err, "unknown error")}). I'll build what I can.`);
      }
      if (firstFeature) follow(`/features?open=${firstFeature.id}`);
      await finishBuild(sid);
    } catch (err) {
      setLine("error", errorText(err, "The build stopped."));
      say(`The build stopped: ${errorText(err, "something went wrong")}. Say "continue the build" to try again.`, { error: true });
    } finally {
      building.current = false;
    }
  };

  // The PM pressed Build before the data was loaded: start as soon as it is.
  useEffect(() => {
    if (sessionId && build.status === "waiting_data") void runBuild();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, build.status]);

  // The PM finished the audit decisions they were waiting for: build now.
  useEffect(() => {
    if (build.status === "paused_audit" && auditReport?.status === "reviewed") {
      say("Audit reviewed. Building now.");
      setLine("running", "Starting the build…");
      void runBuild();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [build.status, auditReport?.status]);

  // The data loaded is a different one (new session): the old build and changes no longer apply.
  const lastSession = useRef<string | null>(sessionId);
  useEffect(() => {
    if (lastSession.current && sessionId !== lastSession.current) {
      setChanges([]);
      setBuildItems([]);
      setReview([]);
      if (live.current.build.status !== "waiting_data") setBuild({ status: "idle", line: "" });
    }
    lastSession.current = sessionId;
  }, [sessionId]);

  // ---------------------------------------------------------------------------------------- build
  /** "Build the report": runs now, or as soon as the data is loaded and the audit decisions are made. */
  const startBuild = useCallback(() => {
    if (building.current) return;
    setPhase("build");
    setQuickReplies([]);
    if (live.current.sessionId) {
      // Not audited yet: runBuild explains what it is waiting for and queues the build.
      if (gateNow().ok) {
        say("Building the report from what you accepted. You can keep chatting or browse the pages while I work.");
        setLine("running", "Starting the build…");
      }
      void runBuild();
    } else {
      say("I'll build as soon as the data is loaded. Load it on the Configure page.", { links: [{ label: "Open Configure", path: "/upload" }] });
      setLine("waiting_data", "Waiting for the data to be loaded.");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const editAssumption = useCallback((id: string, text: string) => {
    setAssumptions((prev) => prev.map((a) => (a.id === id ? { ...a, text } : a)));
  }, []);
  const removeAssumption = useCallback((id: string) => {
    setAssumptions((prev) => prev.filter((a) => a.id !== id));
  }, []);

  // ------------------------------------------------------------------------------------- refine actions
  const addChange = (change: Omit<ChatChange, "id" | "state">) => setChanges((prev) => [...prev, { ...change, id: nextId(), state: "added" }]);

  /**
   * An analysis only runs once the calculations it needs are accepted and computed (the Analysis page does the same).
   * Prepares them; returns the reason when the analysis still cannot run, or null when it can.
   */
  const prepareAnalysis = async (sid: string, entryId: string): Promise<string | null> => {
    const find = async () => (await fetchAnalysisRepository(sid)).entries.find((e) => e.id === entryId);
    let entry = await find();
    if (!entry) return "it is no longer in the report";
    let needCompute = false;
    for (const need of entry.required_features ?? []) {
      if (need.feature_id && need.state === "not_approved") {
        await selectRequiredFeature(sid, entryId, need.feature_id).catch(() => undefined);
        needCompute = true;
      } else if (need.state === "not_computed") {
        needCompute = true;
      }
    }
    if (needCompute) {
      await applyFeatures(sid).catch(() => undefined);
      entry = await find();
    }
    return entry?.dependencies_satisfied === false ? entry.dependency_message ?? "a calculation it needs is not ready" : null;
  };

  /**
   * Runs one analysis for the PM and keeps the live list honest. When it cannot run yet (a calculation it needs
   * is missing) it is NOT marked as started, so the Analysis page runs it once the calculation is there.
   */
  const runAnalysis = async (sid: string, entryId: string, name: string): Promise<{ ok: true } | { ok: false; reason: string }> => {
    beginItem(entryId, name, "analysis");
    const blocked = await prepareAnalysis(sid, entryId).catch((err) => errorText(err, "it could not be prepared"));
    if (blocked) {
      patchItem(entryId, { state: "failed", error: blocked });
      return { ok: false, reason: `it cannot run yet: ${blocked}. The Analysis page shows what to select.` };
    }
    analysisStarted.current.add(entryId); // the Analysis page must not start it a second time
    try {
      const result = await runAnalysisEntry(sid, entryId);
      if (result.run_status === "done") {
        patchItem(entryId, { state: "done" });
        return { ok: true };
      }
      const reason = explainFailure(result.error);
      patchItem(entryId, { state: "failed", error: reason });
      return { ok: false, reason: `it did not run: ${reason}.` };
    } catch (err) {
      const reason = explainFailure(errorText(err, ""));
      patchItem(entryId, { state: "failed", error: reason });
      return { ok: false, reason: `it did not run: ${reason}.` };
    }
  };

  const addAnalysisAction = async (name: string, description: string, quiet = false): Promise<boolean> => {
    const sid = readySession();
    if (!sid) return false;
    if (!quiet) say(`Adding "${name}": drafting it, then running it…`);
    try {
      const draft = await draftAnalysis(sid, { name, description });
      const options = [draft.chart, ...draft.chart.alternatives];
      const columns = live.current.auditReport?.columns ?? [];
      const entry = await addCustomAnalysis(sid, {
        name,
        description,
        calculation_intent: description,
        input_columns: columns.filter((c) => draft.formula.includes(c)),
        formula: draft.formula,
        template: draft.template,
        chart_type: draft.chart.chart_type,
        chart_reason: draft.chart.reason,
        chart_alternatives: options.filter((c) => c.chart_type !== draft.chart.chart_type),
        filters: draft.filters.map((f) => ({ column: f.column, reason: f.reason })),
      });
      addChange({ kind: "analysis", label: name, entryId: entry.id, sessionId: sid });
      const outcome = await runAnalysis(sid, entry.id, name);
      announceChatChange(); // the Analysis page reads it again, so the new analysis is there when it opens
      if (!quiet) {
        say(
          outcome.ok
            ? `I added the analysis "${name}" and ran it. You can undo it under "What I changed".`
            : `I added "${name}", but ${outcome.reason}`,
          { error: !outcome.ok, links: [{ label: "Open this analysis", path: `/analysis?open=${entry.id}` }] }
        );
        navigate(`/analysis?open=${entry.id}`);
      }
      return true;
    } catch (err) {
      say(`I could not add "${name}": ${explainFailure(errorText(err, ""))}`, { error: true });
      return false;
    }
  };

  const addFeatureAction = async (name: string, description: string, quiet = false): Promise<boolean> => {
    const sid = readySession();
    if (!sid) return false;
    if (!quiet) say(`Adding the calculation "${name}"…`);
    try {
      const draft = await draftCustomFeature(sid, { name, description });
      if (draft.status !== "ok") throw new Error(draft.error ?? "the formula did not pass the check on your data");
      const entry = await addCustomFeature(sid, {
        name,
        description,
        calculation_intent: description,
        input_columns: draft.columns_used,
        formula: draft.formula,
        draft_token: draft.draft_token,
      });
      await applyFeatures(sid);
      addChange({ kind: "feature", label: name, entryId: entry.id, sessionId: sid });
      announceChatChange(); // the Features page reads it again, so the new calculation is there when it opens
      const sample = draft.preview_rows.slice(0, 3).map((row) => String(row[draft.output_column] ?? "")).filter(Boolean);
      if (!quiet) {
        const steps = shorten(draft.formula_steps.length ? draft.formula_steps.join(" ") : draft.formula, FEATURE_SUMMARY_CHARS);
        say(
          `I added "${name}" and computed it. In short: ${steps}` +
            (sample.length ? ` Sample values: ${sample.join(", ")}.` : "") +
            ` The full steps are in the calculation that just opened. You can undo it under "What I changed".`,
          { links: [{ label: "Open this calculation", path: `/features?open=${entry.id}` }] }
        );
        navigate(`/features?open=${entry.id}`);
      }
      return true;
    } catch (err) {
      say(`I could not add "${name}": ${explainFailure(errorText(err, ""))}`, { error: true });
      return false;
    }
  };

  const checkReadyAction = async () => {
    const sid = live.current.sessionId;
    if (!sid) {
      say("Nothing is built yet: there is no data loaded.");
      return;
    }
    try {
      const entries = analysesOf((await fetchAnalysisRepository(sid)).entries);
      const notDone = entries.filter((e) => e.run_status !== "done");
      const report = live.current.auditReport;
      const openIssues = (report?.issues ?? []).filter((i) => i.requires_decision && i.status === "pending");
      const undecided = live.current.pendingSuggestions;

      const gaps: string[] = [];
      if (!entries.length) gaps.push("no analysis has been accepted yet");
      if (notDone.length) gaps.push(`not finished or failed: ${notDone.map((e) => e.name).join(", ")}`);
      if (openIssues.length) gaps.push(`${openIssues.length} audit issue${openIssues.length > 1 ? "s" : ""} still wait for a decision`);
      if (undecided) gaps.push(`${undecided} suggestion${undecided > 1 ? "s" : ""} still wait for your accept or reject`);

      const caveat = " I can check that every accepted analysis ran, but I cannot compare numbers between slides yet, so please give those a quick look on the Report page.";
      if (!gaps.length) {
        say(`Every accepted analysis ran and nothing is waiting for a decision.${caveat}`, { links: [{ label: "Open the report", path: "/report" }] });
        return;
      }
      say(`Not quite ready: ${gaps.join("; ")}.${caveat}`, { links: [{ label: "Open the analyses", path: "/analysis" }] });
    } catch (err) {
      say(`I could not check that: ${errorText(err, "unknown error")}`, { error: true });
    }
  };

  const runAction = async (action: ChatAction) => {
    switch (action.type) {
      case "set_brief": {
        const lastUser = [...live.current.messages].reverse().find((m) => m.role === "user")?.text ?? "";
        if (canSetBrief(action.text, lastUser, briefText())) {
          const next = { ...live.current.brief, rawText: action.text, finalText: action.text, isEnglish: true };
          live.current.brief = next;
          chatBrief.current = true;
          onBriefChange(next);
        }
        break;
      }
      case "navigate": {
        const path = PAGE_PATH[action.page];
        if (path) {
          // With an item id the page opens that analysis or calculation next to the explanation in the chat.
          navigate(action.open ? `${path}?open=${encodeURIComponent(action.open)}` : path);
          say(`Opened the ${pageLabel(path)} page.`);
        }
        break;
      }
      case "add_analysis":
        await addAnalysisAction(action.name, action.description);
        break;
      case "add_feature":
        await addFeatureAction(action.name, action.description);
        break;
      case "check_ready":
        await checkReadyAction();
        break;
      case "continue_build": {
        const status = live.current.build.status;
        if (status === "error" || status === "idle") void runBuild();
        break;
      }
    }
  };

  // ----------------------------------------------------------------------------------------- talking
  /**
   * One turn with the model. `hidden` turns (the start of the interview) go to the model but are not shown
   * as something the PM said. Nothing the PM types is ever stored as the brief here: the brief lives in the
   * Configure field, or arrives through the model's set_brief action (see canSetBrief).
   */
  const send = useCallback(
    (raw: string, opts: { hidden?: boolean } = {}) => {
      const text = raw.trim();
      if (!text || busy) return;
      const userMsg: ChatMsg = { id: nextId(), role: "user", text };
      const history = opts.hidden ? live.current.messages : [...live.current.messages, userMsg];
      live.current.messages = history;
      setMessages(history);
      setQuickReplies([]);
      setNextQuestions([]);
      // "Add another analysis", "Add an analysis: ...": the suggestion and drafting agents do it, no chat-model call.
      // Before the data is loaded there is no interview: a pasted brief is just taken, and the PM is sent on to load.
      if (!opts.hidden && stageOf(live.current.pathname) === "configure" && live.current.phase === "interview" && looksLikeBrief(text)) {
        const next = { ...live.current.brief, rawText: text, finalText: text, isEnglish: true };
        live.current.brief = next;
        chatBrief.current = true;
        onBriefChange(next);
        say("Got the client brief. Load your data with the button below; I'll go through the brief with you on the Planner page, with examples from your data.");
        return;
      }
      const shortcut = opts.hidden ? null : shortcutFor(text);
      if (shortcut?.type === "suggest") {
        void suggestWithAi(shortcut.kind);
        return;
      }
      if (shortcut?.type === "own") {
        const title = shortcut.text.split(/\s+/).slice(0, 7).join(" ").replace(/[.,;:]+$/, "");
        setBusy(true);
        void (shortcut.kind === "analysis" ? addAnalysisAction(title, shortcut.text) : addFeatureAction(title, shortcut.text)).finally(() => setBusy(false));
        return;
      }
      setBusy(true);
      const gate = gateNow();
      const state = {
        open_item: live.current.chatFocus
          ? { id: live.current.chatFocus, kind: stageOf(live.current.pathname) === "features" ? "calculation" : "analysis" }
          : null,
        phase: live.current.phase,
        understanding: live.current.understanding,
        assumptions: live.current.assumptions,
        page: live.current.pathname,
        stage: stageOf(live.current.pathname),
        build: live.current.build,
        audit_reviewed: gate.ok,
      };
      chatTurn({
        session_id: live.current.sessionId,
        brief: briefText(),
        messages: transcriptOf(opts.hidden ? [...history, userMsg] : history),
        state,
      })
        .then(async (res) => {
          // A sentence that promises to open a page gets a button when the model sent no navigate action.
          // The first time something is settled (from a brief typed here or on the Configure page), say what was understood.
          const firstTime = !Object.values(live.current.understanding).some(Boolean);
          if (firstTime && res.phase !== "ready") {
            const summary = understandingReply(res.understanding);
            if (summary) say(summary.text, { facts: summary.facts });
          }
          const promised = res.actions.some((a) => a.type === "navigate") ? [] : pageLinksIn(res.reply);
          say(res.reply, promised.length ? { links: promised } : undefined);
          setPhase(res.phase);
          setUnderstanding(res.understanding);
          setAssumptions(res.assumptions);
          setQuickReplies(res.quick_replies);
          setNextQuestions(res.next_questions);
          // The PM confirmed the read-back: keep the answers with the session so the Planner can read them.
          const sid = live.current.sessionId;
          if (res.phase === "ready") {
            live.current.understanding = res.understanding;
            live.current.assumptions = res.assumptions;
            // The PM answered the questions without any brief: their answers are the Planner's input.
            if (!briefText()) {
              const written = briefFromAnswers(res.understanding);
              if (written) {
                const next = { ...live.current.brief, rawText: written, finalText: written, isEnglish: true };
                live.current.brief = next;
                chatBrief.current = true;
                onBriefChange(next);
              }
            }
            if (sid) {
              // The Planner plans from the saved answers, so it is only let go once they are saved. It is on the Planner
              // page already, or the PM is taken there.
              void persistInterview(sid).then(() => {
                setInterviewDone(true);
                if (stageOf(live.current.pathname) === "planner") return;
                navigate("/planner");
                say("Opened the Planner page: it plans from these answers.");
              });
            } else {
              setInterviewDone(true);
            }
          }
          for (const action of res.actions) await runAction(action);
        })
        .catch((err) => say(errorText(err, "I could not reach the assistant. Is the backend running?"), { error: true }))
        .finally(() => setBusy(false));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [busy]
  );

  const changesRef = useRef(changes);
  changesRef.current = changes;

  /** Opens the panel and, on a fresh conversation, has the assistant ask its first question. */
  const startInterview = useCallback(() => {
    setOpen(true);
    if (interviewBegan.current || live.current.phase !== "interview") return;
    interviewBegan.current = true;
    send(START_INTERVIEW_TURN, { hidden: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [send]);

  // Arriving on the Planner page with the data loaded: the questions about the brief start now, with examples from
  // the data. (The Planner waits for them, or for the PM to skip them.)
  const alreadyPlanned = Boolean(plannerResult);
  useEffect(() => {
    if (stageOf(location.pathname) !== "planner" || !sessionId || interviewDone || alreadyPlanned) return;
    startInterview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname, sessionId, interviewDone, alreadyPlanned]);

  // The pending suggestions of both kinds, as cards the PM accepts or rejects in the chat.
  const loadReview = async (sid: string) => {
    const [features, analyses] = await Promise.all([fetchFeatureRepository(sid), fetchAnalysisRepository(sid)]);
    const pending = (e: { status: string; source: string }) => e.status === "pending" && e.source === "ai_suggested";
    const items: ReviewItem[] = [
      ...features.entries.filter(pending).map((e) => ({ id: e.id, stage: "features" as const, kind: "feature" as const, name: e.name, description: e.description, state: "pending" as const })),
      ...analyses.entries.filter(pending).map((e) => ({ id: e.id, stage: "analysis" as const, kind: "analysis" as const, name: e.name, description: e.description, state: "pending" as const })),
    ];
    // What the server says is waiting, plus what is being decided or failed here (a failure must not vanish).
    // Decided suggestions are not kept: they show up on their page and in "What I changed".
    setReview((prev) => {
      const waiting = new Set(items.map((i) => i.id));
      return [...items, ...prev.filter((p) => !waiting.has(p.id) && (p.state === "working" || p.state === "error"))];
    });
    return items;
  };

  /** "Suggest with AI": the suggestion agent runs here, the suggestions come back as cards to accept or reject. */
  const suggestWithAi = useCallback(
    async (kind: "feature" | "analysis") => {
      const sid = readySession();
      if (!sid) return;
      const noun = kind === "feature" ? "calculations" : "analyses";
      setBusy(true);
      say(`Asking the AI for ${noun} that fit the brief…`);
      try {
        await (kind === "feature" ? suggestFeatureEntries(sid) : suggestAnalysisEntries(sid));
        const items = (await loadReview(sid)).filter((i) => i.kind === kind);
        say(
          items.length
            ? `${items.length} ${noun} suggested. Accept or reject each one below; open one to see its details on the page.`
            : `The AI had no new ${noun} to suggest.`
        );
        if (items.length) setSuggestedFor(kind === "feature" ? "features" : "analysis");
        navigate(kind === "feature" ? "/features" : "/analysis");
      } catch (err) {
        say(`I could not get suggestions: ${errorText(err, "unknown error")}`, { error: true });
      } finally {
        setBusy(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [navigate, say]
  );

  // Whatever is already waiting for a decision (the planner's items, earlier AI suggestions) shows up in the
  // chat as soon as it is opened, once per loaded dataset.
  const reviewLoadedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!open || !sessionId || reviewLoadedFor.current === sessionId) return;
    reviewLoadedFor.current = sessionId;
    void loadReview(sessionId).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, sessionId]);

  const setReviewState = (id: string, state: ReviewItem["state"], error?: string) =>
    setReview((prev) => prev.map((r) => (r.id === id ? { ...r, state, error } : r)));

  const decide = useCallback(
    async (id: string, accept: boolean) => {
      const sid = live.current.sessionId;
      const item = review.find((r) => r.id === id);
      if (!sid || !item || item.state === "working") return;
      if (id.startsWith("planner:")) {
        const next = { ...plannerDecisions, [Number(id.slice(8))]: (accept ? "accepted" : "rejected") as PmDecisionValue };
        setPlannerDecisions(next);
        savePlannerDecisions(next);
        return;
      }
      // Accepting a calculation or analysis computes it on the audited data.
      if (!readySession()) return;
      setReviewState(id, "working");
      try {
        if (!accept) {
          await rejectEntry(item.kind, sid, id);
          setReviewState(id, "rejected");
          announceChatChange();
          return;
        }
        if (item.kind === "feature") {
          beginItem(id, item.name, "feature");
          await acceptFeatureEntry(sid, id);
          await applyFeatures(sid);
          patchItem(id, { state: "done" });
          setReviewState(id, "accepted");
          announceChatChange();
          follow(`/features?open=${id}`);
          return;
        }
        await acceptAnalysisEntry(sid, id);
        const outcome = await runAnalysis(sid, id, item.name);
        setReviewState(id, outcome.ok ? "accepted" : "error", outcome.ok ? undefined : outcome.reason);
        announceChatChange();
        if (outcome.ok) follow(`/analysis?open=${id}`);
        else say(`I accepted "${item.name}", but ${outcome.reason}`, { error: true, links: [{ label: "Open this analysis", path: `/analysis?open=${id}` }] });
      } catch (err) {
        const reason = explainFailure(errorText(err, ""));
        if (item.kind === "feature") patchItem(id, { state: "failed", error: reason });
        setReviewState(id, "error", reason);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [review, plannerDecisions, plannerResult]
  );

  /** Accepts every pending suggestion of one page. Features and analyses compute one at a time, in order. */
  const acceptAll = useCallback(
    (stage: ReviewStage) => {
      void (async () => {
        if (stage === "planner") {
          const pending = plannerItems.filter((r) => r.state === "pending");
          if (!pending.length) return;
          const next = { ...plannerDecisions };
          pending.forEach((r) => (next[Number(r.id.slice(8))] = "accepted"));
          setPlannerDecisions(next);
          savePlannerDecisions(next);
          return;
        }
        const pending = repoReview.filter((r) => r.stage === stage && r.state === "pending");
        if (pending.length && !readySession()) return; // say why once, not once per item
        for (const r of pending) await decide(r.id, true);
      })();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [plannerItems, repoReview, plannerDecisions, plannerResult, decide]
  );

  const inspect = useCallback(
    (item: ReviewItem) =>
      navigate(
        item.id.startsWith("planner:")
          ? `/planner?tab=${item.kind === "analysis" ? "analyses" : "features"}&item=${item.id.slice(8)}`
          : `${item.kind === "feature" ? "/features" : "/analysis"}?open=${item.id}`
      ),
    [navigate]
  );

  const setAutoAccept = useCallback(
    (stage: ReviewStage, on: boolean) => setAutoAcceptState((prev) => ({ ...prev, [stage]: on })),
    []
  );

  // Arriving on Features or Analysis, or a page changing something there (an accept, new suggestions): show what is
  // waiting on that page.
  const pageChanges = usePageChangeCount();
  useEffect(() => {
    const here = stageOf(location.pathname);
    if (sessionId && (here === "features" || here === "analysis")) void loadReview(sessionId).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname, sessionId, pageChanges]);

  // The card stays open only on the page the PM asked for suggestions on; leaving that page folds it away. The marker is
  // set a moment before the router has moved to the page, so "not there yet" must not count as "left it".
  const reachedSuggested = useRef(false);
  useEffect(() => {
    if (!suggestedFor) {
      reachedSuggested.current = false;
    } else if (stageOf(location.pathname) === suggestedFor) {
      reachedSuggested.current = true;
    } else if (reachedSuggested.current) {
      reachedSuggested.current = false;
      setSuggestedFor(null);
    }
  }, [location.pathname, suggestedFor]);

  /**
   * Opens a page for a link in the chat. Going to the page the PM is already on does nothing by itself, so that case
   * makes the page read its data again (and, with an item id, the page opens that item).
   */
  const openPage = useCallback(
    (path: string) => {
      if (path.split("?")[0] === location.pathname) announceChatChange();
      navigate(path);
    },
    [navigate, location.pathname]
  );

  // Auto mode: a page set to "accept automatically" accepts each batch of suggestions once, as it arrives. Features and
  // analyses need the audited data, so they wait until the audit decisions are made.
  const autoHandled = useRef(new Set<string>());
  useEffect(() => {
    for (const stage of ["planner", "features", "analysis"] as const) {
      if (!autoAccept[stage]) continue;
      const pending = review.filter((r) => r.stage === stage && r.state === "pending");
      if (!pending.length || (stage !== "planner" && !audit.reviewed)) continue;
      const batch = `${stage}:${pending.map((r) => r.id).join(",")}`;
      if (autoHandled.current.has(batch)) continue;
      autoHandled.current.add(batch);
      say(`Accepting ${pending.length} suggestion${pending.length > 1 ? "s" : ""} automatically, as you asked for this page.`);
      acceptAll(stage);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoAccept, review, audit.reviewed]);

  const undoChange = useCallback(
    (id: string) => {
      const change = changesRef.current.find((c) => c.id === id);
      if (!change || change.state === "undone") return;
      rejectEntry(change.kind, change.sessionId, change.entryId)
        .then(() => {
          setChanges((prev) => prev.map((c) => (c.id === id ? { ...c, state: "undone" } : c)));
          announceChatChange();
          say(`Undone: "${change.label}" is out of the report.`);
        })
        .catch((err) => say(errorText(err, "Could not undo that."), { error: true }));
    },
    [say]
  );
  const reset = useCallback(() => {
    interviewBegan.current = false;
    chatBrief.current = false;
    setInterviewDone(false);
    setMessages([GREETING]);
    setPhase("interview");
    setUnderstanding(EMPTY_UNDERSTANDING);
    setAssumptions([]);
    setQuickReplies([]);
    setNextQuestions([]);
    setBuild({ status: "idle", line: "" });
    setChanges([]);
    setBuildItems([]);
    setReview([]);
  }, []);

  const value = useMemo<ChatValue>(
    () => ({
      review,
      suggestedFor,
      audit,
      autoAccept,
      setAutoAccept,
      decide,
      acceptAll,
      inspect,
      buildItems,
      open,
      setOpen,
      messages,
      busy,
      phase,
      plannerReady: Boolean(plannerResult),
      understanding,
      assumptions,
      // "Skip the questions" belongs to the interview, which happens on the Configure page.
      quickReplies:
        phase === "interview" && stageOf(location.pathname) === "planner" && !quickReplies.includes(SKIP_REPLY) && messages.length > 1
          ? [...quickReplies, SKIP_REPLY]
          : quickReplies,
      nextQuestions,
      build,
      changes,
      hasSession: Boolean(sessionId),
      startInterview,
      startBuild,
      persistInterview,
      suggestWithAi,
      openPage,
      send,
      editAssumption,
      removeAssumption,
      undoChange,
      reset,
    }),
    [review, suggestedFor, audit, autoAccept, setAutoAccept, decide, acceptAll, inspect, buildItems, open, messages, busy, phase, plannerResult, understanding, assumptions, quickReplies, nextQuestions, build, changes, location.pathname, sessionId, startInterview, startBuild, persistInterview, suggestWithAi, openPage, send, editAssumption, removeAssumption, undoChange, reset]
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

function transcriptOf(messages: ChatMsg[]): ChatTurnMessage[] {
  return messages
    .filter((m) => m.id !== "greeting" && !m.error)
    .map((m) => ({ role: m.role, content: m.text }));
}
