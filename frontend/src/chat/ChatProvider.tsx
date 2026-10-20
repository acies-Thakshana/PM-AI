import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  EMPTY_UNDERSTANDING,
  chatTurn,
  rejectEntry,
  saveInterview,
} from "../api/chat";
import type { Assumption, ChatAction, ChatPhase, ChatPlan, ChatTurnMessage, InterviewRecord, Understanding } from "../api/chat";
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
} from "../api/audit";
import type { AnalysisRepositoryEntry, AuditReport } from "../api/audit";
import type { FilesState } from "../App";
import type { BriefState } from "../components/ClientBriefInput";
import { useStoredRef } from "../state/sessionStore";

// The chat assistant: one conversation that first interviews the PM about the client brief and, once the
// plan is approved, builds the report (planner -> audit -> calculations -> analyses) and then refines it
// on request. The model only talks and proposes actions (see routers/chat.py); everything that changes data
// happens here, through the same endpoints the pages use, so the pages show the result when opened.

export interface ChatLink {
  label: string;
  path: string;
}

export interface ChatButton {
  label: string;
  onClick: () => void;
}

export interface ChatMsg {
  id: string;
  role: "user" | "assistant";
  text: string;
  error?: boolean;
  links?: ChatLink[];
  buttons?: ChatButton[];
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
  state: "added" | "kept" | "undone";
}

interface ChatValue {
  open: boolean;
  setOpen: (open: boolean) => void;
  messages: ChatMsg[];
  busy: boolean;
  phase: ChatPhase;
  understanding: Understanding;
  assumptions: Assumption[];
  plan: ChatPlan | null;
  quickReplies: string[];
  build: BuildState;
  changes: ChatChange[];
  hasSession: boolean;
  send: (text: string) => void;
  approvePlan: () => void;
  cancelPlan: () => void;
  editAssumption: (id: string, text: string) => void;
  removeAssumption: (id: string) => void;
  removePlanItem: (kind: "analyses" | "features", index: number) => void;
  keepChange: (id: string) => void;
  undoChange: (id: string) => void;
  reset: () => void;
}

const ChatContext = createContext<ChatValue | null>(null);

export function useChat(): ChatValue {
  const value = useContext(ChatContext);
  if (!value) throw new Error("useChat must be used inside ChatProvider");
  return value;
}

const PAGE_PATH: Record<string, string> = {
  upload: "/upload",
  planner: "/planner",
  audit: "/audit",
  features: "/features",
  analysis: "/analysis",
  report: "/report",
};

const GREETING: ChatMsg = {
  id: "greeting",
  role: "assistant",
  text:
    "Hi! Your data is audited. Before I build the analyses, I'll ask a few quick questions about the client brief so the report fits what the client actually needs. " +
    "Short on time? Say \"skip the questions\" and I'll use my best guess and show you every assumption. Or press \"Build the report\" to begin.",
};

const SKIP_REPLY = "Skip the questions, use your best guess";

let idCounter = 0;
const nextId = () => `m${Date.now().toString(36)}${(idCounter++).toString(36)}`;

// Words that make two names "the same thing" when most of them overlap ("Alarm rate by origin" vs "Alarms by Origin").
function nameTokens(name: string): Set<string> {
  return new Set(
    name
      .toLowerCase()
      .replace(/[^a-z0-9 ]+/g, " ")
      .split(/\s+/)
      .map((w) => w.replace(/s$/, ""))
      .filter((w) => w.length > 2 && !["the", "and", "per", "for", "with", "all"].includes(w))
  );
}

function sameThing(a: string, b: string): boolean {
  const ta = nameTokens(a);
  const tb = nameTokens(b);
  if (!ta.size || !tb.size) return false;
  let shared = 0;
  ta.forEach((t) => {
    if (tb.has(t)) shared += 1;
  });
  return shared / Math.min(ta.size, tb.size) >= 0.6;
}

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
  const [plan, setPlan] = useState<ChatPlan | null>(null);
  const [quickReplies, setQuickReplies] = useState<string[]>([]);
  const [build, setBuild] = useState<BuildState>({ status: "idle", line: "" });
  const [changes, setChanges] = useState<ChatChange[]>([]);

  // Analyses started here must not be started a second time by the Analysis page's own auto-run.
  const analysisStarted = useStoredRef<{ current: Set<string> }>("analysis.autoStarted", () => ({ current: new Set<string>() }));

  // Latest values for the async code (a build outlives the render that started it).
  const live = useRef({ brief, files, sessionId, auditReport, plan, understanding, assumptions, phase, build, messages, pathname: location.pathname });
  live.current = { brief, files, sessionId, auditReport, plan, understanding, assumptions, phase, build, messages, pathname: location.pathname };

  const interview = useRef<InterviewRecord | null>(null);
  const savedFor = useRef<string | null>(null);
  const building = useRef(false);

  const briefText = () => (live.current.brief.rawText || live.current.brief.finalText || "").trim();

  const say = useCallback((text: string, extra?: Partial<ChatMsg>) => {
    setMessages((prev) => [...prev, { id: nextId(), role: "assistant", text, ...extra }]);
  }, []);

  const setLine = (status: BuildStatus, line: string) => setBuild({ status, line });

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
    setLine("running", `Building analyses: ${finished} of ${total} finished.`);

    const worker = async () => {
      for (let entry = queue.shift(); entry; entry = queue.shift()) {
        analysisStarted.current.add(entry.id);
        try {
          const result = await runAnalysisEntry(sid, entry.id);
          if (result.run_status === "done") finished += 1;
          else failed.push({ name: entry.name, error: result.error ?? "no result" });
        } catch (err) {
          failed.push({ name: entry.name, error: errorText(err, "could not run") });
        }
        setLine("running", `Building analyses: ${finished} of ${total} finished.`);
      }
    };
    await Promise.all([worker(), worker()]);
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

    const links: ChatLink[] = [{ label: "Open the analyses", path: "/analysis" }];
    if (sensorIssues.length) links.unshift({ label: "Open the audit", path: "/audit" });
    links.push({ label: "Open the report", path: "/report" });

    const head = `Report ready: ${done} of ${total} analyses built.`;
    const tail = attention.length
      ? ` ${attention.length === 1 ? "One thing needs" : `${attention.length} things need`} your attention: ${attention.join("; ")}.`
      : " Nothing needs your attention.";
    say(head + tail + " Tell me what to change, or ask whether it is ready to send.", { links });
    setLine("done", `Report ready: ${done} of ${total} analyses built.`);
    setPhase("refine");
  };

  /** Adds the approved plan's items that the Planner/Features/Analysis steps do not already have. */
  const addPlanItems = async (sid: string): Promise<void> => {
    const planned = interview.current?.plan;
    if (!planned) return;
    const [featureRepo, analysisRepo] = await Promise.all([fetchFeatureRepository(sid), fetchAnalysisRepository(sid)]);
    const features = featureRepo.entries.filter((e) => e.status !== "rejected");
    const analyses = analysisRepo.entries.filter((e) => e.status !== "rejected" && e.source !== "drilldown");
    let failed = 0;

    // Calculations first: the analyses may need them.
    for (const item of planned.features) {
      const found = features.find((e) => sameThing(e.name, item.name));
      setLine("running", `Adding the calculation "${item.name}"…`);
      if (found) {
        if (found.status === "pending") await acceptFeatureEntry(sid, found.id).catch(() => (failed += 1));
      } else if (!(await addFeatureAction(item.name, item.description, true))) failed += 1;
    }
    for (const item of planned.analyses) {
      const found = analyses.find((e) => sameThing(e.name, item.name));
      setLine("running", `Adding the analysis "${item.name}"…`);
      if (found) {
        if (found.status === "pending") await acceptAnalysisEntry(sid, found.id).catch(() => (failed += 1));
      } else if (!(await addAnalysisAction(item.name, item.description, true))) failed += 1;
    }
    if (failed) say(`${failed} item${failed > 1 ? "s" : ""} of the plan could not be added; the review below says which.`);
  };

  /** The plan was approved after the audit: add what the plan needs, calculate, run the analyses, review. */
  const runBuild = async () => {
    const sid = live.current.sessionId;
    if (!sid || building.current) return;
    building.current = true;
    try {
      if (interview.current && savedFor.current !== sid) {
        await saveInterview(sid, interview.current);
        savedFor.current = sid;
      }
      await addPlanItems(sid);
      setLine("running", "Calculating the features…");
      try {
        await applyFeatures(sid);
      } catch (err) {
        say(`Some calculations could not be computed (${errorText(err, "unknown error")}). I'll build what I can.`);
      }
      await finishBuild(sid);
    } catch (err) {
      setLine("error", errorText(err, "The build stopped."));
      say(`The build stopped: ${errorText(err, "something went wrong")}. Say "continue the build" to try again.`, { error: true });
    } finally {
      building.current = false;
    }
  };

  // The data arrived after the plan was approved: start the build.
  useEffect(() => {
    if (sessionId && build.status === "waiting_data") void runBuild();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, build.status]);

  // The data loaded is a different one (new session): the old build and changes no longer apply.
  const lastSession = useRef<string | null>(sessionId);
  useEffect(() => {
    if (lastSession.current && sessionId !== lastSession.current) {
      setChanges([]);
      if (live.current.build.status !== "waiting_data") setBuild({ status: "idle", line: "" });
    }
    lastSession.current = sessionId;
  }, [sessionId]);

  // ---------------------------------------------------------------------------------------- plan
  const approvePlan = useCallback(() => {
    const current = live.current;
    if (!current.plan) return;
    interview.current = {
      brief: briefText(),
      understanding: current.understanding,
      assumptions: current.assumptions,
      plan: current.plan,
      transcript: transcriptOf(current.messages),
    };
    savedFor.current = null;
    setPhase("build");
    setQuickReplies([]);
    const counts = `${current.plan.analyses.length} analyses and ${current.plan.features.length} calculations`;
    if (current.sessionId) {
      say(`Plan approved: ${counts}. Building now. You can keep chatting or browse the pages while I work.`);
      setLine("running", "Starting the build…");
      void runBuild();
    } else {
      say(
        `Plan approved: ${counts}. I need the data first: load the trips (or upload the files) on the Configure page and I'll start building as soon as it is in.`,
        { links: [{ label: "Open Configure", path: "/upload" }] }
      );
      setLine("waiting_data", "Waiting for the data to be loaded.");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const cancelPlan = useCallback(() => {
    setPlan(null);
    setPhase("interview");
    setQuickReplies([]);
    say("Plan cancelled. Nothing was built. Tell me what you'd like to change and I'll propose a new one.");
  }, [say]);

  const removePlanItem = useCallback((kind: "analyses" | "features", index: number) => {
    setPlan((prev) => (prev ? { ...prev, [kind]: prev[kind].filter((_, i) => i !== index) } : prev));
  }, []);

  const editAssumption = useCallback((id: string, text: string) => {
    setAssumptions((prev) => prev.map((a) => (a.id === id ? { ...a, text } : a)));
  }, []);
  const removeAssumption = useCallback((id: string) => {
    setAssumptions((prev) => prev.filter((a) => a.id !== id));
  }, []);

  // ------------------------------------------------------------------------------------- refine actions
  const addChange = (change: Omit<ChatChange, "id" | "state">) => setChanges((prev) => [...prev, { ...change, id: nextId(), state: "added" }]);

  const addAnalysisAction = async (name: string, description: string, quiet = false): Promise<boolean> => {
    const sid = live.current.sessionId;
    if (!sid) {
      say("I need data loaded before I can add an analysis. Let's go to the Configure page first.", { links: [{ label: "Open Configure", path: "/upload" }] });
      return false;
    }
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
      analysisStarted.current.add(entry.id);
      const result = await runAnalysisEntry(sid, entry.id).catch((err) => {
        say(`I added "${name}" but it could not be run yet (${errorText(err, "unknown error")}). You can retry it on the Analysis page.`, { error: true });
        return null;
      });
      addChange({ kind: "analysis", label: name, entryId: entry.id, sessionId: sid });
      if (!quiet && result?.run_status === "done") {
        say(`I added the analysis "${name}" and ran it. Keep or undo? (See "What I changed" below.)`, { links: [{ label: "Open the analyses", path: "/analysis" }] });
      }
      if (!quiet) navigate("/analysis");
      return true;
    } catch (err) {
      say(`I could not add "${name}": ${errorText(err, "unknown error")}`, { error: true });
      return false;
    }
  };

  const addFeatureAction = async (name: string, description: string, quiet = false): Promise<boolean> => {
    const sid = live.current.sessionId;
    if (!sid) {
      say("I need data loaded before I can add a calculation. Let's go to the Configure page first.", { links: [{ label: "Open Configure", path: "/upload" }] });
      return false;
    }
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
      const sample = draft.preview_rows.slice(0, 3).map((row) => String(row[draft.output_column] ?? "")).filter(Boolean);
      if (!quiet) say(
        `I added "${name}" and computed it. In plain words: ${draft.formula_steps.length ? draft.formula_steps.join(" ") : draft.formula}` +
          (sample.length ? ` Sample values: ${sample.join(", ")}.` : "") +
          ` Keep or undo? (See "What I changed" below.)`,
        { links: [{ label: "Open the features", path: "/features" }] }
      );
      if (!quiet) navigate("/features");
      return true;
    } catch (err) {
      say(`I could not add "${name}": ${errorText(err, "unknown error")}`, { error: true });
      return false;
    }
  };

  const explainAction = async (target: string) => {
    const sid = live.current.sessionId;
    if (!sid) {
      say("There is no data loaded yet, so nothing has been calculated.");
      return;
    }
    try {
      const entries = analysesOf((await fetchAnalysisRepository(sid)).entries);
      const entry = entries.find((e) => sameThing(e.name, target)) ?? (entries.length === 1 ? entries[0] : undefined);
      if (!entry) {
        say(`I could not find an analysis called "${target}". The ones I know: ${entries.map((e) => e.name).join(", ") || "none yet"}.`);
        return;
      }
      const how = (entry.plan_text ?? entry.formula ?? "").trim();
      say(
        how
          ? `Here is how "${entry.name}" was calculated:\n${how}${entry.interpretation ? `\n\nWhat it shows: ${entry.interpretation}` : ""}`
          : `"${entry.name}" has not been run yet, so there is no calculation to explain.`,
        { links: [{ label: "Open the analyses", path: "/analysis" }] }
      );
      navigate("/analysis");
    } catch (err) {
      say(`I could not look that up: ${errorText(err, "unknown error")}`, { error: true });
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
      const planned = live.current.plan ?? interview.current?.plan ?? null;
      const missing = (planned?.analyses ?? []).filter((p) => !entries.some((e) => sameThing(e.name, p.name)));
      const notDone = entries.filter((e) => e.run_status !== "done");
      const report = live.current.auditReport;
      const openIssues = (report?.issues ?? []).filter((i) => i.requires_decision && i.status === "pending");

      const gaps: string[] = [];
      if (missing.length) gaps.push(`missing from the report: ${missing.map((m) => m.name).join(", ")}`);
      if (notDone.length) gaps.push(`not finished or failed: ${notDone.map((e) => e.name).join(", ")}`);
      if (openIssues.length) gaps.push(`${openIssues.length} audit issue${openIssues.length > 1 ? "s" : ""} still wait for a decision`);
      if (!planned) gaps.push("there is no approved plan to check the brief against");

      const caveat = " I can check coverage and that every analysis ran, but I cannot compare numbers between slides yet, so please give those a quick look on the Report page.";
      if (!gaps.length) {
        say(`Everything planned from the brief is in the report and every analysis ran.${caveat}`, { links: [{ label: "Open the report", path: "/report" }] });
        return;
      }
      const buttons: ChatButton[] = missing.map((m) => ({ label: `Add "${m.name}"`, onClick: () => void addAnalysisAction(m.name, m.description) }));
      say(`Not quite ready: ${gaps.join("; ")}.${caveat}`, {
        buttons: buttons.length ? buttons : undefined,
        links: [{ label: "Open the analyses", path: "/analysis" }],
      });
    } catch (err) {
      say(`I could not check that: ${errorText(err, "unknown error")}`, { error: true });
    }
  };

  const runAction = async (action: ChatAction) => {
    switch (action.type) {
      case "set_brief":
        onBriefChange({ ...live.current.brief, rawText: action.text, finalText: action.text, isEnglish: true });
        live.current.brief = { ...live.current.brief, rawText: action.text, finalText: action.text };
        break;
      case "approve_plan":
        if (live.current.plan && live.current.phase !== "build") approvePlan();
        break;
      case "navigate":
        navigate(PAGE_PATH[action.page]);
        break;
      case "add_analysis":
        await addAnalysisAction(action.name, action.description);
        break;
      case "add_feature":
        await addFeatureAction(action.name, action.description);
        break;
      case "explain":
        await explainAction(action.target);
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
  const send = useCallback(
    (raw: string) => {
      const text = raw.trim();
      if (!text || busy) return;
      const userMsg: ChatMsg = { id: nextId(), role: "user", text };
      const history = [...live.current.messages, userMsg];
      live.current.messages = history;
      // The first thing said in an empty chat is the brief (the model may also store it with set_brief).
      if (!briefText() && history.filter((m) => m.role === "user").length === 1 && text.split(/\s+/).length >= 5) {
        const next = { ...live.current.brief, rawText: text, finalText: text, isEnglish: true };
        live.current.brief = next;
        onBriefChange(next);
      }
      setMessages(history);
      setQuickReplies([]);
      setBusy(true);
      const state = {
        phase: live.current.phase,
        understanding: live.current.understanding,
        assumptions: live.current.assumptions,
        plan: live.current.plan,
        page: live.current.pathname,
        build: live.current.build,
        approved_plan_exists: Boolean(interview.current?.plan),
      };
      chatTurn({
        session_id: live.current.sessionId,
        brief: briefText(),
        messages: transcriptOf(history),
        state,
      })
        .then(async (res) => {
          say(res.reply);
          setPhase(res.phase);
          setUnderstanding(res.understanding);
          setAssumptions(res.assumptions);
          setPlan(res.plan);
          setQuickReplies(res.quick_replies);
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

  const keepChange = useCallback((id: string) => setChanges((prev) => prev.map((c) => (c.id === id ? { ...c, state: "kept" } : c))), []);

  const undoChange = useCallback(
    (id: string) => {
      const change = changesRef.current.find((c) => c.id === id);
      if (!change || change.state === "undone") return;
      rejectEntry(change.kind, change.sessionId, change.entryId)
        .then(() => {
          setChanges((prev) => prev.map((c) => (c.id === id ? { ...c, state: "undone" } : c)));
          say(`Undone: "${change.label}" is out of the report.`);
        })
        .catch((err) => say(errorText(err, "Could not undo that."), { error: true }));
    },
    [say]
  );
  const reset = useCallback(() => {
    interview.current = null;
    savedFor.current = null;
    setMessages([GREETING]);
    setPhase("interview");
    setUnderstanding(EMPTY_UNDERSTANDING);
    setAssumptions([]);
    setPlan(null);
    setQuickReplies([]);
    setBuild({ status: "idle", line: "" });
    setChanges([]);
  }, []);

  const value = useMemo<ChatValue>(
    () => ({
      open,
      setOpen,
      messages,
      busy,
      phase,
      understanding,
      assumptions,
      plan,
      quickReplies: phase === "interview" && !quickReplies.includes(SKIP_REPLY) && messages.length > 1 ? [...quickReplies, SKIP_REPLY] : quickReplies,
      build,
      changes,
      hasSession: Boolean(sessionId),
      send,
      approvePlan,
      cancelPlan,
      editAssumption,
      removeAssumption,
      removePlanItem,
      keepChange,
      undoChange,
      reset,
    }),
    [open, messages, busy, phase, understanding, assumptions, plan, quickReplies, build, changes, sessionId, send, approvePlan, cancelPlan, editAssumption, removeAssumption, removePlanItem, keepChange, undoChange, reset]
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

function transcriptOf(messages: ChatMsg[]): ChatTurnMessage[] {
  return messages
    .filter((m) => m.id !== "greeting" && !m.error)
    .map((m) => ({ role: m.role, content: m.text }));
}
