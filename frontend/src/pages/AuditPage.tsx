import ThinkingLoader from "../components/ThinkingLoader";
import { LOADING } from "../utils/loadingMessages";
import { useContext, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AuditReport from "../components/AuditReport";
import type { Tab } from "../components/AuditReport";
import AuditChat from "../components/AuditChat";
import type { AuditBlock, AuditLogEntry } from "../components/AuditChat";
import ChatMessage from "../components/ChatMessage";
import TripInspectModal from "../components/TripInspectModal";
import type { SwpTimesResult } from "../api/swp";
import { DataSourceContext } from "../context/plannerSkipped";
import { IconDownload } from "../components/icons";
import { downloadCleansedFile } from "../api/audit";
import { resetDownstreamState, useStoredState } from "../state/sessionStore";
import { useStageChrome } from "../context/stageChrome";
import type { StageReply } from "../context/stageChrome";
import { AUDITED_SLOTS, UPLOAD_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { AuditErrorsState, AuditLoadingState, AuditReportsState, FilesState, ResolvingState, UploadedSessionIdsState } from "../App";
import "./AuditPage.css";

// SensiWatch alone gets the outlier-checks-first wizard (see
// OutlierCorrectionStep) -- ColdStream keeps today's tabbed layout, run
// immediately on upload like every other audited slot.
const WIZARD_SLOT: UploadSlotId = "sensiwatch";

interface AuditPageProps {
  files: FilesState;
  uploadedSessionIds: UploadedSessionIdsState;
  auditReports: AuditReportsState;
  auditLoading: AuditLoadingState;
  auditErrors: AuditErrorsState;
  resolvingIssueId: ResolvingState;
  onRunAudit: (id: UploadSlotId) => void;
  onResolveIssue: (id: UploadSlotId, issueId: string, decisionId: string, selectedItems?: string[]) => Promise<void>;
  onRevertIssue: (id: UploadSlotId, issueId: string) => void;
  onReuploadSensiwatch: (file: File) => Promise<string | null>;
  reuploadingSensiwatch: boolean;
  reuploadError: string | null;
  /** A trip's departure / arrival was changed here (CET, UTC given for the Trips page's own edit list). */
  onTripTimesEdited: (tripKey: string, result: SwpTimesResult) => void;
}

export default function AuditPage({
  files,
  uploadedSessionIds,
  auditReports,
  auditLoading,
  auditErrors,
  resolvingIssueId,
  onRunAudit,
  onResolveIssue,
  onRevertIssue,
  onReuploadSensiwatch,
  reuploadingSensiwatch,
  reuploadError,
  onTripTimesEdited,
}: AuditPageProps) {
  const navigate = useNavigate();
  const apiSource = useContext(DataSourceContext) === "api";
  // The trip open in the Inspect window (by SWP key from the trips table, by Trip ID from the outlier tables), and
  // a counter that goes up whenever a trip's times were changed so what is built on them is read again.
  const [inspect, setInspect] = useState<{ key?: string; number?: string } | null>(null);
  const [dataVersion, setDataVersion] = useState(0);
  const handleTimesSaved = (tripKey: string, result: SwpTimesResult) => {
    resetDownstreamState(); // features, analyses and the report were built on the old times
    setDataVersion((v) => v + 1);
    onTripTimesEdited(tripKey, result);
  };
  // Held in the shared store (not local state) so leaving this page and coming
  // back keeps the PM where they were instead of replaying the outlier step.
  const [activeTabs, setActiveTabs] = useStoredState<Partial<Record<UploadSlotId, Tab>>>("audit.activeTabs", {});

  // The SensiWatch card shows three persistent tabs -- "Outliers Check" (duration/
  // temperature outlier review), "Standard Check" (the usual Standard Checks /
  // Human Decision flow), and "Summary" (what changed overall). Standard Check and
  // Summary stay disabled until the outlier review has been resolved or explicitly
  // skipped for the CURRENT session. The unlock is remembered against that session
  // id, so a new or re-uploaded file (new id) starts back at the outlier step.
  const [, setWizardActiveTab] = useStoredState<"outliers" | "standard" | "summary" | null>(
    "audit.wizardTab",
    null
  );
  const [unlockedForSession, setUnlockedForSession] = useStoredState<string | null>("audit.sensiwatchUnlockedFor", null);
  const sensiwatchSessionId = uploadedSessionIds[WIZARD_SLOT];
  const sensiwatchStandardUnlocked = !!sensiwatchSessionId && unlockedForSession === sensiwatchSessionId;

  // An audit runs once per upload: never when a report already exists (it
  // holds the PM's resolved decisions), one is in flight, or it already failed.
  const needsAudit = (id: UploadSlotId) =>
    !!uploadedSessionIds[id] && !auditReports[id] && !auditLoading[id] && !auditErrors[id];

  useEffect(() => {
    for (const id of AUDITED_SLOTS) {
      // SensiWatch's audit is deferred until the outlier step is passed (skipped or corrected file uploaded).
      if (id === WIZARD_SLOT && !sensiwatchStandardUnlocked) continue;
      if (needsAudit(id)) onRunAudit(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uploadedSessionIds, auditReports, auditLoading, auditErrors, sensiwatchStandardUnlocked]);

  const advanceSensiwatchToStandard = (sessionId: string | null | undefined = sensiwatchSessionId) => {
    setUnlockedForSession(sessionId ?? null);
    setWizardActiveTab("standard");
  };

  // The corrected file replaces the original: skip a second outlier review and go straight to
  // the Standard Check on the new session.
  const handleCorrectedFile = async (file: File) => {
    const newSessionId = await onReuploadSensiwatch(file);
    if (newSessionId) advanceSensiwatchToStandard(newSessionId);
  };

  const auditedSlotsWithFiles = AUDITED_SLOTS.filter((id) => uploadedSessionIds[id]);
  const hasAnyFile = UPLOAD_SLOTS.some((s) => files[s.id]);

  const anyLoading = auditedSlotsWithFiles.some((id) => auditLoading[id]);
  const anyPending = auditedSlotsWithFiles.some((id) => auditReports[id]?.status === "pending_review");
  const canContinue =
    !!uploadedSessionIds.sensiwatch && sensiwatchStandardUnlocked && !anyLoading && !anyPending;

  // The conversation: what the PM has said so far, and the quick replies on offer at this moment.
  const report = auditReports[WIZARD_SLOT];
  const hasWizard = !!sensiwatchSessionId;
  const [log, setLog] = useStoredState<AuditLogEntry[]>("audit.log", []);
  const said = (block: AuditBlock) => log.some((e) => e.block === block);
  const say = (user: string, block: AuditBlock) => setLog((prev) => [...prev, { user, block }]);

  const replies: StageReply[] = [];
  if (!hasAnyFile) {
    replies.push({ label: "Go to Configure", main: true, onClick: () => navigate("/upload") });
  } else if (hasWizard) {
    if (!sensiwatchStandardUnlocked) {
      replies.push({
        label: "Keep them as they are",
        main: true,
        onClick: () => {
          say("Keep them as they are", "keep");
          advanceSensiwatchToStandard();
        },
      });
      if (!said("review")) replies.push({ label: "Review the flagged trips", onClick: () => say("Let me review the flagged trips", "review") });
    } else {
      if (auditErrors[WIZARD_SLOT] && !report) replies.push({ label: "Try again", main: true, onClick: () => onRunAudit(WIZARD_SLOT) });
      replies.push({ label: "Continue to Features", main: true, disabled: !canContinue, onClick: () => navigate("/features") });
      if (report && !said("summary")) replies.push({ label: "What changed?", onClick: () => say("What changed in my data?", "summary") });
      if (report) {
        replies.push({
          label: "Download the cleaned data",
          onClick: () => {
            say("Download the cleaned data", "download");
            downloadCleansedFile(report.session_id).catch((err) => window.alert(err instanceof Error ? err.message : "Download failed."));
          },
        });
      }
    }
    if (apiSource && !said("trips")) replies.push({ label: "Show all trips", onClick: () => say("Show me all the trips", "trips") });
  }
  useStageChrome({ replies });

  const otherSlots = auditedSlotsWithFiles.filter((id) => id !== WIZARD_SLOT);

  return (
    <>
      {!hasAnyFile && (
        <ChatMessage>
          <p>No files have been uploaded yet. Set up a program in Configure first, and I will check it here.</p>
        </ChatMessage>
      )}

      {hasWizard && (
        <AuditChat
          sessionId={sensiwatchSessionId!}
          apiSource={apiSource}
          dataVersion={dataVersion}
          unlocked={sensiwatchStandardUnlocked}
          report={report}
          loading={!!auditLoading[WIZARD_SLOT]}
          error={auditErrors[WIZARD_SLOT]}
          resolvingIssueId={resolvingIssueId[WIZARD_SLOT] ?? null}
          log={log}
          onUnlock={() => advanceSensiwatchToStandard()}
          onResolve={(issueId, decisionId, selectedItems) => onResolveIssue(WIZARD_SLOT, issueId, decisionId, selectedItems)}
          onRevert={(issueId) => onRevertIssue(WIZARD_SLOT, issueId)}
          onCorrectedFile={handleCorrectedFile}
          reuploading={reuploadingSensiwatch}
          reuploadError={reuploadError}
          onInspectKey={(key) => setInspect({ key })}
          onInspectNumber={(number) => setInspect({ number })}
          onTimesSaved={handleTimesSaved}
          canContinue={canContinue}
        />
      )}

      {otherSlots.map((id) => {
        const slot = UPLOAD_SLOTS.find((s) => s.id === id)!;
        const slotReport = auditReports[id];
        return (
          <ChatMessage key={id}>
            <p>Your {slot.title} was checked too.</p>
            <div className="chat-card">
              <div className="chat-card__head">{slot.title}</div>
              <div className="chat-card__body">
                {auditLoading[id] && <ThinkingLoader messages={LOADING.audit} hint="Data quality checks are running on this file." intervalMs={3500} showElapsed />}
                {auditErrors[id] && <p className="audit-page__audit-error">{auditErrors[id]}</p>}
                {slotReport && (
                  <>
                    <AuditReport
                      report={slotReport}
                      onResolve={(issueId, decisionId, selectedItems) => onResolveIssue(id, issueId, decisionId, selectedItems)}
                      onRevert={(issueId) => onRevertIssue(id, issueId)}
                      resolvingIssueId={resolvingIssueId[id] ?? null}
                      activeTab={activeTabs[id] ?? "quality"}
                      onTabChange={(tab) => setActiveTabs((prev) => ({ ...prev, [id]: tab }))}
                    />
                    <a
                      className="audit-page__download-link"
                      href="#"
                      onClick={(e) => {
                        e.preventDefault();
                        downloadCleansedFile(slotReport.session_id).catch((err) => window.alert(err instanceof Error ? err.message : "Download failed."));
                      }}
                    >
                      <IconDownload />
                      Download cleansed file
                    </a>
                  </>
                )}
              </div>
            </div>
          </ChatMessage>
        );
      })}

      {inspect && sensiwatchSessionId && (
        <TripInspectModal
          sessionId={sensiwatchSessionId}
          tripKey={inspect.key}
          tripNumber={inspect.number}
          dataVersion={dataVersion}
          onClose={() => setInspect(null)}
          onTimesSaved={handleTimesSaved}
        />
      )}
    </>
  );
}
