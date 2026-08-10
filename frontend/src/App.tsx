import { useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import WelcomePage from "./pages/WelcomePage";
import UploadPage from "./pages/UploadPage";
import AuditPage from "./pages/AuditPage";
import FeaturesPage from "./pages/FeaturesPage";
import AnalysisPage from "./pages/AnalysisPage";
import ReportPage from "./pages/ReportPage";
import { AuditApiError, resolveIssue, revertIssue, uploadForAudit } from "./api/audit";
import type { AuditReport as AuditReportData } from "./api/audit";
import { isAudited } from "./constants/uploadSlots";
import type { UploadSlotId } from "./types/upload";

export type FilesState = Record<UploadSlotId, File | null>;
export type AuditReportsState = Partial<Record<UploadSlotId, AuditReportData>>;
export type AuditLoadingState = Partial<Record<UploadSlotId, boolean>>;
export type AuditErrorsState = Partial<Record<UploadSlotId, string>>;
export type ResolvingState = Partial<Record<UploadSlotId, string>>;

const EMPTY_FILES: FilesState = {
  sensiwatch: null,
  coldstream: null,
  thresholds: null,
  customerKpis: null,
  analysisProfile: null,
};

function App() {
  const [files, setFiles] = useState<FilesState>(EMPTY_FILES);
  const [auditReports, setAuditReports] = useState<AuditReportsState>({});
  const [auditLoading, setAuditLoading] = useState<AuditLoadingState>({});
  const [auditErrors, setAuditErrors] = useState<AuditErrorsState>({});
  const [resolvingIssueId, setResolvingIssueId] = useState<ResolvingState>({});

  const runAudit = async (id: UploadSlotId, file: File) => {
    setAuditLoading((prev) => ({ ...prev, [id]: true }));
    setAuditErrors((prev) => ({ ...prev, [id]: undefined }));
    try {
      const report = await uploadForAudit(id, file);
      setAuditReports((prev) => ({ ...prev, [id]: report }));
    } catch (err) {
      setAuditErrors((prev) => ({
        ...prev,
        [id]: err instanceof AuditApiError ? err.message : "Could not reach the audit agent. Is the backend running?",
      }));
    } finally {
      setAuditLoading((prev) => ({ ...prev, [id]: false }));
    }
  };

  const handleSelect = (id: UploadSlotId, file: File) => {
    setFiles((prev) => ({ ...prev, [id]: file }));
    if (isAudited(id)) {
      setAuditReports((prev) => ({ ...prev, [id]: undefined }));
      setAuditErrors((prev) => ({ ...prev, [id]: undefined }));
    }
  };

  const handleRemove = (id: UploadSlotId) => {
    setFiles((prev) => ({ ...prev, [id]: null }));
    setAuditReports((prev) => ({ ...prev, [id]: undefined }));
    setAuditErrors((prev) => ({ ...prev, [id]: undefined }));
    setAuditLoading((prev) => ({ ...prev, [id]: false }));
  };

  const handleClearAll = () => {
    setFiles(EMPTY_FILES);
    setAuditReports({});
    setAuditErrors({});
    setAuditLoading({});
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

  const handleRevertIssue = async (id: UploadSlotId, issueId: string) => {
    const report = auditReports[id];
    if (!report) return;
    setResolvingIssueId((prev) => ({ ...prev, [id]: issueId }));
    try {
      const updated = await revertIssue(report.session_id, issueId);
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
      <Routes>
        <Route path="/" element={<WelcomePage />} />
        <Route
          path="/upload"
          element={<UploadPage files={files} onSelect={handleSelect} onRemove={handleRemove} onClearAll={handleClearAll} />}
        />
        <Route
          path="/audit"
          element={
            <AuditPage
              files={files}
              auditReports={auditReports}
              auditLoading={auditLoading}
              auditErrors={auditErrors}
              resolvingIssueId={resolvingIssueId}
              onRunAudit={runAudit}
              onResolveIssue={handleResolveIssue}
              onRevertIssue={handleRevertIssue}
            />
          }
        />
        <Route path="/features" element={<FeaturesPage files={files} auditReports={auditReports} />} />
        <Route path="/analysis" element={<AnalysisPage files={files} auditReports={auditReports} />} />
        <Route path="/report" element={<ReportPage files={files} auditReports={auditReports} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
