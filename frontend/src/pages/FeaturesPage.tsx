import { useEffect, useState } from "react";
import { useStoredState } from "../state/sessionStore";
import { useNavigate } from "react-router-dom";
import ChatMessage from "../components/ChatMessage";
import FeaturesChat from "../components/FeaturesChat";
import type { FeaturesLogEntry, KpiDraftState } from "../components/FeaturesChat";
import FeatureDetailModal from "../components/FeatureDetailModal";
import { useStageChrome } from "../context/stageChrome";
import type { StageReply } from "../context/stageChrome";
import {
  acceptFeatureEntry,
  addCustomFeature,
  applyFeatures,
  draftCustomFeature,
  downloadCleansedFile,
  fetchFeatureRepository,
  fetchPreview,
  suggestFeatureEntries,
  uploadFeatureDefinitions,
  AuditApiError,
  type DataPreview,
  type FeatureReport,
  type AddCustomFeatureBody,
  type FeatureRepositoryEntry,
} from "../api/audit";
import { AUDITED_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { AuditReportsState, FilesState } from "../App";
import "./FeaturesPage.css";

interface FeaturesPageProps {
  files: FilesState;
  auditReports: AuditReportsState;
}

type FeatureReportsState = Partial<Record<UploadSlotId, FeatureReport>>;
type LoadingState = Partial<Record<UploadSlotId, boolean>>;
type ErrorsState = Partial<Record<UploadSlotId, string>>;
type PreviewsState = Partial<Record<UploadSlotId, DataPreview>>;
type RepositoryState = Partial<Record<UploadSlotId, FeatureRepositoryEntry[]>>;
type BusyIdState = Partial<Record<UploadSlotId, string>>;

export default function FeaturesPage({ files, auditReports }: FeaturesPageProps) {
  const navigate = useNavigate();
  const [reports, setReports] = useStoredState<FeatureReportsState>("features.reports", {});
  const [loading, setLoading] = useStoredState<LoadingState>("features.loading", {});
  // Errors stay page-local on purpose: a failed compute is retried on the next visit.
  const [errors, setErrors] = useState<ErrorsState>({});
  const [previews, setPreviews] = useStoredState<PreviewsState>("features.previews", {});

  const [repositories, setRepositories] = useStoredState<RepositoryState>("features.repositories", {});
  const [suggestLoading, setSuggestLoading] = useStoredState<LoadingState>("features.suggestLoading", {});
  const [suggestError, setSuggestError] = useState<ErrorsState>({});
  const [applyingEntryId, setApplyingEntryId] = useStoredState<BusyIdState>("features.applyingEntryId", {});
  const [addingKpi, setAddingKpi] = useStoredState<LoadingState>("features.addingKpi", {});

  const [defsError, setDefsError] = useStoredState<string | null>("features.defsError", null);
  const [defsLoading, setDefsLoading] = useStoredState("features.defsLoading", false);
  // True once we've either attempted the Customer KPI Profile upload (success
  // or failure) or confirmed there isn't one -- gates the first compute so
  // predefined features are included when they're available, without ever
  // requiring the file to exist.
  const [defsAttempted, setDefsAttempted] = useStoredState("features.defsAttempted", false);

  const [openFeature, setOpenFeature] = useState<{ slotId: UploadSlotId; featureId: string } | null>(null);

  const slotsReady = AUDITED_SLOTS.filter((id) => files[id] && auditReports[id]?.status === "reviewed");
  const hasKpiFile = !!files.customerKpis;

  // Step 1 (optional): if a Customer KPI Profile was uploaded, parse it so
  // its features can join the repository as "predefined" entries. Not
  // required -- planner-approved, custom, and AI-suggested features work
  // with or without this file.
  useEffect(() => {
    if (defsAttempted || defsLoading) return;
    if (!hasKpiFile) {
      setDefsAttempted(true);
      return;
    }
    setDefsLoading(true);
    uploadFeatureDefinitions(files.customerKpis!)
      .catch((err) => setDefsError(err instanceof AuditApiError ? err.message : "Could not upload the Customer KPI Profile."))
      .finally(() => {
        setDefsLoading(false);
        setDefsAttempted(true);
      });
  }, [hasKpiFile, files.customerKpis, defsAttempted, defsLoading]);

  const refreshRepository = (id: UploadSlotId, sessionId: string) =>
    fetchFeatureRepository(sessionId).then((repo) => setRepositories((prev) => ({ ...prev, [id]: repo.entries })));

  const computeAndRefresh = (id: UploadSlotId) => {
    const sessionId = auditReports[id]!.session_id;
    setLoading((prev) => ({ ...prev, [id]: true }));
    setErrors((prev) => ({ ...prev, [id]: undefined }));
    return applyFeatures(sessionId)
      .then((report) => {
        setReports((prev) => ({ ...prev, [id]: report }));
        return refreshRepository(id, sessionId);
      })
      .catch((err) =>
        setErrors((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not compute features.",
        }))
      )
      .finally(() => setLoading((prev) => ({ ...prev, [id]: false })));
  };

  // Step 2: once the KPI Profile upload has settled (or there wasn't one),
  // compute features for each audited slot -- predefined contributes zero
  // entries if no file was uploaded, planner/custom/AI-suggested work regardless.
  useEffect(() => {
    if (!defsAttempted) return;
    for (const id of slotsReady) {
      if (reports[id] || loading[id] || errors[id]) continue;
      computeAndRefresh(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defsAttempted, files, auditReports]);

  const runSuggest = (id: UploadSlotId) => {
    const sessionId = auditReports[id]!.session_id;
    setSuggestLoading((prev) => ({ ...prev, [id]: true }));
    setSuggestError((prev) => ({ ...prev, [id]: undefined }));
    suggestFeatureEntries(sessionId)
      .then(() => refreshRepository(id, sessionId))
      .catch((err) =>
        setSuggestError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not reach the suggestion agent.",
        }))
      )
      .finally(() => setSuggestLoading((prev) => ({ ...prev, [id]: false })));
  };

  const acceptSuggestion = (id: UploadSlotId, entry: FeatureRepositoryEntry) => {
    const sessionId = auditReports[id]!.session_id;
    setApplyingEntryId((prev) => ({ ...prev, [id]: entry.id }));
    acceptFeatureEntry(sessionId, entry.id)
      .then(() => computeAndRefresh(id))
      .catch((err) =>
        setErrors((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not add that feature.",
        }))
      )
      .finally(() => setApplyingEntryId((prev) => ({ ...prev, [id]: undefined })));
  };

  // Rejects on failure so the Add KPI form (a modal) can show the error
  // itself -- the page-level error line is hidden behind the modal.
  const addCustomKpi = (id: UploadSlotId, kpi: AddCustomFeatureBody): Promise<void> => {
    const sessionId = auditReports[id]!.session_id;
    setAddingKpi((prev) => ({ ...prev, [id]: true }));
    return addCustomFeature(sessionId, kpi)
      .then(() => computeAndRefresh(id))
      .finally(() => setAddingKpi((prev) => ({ ...prev, [id]: false })));
  };

  // The conversation. The first ready file is the one it talks about.
  const primary = slotsReady[0];
  const [log, setLog] = useStoredState<FeaturesLogEntry[]>("features.log", []);
  const [drafts, setDrafts] = useStoredState<Record<number, KpiDraftState>>("features.drafts", {});
  const [awaitingKpi, setAwaitingKpi] = useState(false);
  const said = (block: FeaturesLogEntry["block"]) => log.some((e) => e.block === block);
  const say = (user: string, block: FeaturesLogEntry["block"], extra: Partial<FeaturesLogEntry> = {}) =>
    setLog((prev) => [...prev, { user, block, ...extra }]);

  const replies: StageReply[] = [];
  if (AUDITED_SLOTS.every((id) => !files[id])) {
    replies.push({ label: "Go to Configure", main: true, onClick: () => navigate("/upload") });
  } else if (!primary) {
    replies.push({ label: "Back to Audit", main: true, onClick: () => navigate("/audit") });
  } else {
    replies.push({ label: "Continue to Analysis", main: true, onClick: () => navigate("/analysis") });
    replies.push({
      label: "Suggest more features",
      disabled: !!suggestLoading[primary],
      onClick: () => {
        say("Suggest more features", "suggest");
        runSuggest(primary);
      },
    });
    replies.push({
      label: "Add a custom KPI",
      onClick: () => {
        say("I want to add my own KPI", "custom");
        setAwaitingKpi(true);
      },
    });
    if (!said("preview")) {
      replies.push({
        label: "Show the data",
        onClick: () => {
          say("Show me the data", "preview");
          if (!previews[primary]) fetchPreview(auditReports[primary]!.session_id, 30).then((preview) => setPreviews((prev) => ({ ...prev, [primary]: preview })));
        },
      });
    }
    replies.push({
      label: "Download the engineered file",
      onClick: () => {
        say("Download the engineered file", "download");
        downloadCleansedFile(auditReports[primary]!.session_id).catch((err) => window.alert(err instanceof Error ? err.message : "Download failed."));
      },
    });
  }

  // While the assistant waits for a KPI description, the next message is that description.
  const takeMessage = (text: string): boolean => {
    if (!awaitingKpi || !primary) return false;
    const id = Date.now();
    const name = text
      .split(/\s+/)
      .slice(0, 5)
      .join(" ")
      .replace(/^./, (c) => c.toUpperCase());
    setAwaitingKpi(false);
    say(text, "draft", { draftId: id });
    setDrafts((prev) => ({ ...prev, [id]: { request: { name, description: text }, state: "working" } }));
    draftCustomFeature(auditReports[primary]!.session_id, { name, description: text })
      .then((draft) => setDrafts((prev) => ({ ...prev, [id]: { request: { name, description: text }, state: "ready", draft } })))
      .catch((err) =>
        setDrafts((prev) => ({
          ...prev,
          [id]: { request: { name, description: text }, state: "failed", error: err instanceof AuditApiError ? err.message : "I could not write a formula for that." },
        }))
      );
    return true;
  };
  useStageChrome({ replies, onSend: takeMessage });

  const addDraft = (draftId: number) => {
    const d = drafts[draftId];
    if (!d?.draft || !primary) return;
    addCustomKpi(primary, {
      name: d.request.name,
      description: d.request.description,
      calculation_intent: d.request.description,
      input_columns: d.draft.columns_used,
      formula: d.draft.formula,
      draft_token: d.draft.draft_token,
    }).then(() => setDrafts((prev) => ({ ...prev, [draftId]: { ...prev[draftId], state: "added" } })));
  };

  const openData = openFeature ? reports[openFeature.slotId]?.features.find((f) => f.id === openFeature.featureId) : undefined;

  return (
    <>
      {AUDITED_SLOTS.every((id) => !files[id]) && (
        <ChatMessage>
          <p>There is no audited data yet. Set up a program in Configure first, and I will build features from it.</p>
        </ChatMessage>
      )}
      {!AUDITED_SLOTS.every((id) => !files[id]) && !primary && (
        <ChatMessage>
          <p>I can build features once the data audit is finished. Go back and settle the open decisions, then come here.</p>
        </ChatMessage>
      )}

      {primary && (
        <FeaturesChat
          report={reports[primary]}
          loading={!!loading[primary]}
          error={errors[primary]}
          defsLoading={defsLoading}
          defsError={defsError}
          requiredFor={(featureId) => (repositories[primary] ?? []).find((e) => e.id === featureId)?.required_for_analysis ?? []}
          log={log}
          drafts={drafts}
          pendingSuggestions={(repositories[primary] ?? []).filter((e) => e.source === "ai_suggested" && e.status === "pending")}
          suggestLoading={!!suggestLoading[primary]}
          suggestError={suggestError[primary]}
          applyingEntryId={applyingEntryId[primary]}
          preview={previews[primary]}
          onOpenFeature={(featureId) => setOpenFeature({ slotId: primary, featureId })}
          onAcceptSuggestion={(entry) => acceptSuggestion(primary, entry)}
          onAddDraft={addDraft}
          adding={!!addingKpi[primary]}
        />
      )}

      {openData && <FeatureDetailModal feature={openData} onClose={() => setOpenFeature(null)} />}
    </>
  );
}
