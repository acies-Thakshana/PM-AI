import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import StatTile from "../components/StatTile";
import { IconClipboard, IconChevronLeft, IconDoc, IconDownload, IconGrid, IconSparkle, IconWarnTriangle } from "../components/icons";
import { downloadReportUrl, fetchPivotReport, AuditApiError, type PivotReport } from "../api/audit";
import { AUDITED_SLOTS, UPLOAD_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { AuditReportsState, FilesState } from "../App";
import "./ReportPage.css";

interface ReportPageProps {
  files: FilesState;
  auditReports: AuditReportsState;
}

type PivotReportsState = Partial<Record<UploadSlotId, PivotReport>>;
type LoadingState = Partial<Record<UploadSlotId, boolean>>;
type ErrorsState = Partial<Record<UploadSlotId, string>>;

export default function ReportPage({ files, auditReports }: ReportPageProps) {
  const navigate = useNavigate();

  const [reports, setReports] = useState<PivotReportsState>({});
  const [loading, setLoading] = useState<LoadingState>({});
  const [errors, setErrors] = useState<ErrorsState>({});

  const auditedReady = AUDITED_SLOTS.filter((id) => files[id] && auditReports[id]?.status === "reviewed");

  useEffect(() => {
    for (const id of auditedReady) {
      if (reports[id] || loading[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      setLoading((prev) => ({ ...prev, [id]: true }));
      fetchPivotReport(sessionId)
        .then((report) => setReports((prev) => ({ ...prev, [id]: report })))
        .catch((err) =>
          setErrors((prev) => ({
            ...prev,
            [id]: err instanceof AuditApiError ? err.message : "Could not check the analysis for this source.",
          }))
        )
        .finally(() => setLoading((prev) => ({ ...prev, [id]: false })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditedReady, auditReports]);

  const slotsReady = auditedReady.filter((id) => (reports[id]?.pivots.length ?? 0) > 0);

  if (AUDITED_SLOTS.every((id) => !files[id])) {
    return (
      <div className="report-page">
        <Header />
        <main className="report-page__main">
          <StepIndicator current={5} />
          <div className="report-page__empty">
            <p>No audited data yet.</p>
            <button type="button" className="report-page__btn report-page__btn--primary" onClick={() => navigate("/upload")}>
              Go to Upload
            </button>
          </div>
        </main>
      </div>
    );
  }

  if (auditedReady.length === 0) {
    return (
      <div className="report-page">
        <Header />
        <main className="report-page__main">
          <StepIndicator current={5} />
          <div className="report-page__empty">
            <p>Finish resolving the data audit before a report can be generated.</p>
            <button type="button" className="report-page__btn report-page__btn--primary" onClick={() => navigate("/audit")}>
              Back to Audit
            </button>
          </div>
        </main>
      </div>
    );
  }

  const stillChecking = Object.values(loading).some(Boolean);

  if (slotsReady.length === 0) {
    return (
      <div className="report-page">
        <Header />
        <main className="report-page__main">
          <StepIndicator current={5} />
          <div className="report-page__empty">
            <p>
              {stillChecking
                ? "Checking whether analysis tables have been computed…"
                : "No analysis tables have been computed yet -- run the Analysis step first, since the report is built from whatever analyses (and slicer filters) are currently in place there."}
            </p>
            <button type="button" className="report-page__btn report-page__btn--primary" onClick={() => navigate("/analysis")}>
              Go to Analysis
            </button>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="report-page">
      <Header />
      <main className="report-page__main">
        <StepIndicator current={5} />

        <PageHeader
          icon={<IconClipboard />}
          title="Report"
          subtitle="A downloadable .pptx built with native, editable charts from whatever analyses and filters are currently set on the Analysis page -- plus the summary."
        />

        {slotsReady.map((id) => {
          const slot = UPLOAD_SLOTS.find((s) => s.id === id)!;
          const report = reports[id]!;
          const aiPivotCount = report.pivots.filter((p) => p.id.startsWith("ai_pivot_")).length;
          const customPivotCount = report.pivots.filter((p) => p.id.startsWith("custom_pivot_")).length;

          return (
            <section className="report-page__card" key={id}>
              <div className="report-page__card-head">
                <div className="report-page__card-head-left">
                  <span className="report-page__header-icon">
                    <IconClipboard />
                  </span>
                  <div>
                    <h2 className="report-page__slot-title">{slot.title}</h2>
                    <span className="report-page__pill">REPORT READY</span>
                  </div>
                </div>
                <span className="report-page__filename">{files[id]!.name}</span>
              </div>

              {errors[id] && <p className="report-page__error">{errors[id]}</p>}

              <div className="report-page__stat-row">
                <StatTile icon={<IconDoc />} color="blue" value={report.row_count.toLocaleString()} label="Rows" />
                <StatTile icon={<IconGrid />} color="teal" value={report.pivots.length} label="Analysis Tables" />
                {aiPivotCount > 0 && <StatTile icon={<IconSparkle />} color="amber" value={aiPivotCount} label="AI Suggested" />}
                {customPivotCount > 0 && <StatTile icon={<IconGrid />} color="purple" value={customPivotCount} label="Custom Analyses" />}
                {report.skipped_notes.length > 0 && (
                  <StatTile icon={<IconWarnTriangle />} color="error" value={report.skipped_notes.length} label="Skipped" />
                )}
              </div>

              <div className="report-page__included">
                <p className="report-page__included-title">This report will include:</p>
                <ul className="report-page__included-list">
                  {report.pivots.map((p) => (
                    <li key={p.id}>
                      {p.name}
                      <span className="report-page__included-metrics">{p.metric_labels.join(", ")}</span>
                    </li>
                  ))}
                  <li className="report-page__included-summary">Overall analysis summary</li>
                </ul>
              </div>

              <a
                className="report-page__download-btn"
                href={downloadReportUrl(auditReports[id]!.session_id)}
                download
              >
                <IconDownload />
                Download Report (.pptx)
              </a>
            </section>
          );
        })}

        <div className="report-page__actions">
          <button type="button" className="report-page__btn report-page__btn--secondary report-page__nav-btn" onClick={() => navigate("/analysis")}>
            <IconChevronLeft /> Back to Analysis
          </button>
        </div>
      </main>
    </div>
  );
}
