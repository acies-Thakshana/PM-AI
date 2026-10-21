import ThinkingLoader from "../components/ThinkingLoader";
import { useEffect, useRef, useState } from "react";
import { useStoredRef, useStoredState } from "../state/sessionStore";
import { useNavigate } from "react-router-dom";
import ChatMessage from "../components/ChatMessage";
import AnalysisChat from "../components/AnalysisChat";
import type { AnalysisDraftState, AnalysisLogEntry } from "../components/AnalysisChat";
import { useStageChrome } from "../context/stageChrome";
import type { StageReply } from "../context/stageChrome";
import AnalysisCard from "../components/AnalysisCard";
import AnalysisDetailModal from "../components/AnalysisDetailModal";
import { ancestorTrail, buildLevelTree } from "../utils/drilldownTree";
import {
  acceptAnalysisEntry,
  addCustomAnalysis,
  draftAnalysis,
  fetchAnalysisRepository,
  fetchFeatureReport,
  fetchOverallAnalysis,
  filterAnalysisEntry,
  fetchDrilldownOptions,
  proposeDrilldowns,
  acceptDrilldownPath,
  confirmDrilldown,
  fetchDrilldownPaths,
  refreshDrilldown,
  rejectDrilldownPath,
  suggestDrilldownPath,
  runAnalysisEntry,
  applyFeatures,
  selectRequiredFeature,
  suggestAnalysisEntries,
  uploadAnalysisDefinitions,
  AuditApiError,
  type AddCustomAnalysisBody,
  type AnalysisFilterSelections,
  type AnalysisRepositoryEntry,
  type ConfirmDrilldownBody,
  type FeatureReport,
  type OverallAnalysisReport,
} from "../api/audit";
import { AUDITED_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { AuditReportsState, FilesState } from "../App";

// Stable empty Set reference for entries with nothing dismissed yet.
const EMPTY_ID_SET: Set<string> = new Set();

interface AnalysisPageProps {
  files: FilesState;
  auditReports: AuditReportsState;
}

type FeatureReportsState = Partial<Record<UploadSlotId, FeatureReport>>;
type RepositoryState = Partial<Record<UploadSlotId, AnalysisRepositoryEntry[]>>;
type OverallReportsState = Partial<Record<UploadSlotId, OverallAnalysisReport>>;
type LoadingState = Partial<Record<UploadSlotId, boolean>>;
type ErrorsState = Partial<Record<UploadSlotId, string>>;
type BusyIdState = Partial<Record<UploadSlotId, string>>;

// Each analysis run is several LLM calls, so only this many run at once.
const MAX_CONCURRENT_RUNS = 2;
// Start of the 422 detail when a run is refused for unmet required features.
const REQUIRED_FEATURES_PREFIX = "Select all required features";
// Approved, not yet run, and waiting on required features.
const isBlocked = (e: AnalysisRepositoryEntry) =>
  e.status === "approved" && e.run_status === "not_run" && e.dependencies_satisfied === false;
export default function AnalysisPage({ files, auditReports }: AnalysisPageProps) {
  const navigate = useNavigate();

  const [featureReports, setFeatureReports] = useStoredState<FeatureReportsState>("analysis.featureReports", {});
  const [featureCheckLoading, setFeatureCheckLoading] = useState<LoadingState>({});
  const [featureCheckFailed, setFeatureCheckFailed] = useState<LoadingState>({});

  const [repositories, setRepositories] = useStoredState<RepositoryState>("analysis.repositories", {});
  // The Report page's own selection, so a skipped drill-down level can be left out of the report from here.
  const [, setReportSelected] = useStoredState<Record<string, boolean>>("report.selected", {});
  const [repoLoading, setRepoLoading] = useStoredState<LoadingState>("analysis.repoLoading", {});
  const [repoError, setRepoError] = useState<ErrorsState>({});

  const [runningIds, setRunningIds] = useStoredState<Record<string, boolean>>("analysis.runningIds", {});
  const [runFailures, setRunFailures] = useStoredState<Record<string, string | undefined>>("analysis.runFailures", {});
  // Entries the auto-runner has already started once -- it never starts the
  // same entry twice; a failed run is retried only from the card.
  const autoStarted = useStoredRef<{ current: Set<string> }>("analysis.autoStarted", () => ({ current: new Set<string>() }));
  // Required-feature actions per analysis entry: what's running, and errors.
  const [featureBusy, setFeatureBusy] = useStoredState<Record<string, string | undefined>>("analysis.featureBusy", {});
  const [featureErrors, setFeatureErrors] = useState<Record<string, string | undefined>>({});
  // Per slot: the set of finished analyses the last summary was generated
  // for, so the summary regenerates only when that set actually changes.
  const summarizedFor = useStoredRef<{ current: Partial<Record<UploadSlotId, string>> }>("analysis.summarizedFor", () => ({ current: {} }));
  const [suggestLoading, setSuggestLoading] = useStoredState<LoadingState>("analysis.suggestLoading", {});
  const [suggestError, setSuggestError] = useState<ErrorsState>({});
  const [applyingEntryId, setApplyingEntryId] = useStoredState<BusyIdState>("analysis.applyingEntryId", {});
  const [addingAnalysis, setAddingAnalysis] = useStoredState<LoadingState>("analysis.addingAnalysis", {});
  // Ids the PM has explicitly hidden from an entry's Selected Drill-downs
  // list -- frontend-only. "Selected" itself is derived straight from real
  // repository data (triggered suggestions + existing chain levels), never
  // hand-tracked, so it can't fall out of sync with what actually exists.
  const [dismissedDrilldowns, setDismissedDrilldowns] = useStoredState<Record<string, Set<string>>>("analysis.dismissedDrilldowns", {});

  const [overallReports, setOverallReports] = useStoredState<OverallReportsState>("analysis.overallReports", {});
  const [overallLoading, setOverallLoading] = useStoredState<LoadingState>("analysis.overallLoading", {});
  const [overallError, setOverallError] = useState<ErrorsState>({});

  const [openEntry, setOpenEntry] = useState<{ slotId: UploadSlotId; entryId: string } | null>(null);
  // Bumped after each guided Confirm so the open modal switches to its Selected Drill-downs tab.
  const [openSelectedSignal, setOpenSelectedSignal] = useState(0);

  const [defsError, setDefsError] = useState<string | null>(null);
  const [defsLoading, setDefsLoading] = useStoredState("analysis.defsLoading", false);
  // True once we've either attempted the Analysis Profile upload (success or
  // failure) or confirmed there isn't one -- gates the first repository fetch
  // so predefined analyses are included when available, without ever
  // requiring the file to exist.
  const [defsAttempted, setDefsAttempted] = useStoredState("analysis.defsAttempted", false);

  const auditedReady = AUDITED_SLOTS.filter((id) => files[id] && auditReports[id]?.status === "reviewed");
  const hasAnalysisProfileFile = !!files.analysisProfile;

  // Step 0: confirm feature engineering has actually run for each audited
  // slot -- an analysis can group by engineered columns, so it needs that
  // step done first.
  // Server-derived data (the feature report, the analysis repository) can be
  // changed by the Features page between visits, so each visit refetches it once
  // while the cached copy stays on screen -- no flash of an empty page.
  const refreshedThisVisit = useRef<Set<string>>(new Set());

  useEffect(() => {
    for (const id of auditedReady) {
      if (featureCheckLoading[id] || featureCheckFailed[id] || refreshedThisVisit.current.has(`feature:${id}`)) continue;
      refreshedThisVisit.current.add(`feature:${id}`);
      const sessionId = auditReports[id]!.session_id;
      setFeatureCheckLoading((prev) => ({ ...prev, [id]: true }));
      fetchFeatureReport(sessionId)
        .then((report) => setFeatureReports((prev) => ({ ...prev, [id]: report })))
        .catch(() => setFeatureCheckFailed((prev) => ({ ...prev, [id]: true })))
        .finally(() => setFeatureCheckLoading((prev) => ({ ...prev, [id]: false })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditedReady, auditReports]);

  const slotsReady = auditedReady.filter((id) => (featureReports[id]?.features.length ?? 0) > 0);

  // Step 1 (optional): if an Analysis Profile was uploaded, parse it so its
  // analyses can join the repository as "predefined" entries. Not required --
  // planner-approved, custom, and AI-suggested analyses work with or without
  // this file.
  useEffect(() => {
    if (defsAttempted || defsLoading) return;
    if (!hasAnalysisProfileFile) {
      setDefsAttempted(true);
      return;
    }
    setDefsLoading(true);
    uploadAnalysisDefinitions(files.analysisProfile!)
      .catch((err) => setDefsError(err instanceof AuditApiError ? err.message : "Could not upload the Analysis Profile."))
      .finally(() => {
        setDefsLoading(false);
        setDefsAttempted(true);
      });
  }, [hasAnalysisProfileFile, files.analysisProfile, defsAttempted, defsLoading]);

  const refreshRepository = (id: UploadSlotId, sessionId: string) =>
    fetchAnalysisRepository(sessionId).then((repo) => setRepositories((prev) => ({ ...prev, [id]: repo.entries })));

  // Step 2: once the Analysis Profile upload has settled (or there wasn't
  // one), load the repository for each ready slot. Entries then run on
  // their own (see the auto-run effect below).
  useEffect(() => {
    if (!defsAttempted) return;
    for (const id of slotsReady) {
      if (repoLoading[id] || repoError[id] || refreshedThisVisit.current.has(`repo:${id}`)) continue;
      refreshedThisVisit.current.add(`repo:${id}`);
      const sessionId = auditReports[id]!.session_id;
      setRepoLoading((prev) => ({ ...prev, [id]: true }));
      refreshRepository(id, sessionId)
        .catch((err) =>
          setRepoError((prev) => ({
            ...prev,
            [id]: err instanceof AuditApiError ? err.message : "Could not load the analysis repository.",
          }))
        )
        .finally(() => setRepoLoading((prev) => ({ ...prev, [id]: false })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defsAttempted, slotsReady, auditReports]);

  const updateEntry = (id: UploadSlotId, updated: AnalysisRepositoryEntry) => {
    setRepositories((prev) => ({
      ...prev,
      [id]: (prev[id] ?? []).map((e) => (e.id === updated.id ? updated : e)),
    }));
  };

  const runEntry = (id: UploadSlotId, entry: AnalysisRepositoryEntry) => {
    const sessionId = auditReports[id]!.session_id;
    setRunFailures((prev) => ({ ...prev, [entry.id]: undefined }));
    setRunningIds((prev) => ({ ...prev, [entry.id]: true }));
    runAnalysisEntry(sessionId, entry.id)
      .then((updated) => updateEntry(id, updated))
      .catch((err) => {
        const message = err instanceof AuditApiError ? err.message : "Could not run this analysis.";
        if (message.startsWith(REQUIRED_FEATURES_PREFIX)) {
          // The backend refused because a required feature isn't ready.
          // Show the detail on the card, refresh the entry's dependency
          // status, and let the auto-runner pick it up once satisfied.
          autoStarted.current.delete(entry.id);
          setFeatureErrors((prev) => ({ ...prev, [entry.id]: message }));
          refreshRepository(id, sessionId).catch(() => undefined);
          return;
        }
        // Recorded per entry (not as a page-level error) so the card can say
        // what went wrong -- the auto-runner never retries a failed entry on
        // its own, which would loop on a persistent failure.
        setRunFailures((prev) => ({ ...prev, [entry.id]: message }));
      })
      .finally(() => setRunningIds((prev) => ({ ...prev, [entry.id]: false })));
  };

  // Computes features (the existing Feature step) so an approved required
  // feature becomes usable, then refetches so dependency status updates.
  const computeRequiredFeatures = (id: UploadSlotId, entryId: string): Promise<void> => {
    const sessionId = auditReports[id]!.session_id;
    setFeatureBusy((prev) => ({ ...prev, [entryId]: "compute" }));
    return applyFeatures(sessionId)
      .then((report) => {
        setFeatureReports((prev) => ({ ...prev, [id]: report }));
        return refreshRepository(id, sessionId);
      })
      .catch((err) =>
        setFeatureErrors((prev) => ({
          ...prev,
          [entryId]: err instanceof AuditApiError ? err.message : "Could not compute features.",
        }))
      )
      .finally(() => setFeatureBusy((prev) => ({ ...prev, [entryId]: undefined })));
  };

  const selectFeature = (id: UploadSlotId, entry: AnalysisRepositoryEntry, featureId: string) => {
    const sessionId = auditReports[id]!.session_id;
    setFeatureErrors((prev) => ({ ...prev, [entry.id]: undefined }));
    setFeatureBusy((prev) => ({ ...prev, [entry.id]: `select:${featureId}` }));
    selectRequiredFeature(sessionId, entry.id, featureId)
      .then((updated) => {
        updateEntry(id, updated);
        // Approved but not computed yet -> compute it now.
        if ((updated.required_features ?? []).some((f) => f.state === "not_computed")) {
          return computeRequiredFeatures(id, entry.id);
        }
        return refreshRepository(id, sessionId);
      })
      .catch((err) =>
        setFeatureErrors((prev) => ({
          ...prev,
          [entry.id]: err instanceof AuditApiError ? err.message : "Could not select that feature.",
        }))
      )
      .finally(() => setFeatureBusy((prev) => ({ ...prev, [entry.id]: prev[entry.id]?.startsWith("select:") ? undefined : prev[entry.id] })));
  };

  const runSuggest = (id: UploadSlotId) => {
    const sessionId = auditReports[id]!.session_id;
    setSuggestLoading((prev) => ({ ...prev, [id]: true }));
    setSuggestError((prev) => ({ ...prev, [id]: undefined }));
    suggestAnalysisEntries(sessionId)
      .then(() => refreshRepository(id, sessionId))
      .catch((err) =>
        setSuggestError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not reach the suggestion agent.",
        }))
      )
      .finally(() => setSuggestLoading((prev) => ({ ...prev, [id]: false })));
  };

  const acceptSuggestion = (id: UploadSlotId, entry: AnalysisRepositoryEntry) => {
    const sessionId = auditReports[id]!.session_id;
    setApplyingEntryId((prev) => ({ ...prev, [id]: entry.id }));
    acceptAnalysisEntry(sessionId, entry.id)
      .then(() => refreshRepository(id, sessionId))
      .catch((err) =>
        setRepoError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not add that analysis.",
        }))
      )
      .finally(() => setApplyingEntryId((prev) => ({ ...prev, [id]: undefined })));
  };

  // Rejects on failure so the Add Analysis form (a modal) can show the error
  // itself -- the page-level error line is hidden behind the modal.
  const addAnalysis = (id: UploadSlotId, analysis: AddCustomAnalysisBody): Promise<void> => {
    const sessionId = auditReports[id]!.session_id;
    setAddingAnalysis((prev) => ({ ...prev, [id]: true }));
    return addCustomAnalysis(sessionId, analysis)
      .then(() => refreshRepository(id, sessionId))
      .finally(() => setAddingAnalysis((prev) => ({ ...prev, [id]: false })));
  };

  // Guided drill-down chain. These reject so the modal can show the error
  // next to the control that failed; each refetches the repository so new and
  // stale levels appear. Confirming also navigates straight into the new
  // level, so its own suggestions (about drilling further from THIS level)
  // are what the PM sees next, not the parent's.
  const confirmChainDrilldown = (id: UploadSlotId, entryId: string, body: ConfirmDrilldownBody): Promise<void> => {
    const sessionId = auditReports[id]!.session_id;
    // Stay on the analysis being drilled and show its Selected Drill-downs tab, where
    // every level just created (one per value, when several were ticked) is listed.
    return confirmDrilldown(sessionId, entryId, body)
      .then(() => refreshRepository(id, sessionId))
      .then(() => setOpenSelectedSignal((n) => n + 1));
  };

  // Suggested drill-down paths. Accepting or rejecting refetches the repository so the
  // accepted levels show up under Selected Drill-downs (and the report) straight away.
  const decidePath = (id: UploadSlotId, pathId: string, accept: boolean, levels?: number[]) => {
    const sessionId = auditReports[id]!.session_id;
    const request = accept ? acceptDrilldownPath(sessionId, pathId, levels) : rejectDrilldownPath(sessionId, pathId);
    return request.then((path) => {
      // A level the PM skipped is kept (the next level builds on it) but left out of the report by default.
      const skipped = new Set(path.skipped_levels ?? []);
      const skippedIds = path.steps.filter((st) => skipped.has(st.level)).flatMap((st) => st.entries.map((e) => e.entry_id));
      if (skippedIds.length > 0) {
        setReportSelected((prev) => ({ ...prev, ...Object.fromEntries(skippedIds.map((eid) => [eid, false])) }));
      }
      return refreshRepository(id, sessionId).then(() => path);
    });
  };

  const refreshChainLevel = (id: UploadSlotId, entryId: string): Promise<void> => {
    const sessionId = auditReports[id]!.session_id;
    return refreshDrilldown(sessionId, entryId).then(() => refreshRepository(id, sessionId));
  };

  const proposeDrilldownsFor = (id: UploadSlotId, entryId: string, more: boolean) => {
    const sessionId = auditReports[id]!.session_id;
    return proposeDrilldowns(sessionId, entryId, more);
  };

  // Frontend-only: hide one drilldown from an entry's Selected list without
  // deleting it -- never sent to the backend.
  const dismissDrilldown = (entryId: string, id: string) => {
    setDismissedDrilldowns((prev) => {
      const current = new Set(prev[entryId] ?? []);
      current.add(id);
      return { ...prev, [entryId]: current };
    });
  };

  const runOverallAnalysis = (id: UploadSlotId) => {
    const sessionId = auditReports[id]!.session_id;
    setOverallLoading((prev) => ({ ...prev, [id]: true }));
    setOverallError((prev) => ({ ...prev, [id]: undefined }));
    fetchOverallAnalysis(sessionId)
      .then((report) => setOverallReports((prev) => ({ ...prev, [id]: report })))
      .catch((err) =>
        setOverallError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not reach the analysis agent.",
        }))
      )
      .finally(() => setOverallLoading((prev) => ({ ...prev, [id]: false })));
  };

  // Auto-run: every approved analysis that hasn't been computed yet starts
  // on its own -- predefined and planner entries on page load, custom and
  // accepted AI suggestions as soon as they're added. Capped at
  // MAX_CONCURRENT_RUNS because each run is several LLM calls.
  useEffect(() => {
    let slots = MAX_CONCURRENT_RUNS - Object.values(runningIds).filter(Boolean).length;
    for (const id of slotsReady) {
      for (const entry of repositories[id] ?? []) {
        if (slots <= 0) return;
        if (entry.status !== "approved" || entry.run_status !== "not_run") continue;
        // Blocked on required features: running would just return a 422.
        if (entry.dependencies_satisfied === false) continue;
        if (autoStarted.current.has(entry.id) || runningIds[entry.id]) continue;
        autoStarted.current.add(entry.id);
        runEntry(id, entry);
        slots -= 1;
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repositories, runningIds, slotsReady]);

  // Auto-summary: once no analysis in a slot is still waiting or running,
  // generate the summary -- and regenerate it whenever the set of finished
  // analyses changes (a new analysis ran, a drilldown was explored).
  useEffect(() => {
    for (const id of slotsReady) {
      const approved = (repositories[id] ?? []).filter((e) => e.status === "approved");
      const pending = approved.some(
        (e) => runningIds[e.id] || (e.run_status === "not_run" && !runFailures[e.id] && !isBlocked(e))
      );
      const done = approved.filter((e) => e.run_status === "done").map((e) => e.id).sort().join("|");
      if (pending || !done || overallLoading[id] || summarizedFor.current[id] === done) continue;
      summarizedFor.current[id] = done;
      runOverallAnalysis(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repositories, runningIds, runFailures, slotsReady, overallLoading]);

  // The conversation. The first ready file is the one it talks about.
  const primary = slotsReady[0];
  const noFiles = AUDITED_SLOTS.every((id) => !files[id]);
  const [log, setLog] = useStoredState<AnalysisLogEntry[]>("analysis.log", []);
  const [drafts, setDrafts] = useStoredState<Record<number, AnalysisDraftState>>("analysis.drafts", {});
  const [awaitingAnalysis, setAwaitingAnalysis] = useState(false);
  const say = (user: string, block: AnalysisLogEntry["block"], extra: Partial<AnalysisLogEntry> = {}) =>
    setLog((prev) => [...prev, { user, block, ...extra }]);

  const replies: StageReply[] = [];
  if (noFiles) {
    replies.push({ label: "Go to Configure", main: true, onClick: () => navigate("/upload") });
  } else if (auditedReady.length === 0) {
    replies.push({ label: "Back to Audit", main: true, onClick: () => navigate("/audit") });
  } else if (!primary) {
    replies.push({ label: "Go to Features", main: true, onClick: () => navigate("/features") });
  } else {
    replies.push({ label: "Continue to Report", main: true, onClick: () => navigate("/report") });
    replies.push({
      label: "Suggest more analyses",
      disabled: !!suggestLoading[primary],
      onClick: () => {
        say("Suggest more analyses", "suggest");
        runSuggest(primary);
      },
    });
    replies.push({
      label: "Add a custom analysis",
      onClick: () => {
        say("I want to add my own analysis", "custom");
        setAwaitingAnalysis(true);
      },
    });
  }

  // While the assistant waits for an analysis description, the next message is that description.
  const takeMessage = (text: string): boolean => {
    if (!awaitingAnalysis || !primary) return false;
    const id = Date.now();
    const name = text
      .split(/\s+/)
      .slice(0, 6)
      .join(" ")
      .replace(/^./, (c) => c.toUpperCase());
    setAwaitingAnalysis(false);
    say(text, "draft", { draftId: id });
    setDrafts((prev) => ({ ...prev, [id]: { request: { name, description: text }, state: "working" } }));
    draftAnalysis(auditReports[primary]!.session_id, { name, description: text })
      .then((draft) => setDrafts((prev) => ({ ...prev, [id]: { request: { name, description: text }, state: "ready", draft } })))
      .catch((err) =>
        setDrafts((prev) => ({
          ...prev,
          [id]: { request: { name, description: text }, state: "failed", error: err instanceof AuditApiError ? err.message : "I could not work that out." },
        }))
      );
    return true;
  };
  useStageChrome({ replies, onSend: takeMessage });

  const addDraft = (draftId: number) => {
    const d = drafts[draftId];
    if (!d?.draft || !primary) return;
    const draft = d.draft;
    const options = [draft.chart, ...draft.chart.alternatives];
    addAnalysis(primary, {
      name: d.request.name,
      description: d.request.description,
      calculation_intent: d.request.description,
      input_columns: [...draft.group_by],
      formula: draft.formula,
      template: draft.template,
      chart_type: draft.chart.chart_type,
      chart_reason: draft.chart.reason,
      chart_alternatives: options.filter((c) => c.chart_type !== draft.chart.chart_type),
      filters: draft.filters.map((f) => ({ column: f.column, reason: f.reason })),
    }).then(() => setDrafts((prev) => ({ ...prev, [draftId]: { ...prev[draftId], state: "added" } })));
  };

  const repo = primary ? repositories[primary] ?? [] : [];
  const visibleEntries = repo.filter((e) => e.status === "approved");
  const topLevelEntries = visibleEntries.filter((e) => !e.parent_id);
  const blockedCount = slotsReady.reduce((n, sid) => n + (repositories[sid] ?? []).filter(isBlocked).length, 0);
  const waitingForAnalyses = visibleEntries.some((e) => runningIds[e.id] || (e.run_status === "not_run" && !runFailures[e.id] && !isBlocked(e)));

  return (
    <>
      {noFiles && (
        <ChatMessage>
          <p>There is no audited data yet. Set up a program in Configure first, and I will run the analyses from your plan.</p>
        </ChatMessage>
      )}
      {!noFiles && auditedReady.length === 0 && (
        <ChatMessage>
          <p>I can run the analyses once the data audit is finished. Go back and settle the open decisions, then come here.</p>
        </ChatMessage>
      )}
      {!noFiles && auditedReady.length > 0 && !primary && (
        <ChatMessage>
          {Object.values(featureCheckLoading).some(Boolean) ? (
            <ThinkingLoader variant="inline" messages={["Checking whether the features have been built…"]} />
          ) : (
            <p>No features have been built yet. An analysis can group by built columns such as time above 8 °C, so finish the Features step first.</p>
          )}
        </ChatMessage>
      )}

      {primary && (
        <AnalysisChat
          rows={featureReports[primary]?.row_count ?? 0}
          columns={featureReports[primary]?.column_count ?? 0}
          topLevel={topLevelEntries}
          drilldownCount={visibleEntries.length - topLevelEntries.length}
          running={topLevelEntries.filter((e) => runningIds[e.id]).length}
          blocked={blockedCount}
          repoLoading={!!repoLoading[primary] && !repositories[primary]}
          repoError={repoError[primary]}
          defsLoading={defsLoading}
          defsError={defsError}
          overall={{
            report: overallReports[primary],
            loading: !!overallLoading[primary],
            error: overallError[primary],
            waiting: waitingForAnalyses,
            onRetry: () => runOverallAnalysis(primary),
          }}
          renderCard={(entry) => (
            <AnalysisCard
              entry={entry}
              running={!!runningIds[entry.id]}
              runFailure={runFailures[entry.id]}
              onRun={() => runEntry(primary, entry)}
              onExpand={() => setOpenEntry({ slotId: primary, entryId: entry.id })}
              levels={buildLevelTree(visibleEntries, entry.id)}
              onOpenLevel={(entryId) => setOpenEntry({ slotId: primary, entryId })}
              onSelectFeature={(featureId) => selectFeature(primary, entry, featureId)}
              onComputeFeatures={() => {
                setFeatureErrors((prev) => ({ ...prev, [entry.id]: undefined }));
                computeRequiredFeatures(primary, entry.id);
              }}
              featureBusy={featureBusy[entry.id]}
              featureError={featureErrors[entry.id]}
            />
          )}
          log={log}
          drafts={drafts}
          pendingSuggestions={repo.filter((e) => e.source === "ai_suggested" && e.status === "pending")}
          suggestLoading={!!suggestLoading[primary]}
          suggestError={suggestError[primary]}
          applyingEntryId={applyingEntryId[primary]}
          onAcceptSuggestion={(entry) => acceptSuggestion(primary, entry)}
          onAddDraft={addDraft}
          adding={!!addingAnalysis[primary]}
        />
      )}

      {openEntry &&
        (() => {
          const openRepo = repositories[openEntry.slotId] ?? [];
          const openEntryData = openRepo.find((e) => e.id === openEntry.entryId);
          if (!openEntryData) return null;
          const parentName = openEntryData.parent_id
            ? openRepo.find((e) => e.id === openEntryData.parent_id)?.name
            : undefined;
          return (
            <AnalysisDetailModal
              entry={openEntryData}
              parentName={parentName}
              dismissedIds={dismissedDrilldowns[openEntryData.id] ?? EMPTY_ID_SET}
              onDismiss={(id) => dismissDrilldown(openEntryData.id, id)}
              running={!!runningIds[openEntryData.id]}
              onRetry={() => runEntry(openEntry.slotId, openEntryData)}
              onClose={() => setOpenEntry(null)}
              onOpenChild={(childEntryId) => setOpenEntry({ slotId: openEntry.slotId, entryId: childEntryId })}
              trail={ancestorTrail(openRepo, openEntryData)}
              childLevels={buildLevelTree(openRepo, openEntryData.id)}
              onFetchDrilldownOptions={() => fetchDrilldownOptions(auditReports[openEntry.slotId]!.session_id, openEntry.entryId)}
              onProposeDrilldowns={(more) => proposeDrilldownsFor(openEntry.slotId, openEntry.entryId, more)}
              onConfirmDrilldown={(body) => confirmChainDrilldown(openEntry.slotId, openEntry.entryId, body)}
              onRefreshLevel={() => refreshChainLevel(openEntry.slotId, openEntry.entryId)}
              openSelectedSignal={openSelectedSignal}
              onFetchPaths={() => fetchDrilldownPaths(auditReports[openEntry.slotId]!.session_id, openEntry.entryId)}
              onSuggestPath={() => suggestDrilldownPath(auditReports[openEntry.slotId]!.session_id, openEntry.entryId)}
              onAcceptPath={(pathId, levels) => decidePath(openEntry.slotId, pathId, true, levels)}
              onRejectPath={(pathId) => decidePath(openEntry.slotId, pathId, false)}
              onApplyFilters={(filters: AnalysisFilterSelections) =>
                filterAnalysisEntry(auditReports[openEntry.slotId]!.session_id, openEntry.entryId, filters)
              }
            />
          );
        })()}
    </>
  );
}
