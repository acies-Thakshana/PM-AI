import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import StatTile from "../components/StatTile";
import ReportSlideCard from "../components/ReportSlideCard";
import { IconClipboard, IconChevronLeft, IconDoc, IconDownload, IconGrid, IconSparkle, IconWarnTriangle } from "../components/icons";
import {
  createReportSlide,
  deleteReportSlide,
  downloadReportUrl,
  fetchPivotReport,
  fetchReportSlides,
  updateReportSlide,
  AuditApiError,
  type PivotFilter,
  type PivotReport,
  type ReportSlide,
} from "../api/audit";
import { AUDITED_SLOTS, UPLOAD_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { AuditReportsState, FilesState } from "../App";
import "./ReportPage.css";

interface ReportPageProps {
  files: FilesState;
  auditReports: AuditReportsState;
}

type PivotReportsState = Partial<Record<UploadSlotId, PivotReport>>;
type SlidesState = Partial<Record<UploadSlotId, ReportSlide[]>>;
type LoadingState = Partial<Record<UploadSlotId, boolean>>;
type ErrorsState = Partial<Record<UploadSlotId, string>>;

// "Slide 1", "Slide 2", ... for each pivot's base slide, "Slide 2.1",
// "Slide 2.2", ... for slides duplicated ("+ Add slide") off of it -- relies
// on the backend always keeping a slide's children immediately after it.
function computeLabels(slides: ReportSlide[]): Record<string, string> {
  const labels: Record<string, string> = {};
  let topIndex = 0;
  let childIndex = 0;
  for (const s of slides) {
    if (s.parent_id === null) {
      topIndex += 1;
      childIndex = 0;
      labels[s.id] = `Slide ${topIndex}`;
    } else {
      childIndex += 1;
      labels[s.id] = `Slide ${topIndex}.${childIndex}`;
    }
  }
  return labels;
}

export default function ReportPage({ files, auditReports }: ReportPageProps) {
  const navigate = useNavigate();

  const [reports, setReports] = useState<PivotReportsState>({});
  const [loading, setLoading] = useState<LoadingState>({});
  const [errors, setErrors] = useState<ErrorsState>({});

  const [slides, setSlides] = useState<SlidesState>({});
  const [slidesLoading, setSlidesLoading] = useState<LoadingState>({});
  const [savingSlide, setSavingSlide] = useState<Record<string, boolean>>({});

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

  // The slide list is auto-seeded (one per pivot) server-side the first time
  // it's fetched for a session, so this just needs to ask for it once the
  // pivots themselves are ready.
  useEffect(() => {
    for (const id of slotsReady) {
      if (slides[id] || slidesLoading[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      setSlidesLoading((prev) => ({ ...prev, [id]: true }));
      fetchReportSlides(sessionId)
        .then((res) => setSlides((prev) => ({ ...prev, [id]: res.slides })))
        .catch((err) =>
          setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not load the slide list." }))
        )
        .finally(() => setSlidesLoading((prev) => ({ ...prev, [id]: false })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slotsReady, auditReports]);

  const handleSaveTitle = (id: UploadSlotId, slideId: string, title: string) => {
    const sessionId = auditReports[id]!.session_id;
    setSavingSlide((prev) => ({ ...prev, [slideId]: true }));
    updateReportSlide(sessionId, slideId, { title })
      .then((res) => setSlides((prev) => ({ ...prev, [id]: res.slides })))
      .catch((err) =>
        setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not rename the slide." }))
      )
      .finally(() => setSavingSlide((prev) => ({ ...prev, [slideId]: false })));
  };

  const handleSaveFilters = (id: UploadSlotId, slideId: string, filters: PivotFilter[]) => {
    const sessionId = auditReports[id]!.session_id;
    setSavingSlide((prev) => ({ ...prev, [slideId]: true }));
    updateReportSlide(sessionId, slideId, { filters })
      .then((res) => setSlides((prev) => ({ ...prev, [id]: res.slides })))
      .catch((err) =>
        setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not save filters." }))
      )
      .finally(() => setSavingSlide((prev) => ({ ...prev, [slideId]: false })));
  };

  // "+ Add slide" -- explores the same pivot again with a different filter.
  // Inherits the source slide's CURRENT filters (e.g. Origin: Italy) so the
  // user only has to change whatever varies, and always attaches to the
  // TOP-LEVEL slide for that pivot so the hierarchy stays two levels deep.
  const handleDuplicate = (id: UploadSlotId, source: ReportSlide) => {
    const sessionId = auditReports[id]!.session_id;
    const topLevelId = source.parent_id ?? source.id;
    setSavingSlide((prev) => ({ ...prev, [topLevelId]: true }));
    createReportSlide(sessionId, {
      pivot_id: source.pivot_id,
      title: `${source.title} (copy)`,
      filters: source.filters,
      parent_id: topLevelId,
    })
      .then((res) => setSlides((prev) => ({ ...prev, [id]: res.slides })))
      .catch((err) =>
        setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not add the slide." }))
      )
      .finally(() => setSavingSlide((prev) => ({ ...prev, [topLevelId]: false })));
  };

  const handleDelete = (id: UploadSlotId, slideId: string) => {
    const sessionId = auditReports[id]!.session_id;
    setSavingSlide((prev) => ({ ...prev, [slideId]: true }));
    deleteReportSlide(sessionId, slideId)
      .then((res) => setSlides((prev) => ({ ...prev, [id]: res.slides })))
      .catch((err) =>
        setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not remove the slide." }))
      )
      .finally(() => setSavingSlide((prev) => ({ ...prev, [slideId]: false })));
  };

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
          subtitle="Each slide below is its own {title, table, filter} -- edit a title, change a filter, or add another slide off the same table with a different filter (e.g. Origin: Italy vs Germany)."
        />

        {slotsReady.map((id) => {
          const slot = UPLOAD_SLOTS.find((s) => s.id === id)!;
          const report = reports[id]!;
          const aiPivotCount = report.pivots.filter((p) => p.id.startsWith("ai_pivot_")).length;
          const customPivotCount = report.pivots.filter((p) => p.id.startsWith("custom_pivot_")).length;
          const pivotsById = new Map(report.pivots.map((p) => [p.id, p]));
          const slotSlides = slides[id];
          const labels = slotSlides ? computeLabels(slotSlides) : {};

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

              <div className="report-page__slides">
                {!slotSlides ? (
                  <p className="report-page__loading">Loading slides…</p>
                ) : (
                  slotSlides.map((slide) => (
                    <ReportSlideCard
                      key={slide.id}
                      slide={slide}
                      pivot={pivotsById.get(slide.pivot_id)}
                      label={labels[slide.id]}
                      onSaveTitle={(title) => handleSaveTitle(id, slide.id, title)}
                      onSaveFilters={(filters) => handleSaveFilters(id, slide.id, filters)}
                      onDuplicate={() => handleDuplicate(id, slide)}
                      onDelete={slide.parent_id ? () => handleDelete(id, slide.id) : undefined}
                      saving={!!savingSlide[slide.id]}
                    />
                  ))
                )}
                <p className="report-page__summary-note">Plus a final Summary slide, generated from the overall analysis.</p>
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
