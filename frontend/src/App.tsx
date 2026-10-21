import { DataSourceContext, PlannerSkippedContext, hasBrief } from "./context/plannerSkipped";
import type { DataSource } from "./context/plannerSkipped";
import { useRef, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell";
import WelcomePage from "./pages/WelcomePage";
import UploadPage from "./pages/UploadPage";
import AuditPage from "./pages/AuditPage";
import FeaturesPage from "./pages/FeaturesPage";
import AnalysisPage from "./pages/AnalysisPage";
import ReportPage from "./pages/ReportPage";
import { AuditApiError, resolveIssue, reuploadCorrected, revertIssue, runAudit } from "./api/audit";
import type { AuditReport as AuditReportData } from "./api/audit";
import { isAudited } from "./constants/uploadSlots";
import type { UploadSlotId } from "./types/upload";
import { resetAllState, resetDownstreamState } from "./state/sessionStore";
import { EMPTY_BRIEF } from "./components/ClientBriefInput";
import type { BriefState } from "./components/ClientBriefInput";
import type { SwpTimesResult, SwpTripsResponse, TripEdits } from "./api/swp";
import { EMPTY_SWP_CONFIG } from "./utils/swpTrips";
import type { SwpConfigState } from "./utils/swpTrips";

export type FilesState = Record<UploadSlotId, File | null>;
export type UploadedSessionIdsState = Partial<Record<UploadSlotId, string>>;
export type AuditReportsState = Partial<Record<UploadSlotId, AuditReportData>>;
export type AuditLoadingState = Partial<Record<UploadSlotId, boolean>>;
export type AuditErrorsState = Partial<Record<UploadSlotId, string>>;
export type ResolvingState = Partial<Record<UploadSlotId, string>>;
export type { BriefState };

export type { SwpConfigState };

const EMPTY_FILES: FilesState = {
  sensiwatch: null,
  coldstream: null,
  customerKpis: null,
  analysisProfile: null,
};

function App() {
  const [files, setFiles] = useState<FilesState>(EMPTY_FILES);
  const [brief, setBrief] = useState<BriefState>(EMPTY_BRIEF);
  const [dataSource, setDataSource] = useState<DataSource>("api");
  const [swpConfig, setSwpConfig] = useState<SwpConfigState>(EMPTY_SWP_CONFIG);
  // The program's trip list (fetched on the Configure page) and the changes made to trips in the app.
  const [swpTrips, setSwpTrips] = useState<SwpTripsResponse | null>(null);
  const [tripEdits, setTripEdits] = useState<TripEdits>({});
  const [uploadedSessionIds, setUploadedSessionIds] = useState<UploadedSessionIdsState>({});
  const [plannerSessionId, setPlannerSessionId] = useState<string | null>(null);
  // The brief text the current sessions were created with: coming back to Upload with the same files
  // and the same brief continues with those sessions instead of uploading (and planning) all over again.
  const [uploadedBriefSignature, setUploadedBriefSignature] = useState<string | null>(null);
  const [auditReports, setAuditReports] = useState<AuditReportsState>({});
  const [auditLoading, setAuditLoading] = useState<AuditLoadingState>({});
  const [auditErrors, setAuditErrors] = useState<AuditErrorsState>({});
  const [resolvingIssueId, setResolvingIssueId] = useState<ResolvingState>({});
  const [reuploadingSensiwatch, setReuploadingSensiwatch] = useState(false);
  const [reuploadError, setReuploadError] = useState<string | null>(null);

  const plannerSkipped = !hasBrief(brief);

  // Always-current session ids, so an async audit/resolve/revert that finishes
  // after its file was replaced or removed can tell its result is stale and drop it.
  const sessionIdsRef = useRef<UploadedSessionIdsState>({});
  sessionIdsRef.current = uploadedSessionIds;

  // Files were uploaded (the other way to bring data in): one session per audited file.
  const handleUploadComplete = (sessionIds: UploadedSessionIdsState, briefSignature: string) => {
    resetAllState();
    setUploadedBriefSignature(briefSignature);
    setUploadedSessionIds(sessionIds);
    setPlannerSessionId(sessionIds.sensiwatch ?? null);
  };

  // Switching between API and upload: whatever was loaded the other way is dropped (brief, profiles and
  // the API configuration stay).
  const handleSourceChange = (source: DataSource) => {
    if (source === dataSource) return;
    resetAllState();
    setDataSource(source);
    setFiles((prev) => ({ ...prev, sensiwatch: null, coldstream: null }));
    setUploadedSessionIds({});
    setUploadedBriefSignature(null);
    setPlannerSessionId(null);
    setAuditReports({});
    setAuditErrors({});
    setAuditLoading({});
    setResolvingIssueId({});
  };

  // The trips were loaded from the SWP API into one session. `label` is a stand-in "file" that only
  // carries the source's name for the pages that show it.
  const handleLoadComplete = (sessionId: string, label: File, signature: string) => {
    resetAllState();
    setFiles((prev) => ({ ...prev, sensiwatch: label }));
    setUploadedBriefSignature(signature);
    setUploadedSessionIds({ sensiwatch: sessionId });
    setPlannerSessionId(sessionId);
    setAuditReports({});
    setAuditErrors({});
    setAuditLoading({});
    setResolvingIssueId({});
  };

  const handleRunAudit = async (id: UploadSlotId) => {
    const sessionId = uploadedSessionIds[id];
    if (!sessionId) return;
    setAuditLoading((prev) => ({ ...prev, [id]: true }));
    setAuditErrors((prev) => ({ ...prev, [id]: undefined }));
    try {
      const report = await runAudit(sessionId);
      if (sessionIdsRef.current[id] !== sessionId) return;
      setAuditReports((prev) => ({ ...prev, [id]: report }));
    } catch (err) {
      if (sessionIdsRef.current[id] !== sessionId) return;
      setAuditErrors((prev) => ({
        ...prev,
        [id]: err instanceof AuditApiError ? err.message : "Could not run the data audit. Is the backend running?",
      }));
    } finally {
      setAuditLoading((prev) => ({ ...prev, [id]: false }));
    }
  };

  const handleSelect = (id: UploadSlotId, file: File) => {
    setFiles((prev) => ({ ...prev, [id]: file }));
    if (isAudited(id)) {
      resetAllState();
      setUploadedSessionIds((prev) => ({ ...prev, [id]: undefined }));
      setAuditReports((prev) => ({ ...prev, [id]: undefined }));
      setAuditErrors((prev) => ({ ...prev, [id]: undefined }));
      setAuditLoading((prev) => ({ ...prev, [id]: false }));
      setResolvingIssueId((prev) => ({ ...prev, [id]: undefined }));
    }
  };

  const handleRemove = (id: UploadSlotId) => {
    resetAllState();
    setFiles((prev) => ({ ...prev, [id]: null }));
    setUploadedSessionIds((prev) => ({ ...prev, [id]: undefined }));
    setAuditReports((prev) => ({ ...prev, [id]: undefined }));
    setAuditErrors((prev) => ({ ...prev, [id]: undefined }));
    setAuditLoading((prev) => ({ ...prev, [id]: false }));
    setResolvingIssueId((prev) => ({ ...prev, [id]: undefined }));
  };

  const handleClearAll = () => {
    resetAllState();
    setFiles(EMPTY_FILES);
    setBrief(EMPTY_BRIEF);
    setSwpConfig(EMPTY_SWP_CONFIG);
    setSwpTrips(null);
    setTripEdits({});
    setUploadedSessionIds({});
    setUploadedBriefSignature(null);
    setPlannerSessionId(null);
    setAuditReports({});
    setAuditErrors({});
    setAuditLoading({});
    setResolvingIssueId({});
    setReuploadingSensiwatch(false);
    setReuploadError(null);
  };

  const handleResolveIssue = async (
    id: UploadSlotId,
    issueId: string,
    decisionId: string,
    selectedItems?: string[]
  ) => {
    const report = auditReports[id];
    if (!report) return;
    setResolvingIssueId((prev) => ({ ...prev, [id]: issueId }));
    try {
      const updated = await resolveIssue(report.session_id, issueId, decisionId, selectedItems);
      if (sessionIdsRef.current[id] !== report.session_id) return;
      // The audited data changed, so anything built on it is out of date.
      resetDownstreamState();
      setAuditReports((prev) => ({ ...prev, [id]: updated }));
    } catch (err) {
      setAuditErrors((prev) => ({
        ...prev,
        [id]: err instanceof AuditApiError ? err.message : "Could not apply that decision.",
      }));
    } finally {
      setResolvingIssueId((prev) => ({ ...prev, [id]: undefined }));
    }
  };

  // A corrected file re-uploaded from the SensiWatch outlier-correction step
  // (see AuditPage / OutlierCorrectionStep) -- uploaded into the SAME session, with
  // the audit state cleared so the pipeline re-runs from scratch on the corrected data.
  // Resolves to the (unchanged) session id, or null if the upload failed.
  const handleReuploadSensiwatch = async (file: File): Promise<string | null> => {
    const sessionId = sessionIdsRef.current.sensiwatch;
    if (!sessionId) return null;
    setReuploadingSensiwatch(true);
    setReuploadError(null);
    try {
      // Same session: the backend diffs the corrected file against the original upload and swaps the data in.
      await reuploadCorrected(sessionId, file);
      resetAllState();
      setFiles((prev) => ({ ...prev, sensiwatch: file }));
      setAuditReports((prev) => ({ ...prev, sensiwatch: undefined }));
      setAuditErrors((prev) => ({ ...prev, sensiwatch: undefined }));
      return sessionId;
    } catch (err) {
      setReuploadError(err instanceof AuditApiError ? err.message : "Could not upload the corrected file.");
      return null;
    } finally {
      setReuploadingSensiwatch(false);
    }
  };

  // A trip's times were changed on the Audit page: keep them in the Trips page's edit list too, so loading the
  // trips again keeps the change.
  const handleTripTimesEdited = (tripKey: string, result: SwpTimesResult) =>
    setTripEdits((prev) => ({
      ...prev,
      [tripKey]: {
        ...prev[tripKey],
        ...(result.departure_utc ? { departure: result.departure_utc } : {}),
        ...(result.arrival_utc ? { arrival: result.arrival_utc } : {}),
      },
    }));

  const handleRevertIssue = async (id: UploadSlotId, issueId: string) => {
    const report = auditReports[id];
    if (!report) return;
    setResolvingIssueId((prev) => ({ ...prev, [id]: issueId }));
    try {
      const updated = await revertIssue(report.session_id, issueId);
      if (sessionIdsRef.current[id] !== report.session_id) return;
      resetDownstreamState();
      setAuditReports((prev) => ({ ...prev, [id]: updated }));
    } catch (err) {
      setAuditErrors((prev) => ({
        ...prev,
        [id]: err instanceof AuditApiError ? err.message : "Could not revert that change.",
      }));
    } finally {
      setResolvingIssueId((prev) => ({ ...prev, [id]: undefined }));
    }
  };

  return (
    <BrowserRouter>
      <DataSourceContext.Provider value={dataSource}>
      <PlannerSkippedContext.Provider value={plannerSkipped}>
      <Routes>
        <Route path="/" element={<WelcomePage />} />
        <Route element={<AppShell onNewProgram={handleClearAll} sessionId={plannerSessionId} />}>
        <Route
          path="/upload"
          element={
            <UploadPage
              files={files}
              brief={brief}
              dataSource={dataSource}
              onSourceChange={handleSourceChange}
              config={swpConfig}
              onConfigChange={setSwpConfig}
              trips={swpTrips}
              onTripsChange={setSwpTrips}
              edits={tripEdits}
              onEditsChange={setTripEdits}
              onLoadComplete={handleLoadComplete}
              onSelect={handleSelect}
              onRemove={handleRemove}
              sessionId={plannerSessionId}
              onBriefChange={setBrief}
              onUploadComplete={handleUploadComplete}
              uploadedSessionIds={uploadedSessionIds}
              uploadedBriefSignature={uploadedBriefSignature}
            />
          }
        />
        <Route path="/planner" element={<Navigate to="/upload" replace />} />
        <Route
          path="/audit"
          element={
            <AuditPage
              files={files}
              uploadedSessionIds={uploadedSessionIds}
              auditReports={auditReports}
              auditLoading={auditLoading}
              auditErrors={auditErrors}
              resolvingIssueId={resolvingIssueId}
              onRunAudit={handleRunAudit}
              onResolveIssue={handleResolveIssue}
              onRevertIssue={handleRevertIssue}
              onReuploadSensiwatch={handleReuploadSensiwatch}
              reuploadingSensiwatch={reuploadingSensiwatch}
              reuploadError={reuploadError}
              onTripTimesEdited={handleTripTimesEdited}
            />
          }
        />
        <Route path="/features" element={<FeaturesPage files={files} auditReports={auditReports} />} />
        <Route path="/analysis" element={<AnalysisPage files={files} auditReports={auditReports} />} />
        <Route path="/report" element={<ReportPage files={files} auditReports={auditReports} />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </PlannerSkippedContext.Provider>
      </DataSourceContext.Provider>
    </BrowserRouter>
  );
}

export default App;
