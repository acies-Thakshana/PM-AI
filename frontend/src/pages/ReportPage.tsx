import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import StatTile from "../components/StatTile";
import PivotFilterBar from "../components/PivotFilterBar";
import { IconClipboard, IconChevronLeft, IconDoc, IconDownload, IconGrid, IconLayers, IconSparkle, IconWarnTriangle } from "../components/icons";
import { AuditApiError } from "../api/client";
import { fetchPivotReport } from "../api/pivots";
import {
  downloadReportUrl,
  fetchReportFilters,
  fetchReportFilterScope,
  fetchReportTitles,
  saveReportFilters,
  saveReportFilterScope,
  saveReportTitle,
  uploadReportTemplate,
} from "../api/report";
import type { PivotFilter, PivotReport, ReportTemplateSummary } from "../api/types";
import { AUDITED_SLOTS, UPLOAD_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import { useSlotState } from "../hooks/useSlotState";
import {
  DEPARTURE_COLUMN,
  activeColumns,
  columnLabel,
  globalColumnsFor,
  globalCombinationsFor,
  globalOptionsFor,
  pivotSlidePreviews,
  rangeFromFilters,
  selectionsFromFilters,
} from "../utils/reportFilters";
import type { AuditReportsState, FilesState } from "../App";
import "./ReportPage.css";

interface ReportPageProps {
  files: FilesState;
  auditReports: AuditReportsState;
}

export default function ReportPage({ files, auditReports }: ReportPageProps) {
  const navigate = useNavigate();

  const [reports, reportsApi] = useSlotState<PivotReport>();
  const [loading, loadingApi] = useSlotState<boolean>();
  const [errors, errorsApi] = useSlotState<string>();

  const [reportFilters, reportFiltersApi] = useSlotState<PivotFilter[]>();
  const [filtersLoading, filtersLoadingApi] = useSlotState<boolean>();
  const [savingFilters, savingFiltersApi] = useSlotState<boolean>();
  const [rangeDraft, rangeDraftApi] = useSlotState<{ start: string; end: string }>();

  const [filterScope, filterScopeApi] = useSlotState<Record<string, string[]>>();
  const [scopeLoading, scopeLoadingApi] = useSlotState<boolean>();
  const [savingScope, setSavingScope] = useState<Record<string, boolean>>({});

  const [titles, titlesApi] = useSlotState<Record<string, string>>();
  const [titlesLoading, titlesLoadingApi] = useSlotState<boolean>();
  const [savingTitle, setSavingTitle] = useState<Record<string, boolean>>({});

  const [templateSummary, setTemplateSummary] = useState<ReportTemplateSummary | null>(null);
  const [templateLoading, setTemplateLoading] = useState(false);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const hasTemplateFile = !!files.reportTemplate;

  // Optional -- when a Report Template file was selected on the Upload page,
  // send it once so every download for the rest of this session uses it as
  // the base deck instead of the built-in layout (see report_generator.py's
  // build_report / TemplateReportBuilder).
  useEffect(() => {
    if (!hasTemplateFile || templateSummary || templateLoading || templateError) return;
    setTemplateLoading(true);
    uploadReportTemplate(files.reportTemplate!)
      .then(setTemplateSummary)
      .catch((err) => setTemplateError(err instanceof AuditApiError ? err.message : "Could not upload the Report Template."))
      .finally(() => setTemplateLoading(false));
  }, [hasTemplateFile, files.reportTemplate, templateSummary, templateLoading, templateError]);

  const auditedReady = AUDITED_SLOTS.filter((id) => files[id] && auditReports[id]?.status === "reviewed");

  useEffect(() => {
    for (const id of auditedReady) {
      if (reports[id] || loading[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      loadingApi.set(id, true);
      fetchPivotReport(sessionId)
        .then((report) => reportsApi.set(id, report))
        .catch((err) =>
          errorsApi.set(id, err instanceof AuditApiError ? err.message : "Could not check the analysis for this source.")
        )
        .finally(() => loadingApi.set(id, false));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditedReady, auditReports]);

  const slotsReady = auditedReady.filter((id) => (reports[id]?.pivots.length ?? 0) > 0);

  useEffect(() => {
    for (const id of slotsReady) {
      if (reportFilters[id] || filtersLoading[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      filtersLoadingApi.set(id, true);
      fetchReportFilters(sessionId)
        .then((res) => reportFiltersApi.set(id, res.filters))
        .catch((err) =>
          errorsApi.set(id, err instanceof AuditApiError ? err.message : "Could not load report filters.")
        )
        .finally(() => filtersLoadingApi.set(id, false));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slotsReady, auditReports]);

  useEffect(() => {
    for (const id of slotsReady) {
      if (filterScope[id] || scopeLoading[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      scopeLoadingApi.set(id, true);
      fetchReportFilterScope(sessionId)
        .then((res) => filterScopeApi.set(id, res.scope))
        .catch((err) =>
          errorsApi.set(id, err instanceof AuditApiError ? err.message : "Could not load filter scope.")
        )
        .finally(() => scopeLoadingApi.set(id, false));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slotsReady, auditReports]);

  useEffect(() => {
    for (const id of slotsReady) {
      if (titles[id] || titlesLoading[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      titlesLoadingApi.set(id, true);
      fetchReportTitles(sessionId)
        .then((res) => titlesApi.set(id, res.titles))
        .catch((err) =>
          errorsApi.set(id, err instanceof AuditApiError ? err.message : "Could not load slide titles.")
        )
        .finally(() => titlesLoadingApi.set(id, false));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slotsReady, auditReports]);

  const handleSaveTitle = (id: UploadSlotId, pivotId: string, title: string) => {
    const sessionId = auditReports[id]!.session_id;
    setSavingTitle((prev) => ({ ...prev, [pivotId]: true }));
    saveReportTitle(sessionId, pivotId, title)
      .then((res) => titlesApi.set(id, res.titles))
      .catch((err) =>
        errorsApi.set(id, err instanceof AuditApiError ? err.message : "Could not rename the slide.")
      )
      .finally(() => setSavingTitle((prev) => ({ ...prev, [pivotId]: false })));
  };

  // Toggles ONE column on/off for ONE pivot -- starts from the full active
  // set if this pivot has no override yet. Always saves the resulting list
  // explicitly, even when it happens to equal every active column: some
  // pivots default to a narrower scope than "everything" (see the backend's
  // DEFAULT_SCOPE_EXCLUSIONS), so clearing back to an implicit "no override"
  // here would silently revert the user's own explicit choice back to that
  // narrower default the next time this page loads, instead of keeping
  // whatever they last set as a static, sticky selection.
  const handleToggleScope = (id: UploadSlotId, pivotId: string, column: string, allActive: string[]) => {
    const sessionId = auditReports[id]!.session_id;
    const baseline = filterScope[id]?.[pivotId] ?? allActive;
    const next = baseline.includes(column) ? baseline.filter((c) => c !== column) : [...baseline, column];
    setSavingScope((prev) => ({ ...prev, [pivotId]: true }));
    saveReportFilterScope(sessionId, pivotId, next)
      .then((res) => filterScopeApi.set(id, res.scope))
      .catch((err) =>
        errorsApi.set(id, err instanceof AuditApiError ? err.message : "Could not save filter scope.")
      )
      .finally(() => setSavingScope((prev) => ({ ...prev, [pivotId]: false })));
  };

  const saveFilters = (id: UploadSlotId, filters: PivotFilter[]) => {
    const sessionId = auditReports[id]!.session_id;
    savingFiltersApi.set(id, true);
    saveReportFilters(sessionId, filters)
      .then((res) => reportFiltersApi.set(id, res.filters))
      .catch((err) =>
        errorsApi.set(id, err instanceof AuditApiError ? err.message : "Could not save filters.")
      )
      .finally(() => savingFiltersApi.set(id, false));
  };

  const handleSaveCategorical = (id: UploadSlotId, nextSelections: Record<string, string[] | undefined>) => {
    const current = reportFilters[id] ?? [];
    const inFilters: PivotFilter[] = [];
    for (const [column, values] of Object.entries(nextSelections)) {
      if (values !== undefined) inFilters.push({ column, op: "in", value: values });
    }
    const preservedRange = current.filter((f) => f.column === DEPARTURE_COLUMN);
    saveFilters(id, [...inFilters, ...preservedRange]);
  };

  const handleApplyRange = (id: UploadSlotId, start: string, end: string) => {
    const current = reportFilters[id] ?? [];
    const rangeFilters: PivotFilter[] =
      start && end
        ? [
            { column: DEPARTURE_COLUMN, op: "gte", value: `${start} 00:00:00` },
            { column: DEPARTURE_COLUMN, op: "lte", value: `${end} 23:59:59` },
          ]
        : [];
    const preservedIn = current.filter((f) => f.column !== DEPARTURE_COLUMN);
    saveFilters(id, [...preservedIn, ...rangeFilters]);
  };

  if (AUDITED_SLOTS.every((id) => !files[id])) {
    return (
      <div className="report-page">
        <Header subtitle="Report" />
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
        <Header subtitle="Report" />
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
        <Header subtitle="Report" />
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
      <Header subtitle="Report" />
      <main className="report-page__main">
        <StepIndicator current={5} />

        <PageHeader
          icon={<IconClipboard />}
          title="Report"
          subtitle="One shared filter for the whole report -- pick 2+ values for a column (e.g. Origin) and every table below gets one slide per value instead of one slide combining them."
        />

        {hasTemplateFile && (
          <p className="report-page__template-status">
            {templateLoading && <>Uploading report template ({files.reportTemplate!.name})…</>}
            {templateSummary?.filename && <>Using your uploaded template ({templateSummary.filename}) as the report's base design.</>}
            {templateError && <span className="report-page__error">{templateError}</span>}
          </p>
        )}

        {slotsReady.map((id) => {
          const slot = UPLOAD_SLOTS.find((s) => s.id === id)!;
          const report = reports[id]!;
          const aiPivotCount = report.pivots.filter((p) => p.id.startsWith("ai_pivot_")).length;
          const customPivotCount = report.pivots.filter((p) => p.id.startsWith("custom_pivot_")).length;
          const globalColumns = globalColumnsFor(report.pivots);
          const filters = reportFilters[id] ?? [];

          return (
            <section className="report-page__card" key={id}>
              <div className="report-page__card-head">
                <div className="report-page__card-head-left">
                  <h2 className="report-page__slot-title">{slot.title}</h2>
                  <span className="report-page__pill">REPORT READY</span>
                </div>
                <span className="report-page__filename">{files[id]!.name}</span>
              </div>

              {errors[id] && <p className="report-page__error">{errors[id]}</p>}

              <div className="report-page__stat-row">
                <StatTile icon={<IconDoc />} color="blue" value={report.row_count.toLocaleString()} label="Rows" />
                <StatTile icon={<IconLayers />} color="teal" value={report.pivots.length} label="Analysis Tables" />
                {aiPivotCount > 0 && <StatTile icon={<IconSparkle />} color="amber" value={aiPivotCount} label="AI Suggested" />}
                {customPivotCount > 0 && <StatTile icon={<IconGrid />} color="purple" value={customPivotCount} label="Custom Analyses" />}
                {report.skipped_notes.length > 0 && (
                  <StatTile icon={<IconWarnTriangle />} color="error" value={report.skipped_notes.length} label="Skipped" />
                )}
              </div>

              {globalColumns.length > 0 && (
                <div className="report-page__global-filters">
                  <span className="report-page__range-label">Filters (applied to every table below)</span>
                  <PivotFilterBar
                    filterableColumns={globalColumns}
                    filterOptions={globalOptionsFor(report.pivots, globalColumns)}
                    combinations={globalCombinationsFor(report.pivots)}
                    selected={selectionsFromFilters(filters, globalColumns)}
                    onSave={(next) => handleSaveCategorical(id, next)}
                    saving={!!savingFilters[id]}
                  />
                </div>
              )}

              {(() => {
                const range = rangeDraft[id] ?? rangeFromFilters(filters);
                const setField = (field: "start" | "end", value: string) =>
                  rangeDraftApi.set(id, { ...range, [field]: value });
                return (
                  <div className="report-page__range">
                    <span className="report-page__range-label">Departure time (applies to every table above)</span>
                    <div className="report-page__range-row">
                      <input type="date" value={range.start} onChange={(e) => setField("start", e.target.value)} aria-label="Departure start date" />
                      <span className="report-page__range-sep">to</span>
                      <input type="date" value={range.end} onChange={(e) => setField("end", e.target.value)} aria-label="Departure end date" />
                      <button
                        type="button"
                        className="report-page__btn report-page__btn--secondary report-page__range-btn"
                        disabled={!!savingFilters[id] || !range.start || !range.end}
                        onClick={() => handleApplyRange(id, range.start, range.end)}
                      >
                        {savingFilters[id] ? "Saving…" : "Apply Range"}
                      </button>
                      {(range.start || range.end) && (
                        <button
                          type="button"
                          className="report-page__btn report-page__btn--secondary report-page__range-btn"
                          disabled={!!savingFilters[id]}
                          onClick={() => {
                            rangeDraftApi.set(id, { start: "", end: "" });
                            handleApplyRange(id, "", "");
                          }}
                        >
                          Clear
                        </button>
                      )}
                    </div>
                  </div>
                );
              })()}

              <div className="report-page__included">
                <p className="report-page__included-title">This report will include:</p>
                <ul className="report-page__included-list">
                  {report.pivots.flatMap((p, idx) => {
                    const active = activeColumns(filters);
                    const override = filterScope[id]?.[p.id];
                    const applied = override ?? active;
                    const currentTitle = titles[id]?.[p.id] ?? p.name;
                    const previews = pivotSlidePreviews(filters, override);

                    return previews.map((comboLabel, comboIdx) => (
                      <li key={`${p.id}-${comboIdx}`} className="report-page__included-item-wrap">
                        <div className="report-page__included-row">
                          <span className="report-page__slide-label">
                            {previews.length > 1 ? `Slide ${idx + 1}.${comboIdx + 1}` : `Slide ${idx + 1}`}
                          </span>
                          <input
                            key={currentTitle}
                            className="report-page__slide-title"
                            defaultValue={currentTitle}
                            disabled={!!savingTitle[p.id]}
                            aria-label={`Title for ${p.name}`}
                            onBlur={(e) => {
                              const next = e.target.value.trim();
                              if (next && next !== currentTitle) handleSaveTitle(id, p.id, next);
                            }}
                          />
                          <span className="report-page__included-metrics">{p.metric_labels.join(", ")}</span>
                        </div>
                        {(active.length > 0 || comboLabel) && (
                          <div className="report-page__scope-row">
                            {active.length > 0 && (
                              <>
                                <span className="report-page__scope-label">Filters applied:</span>
                                {active.map((column) => (
                                  <button
                                    key={column}
                                    type="button"
                                    className={`report-page__scope-chip ${applied.includes(column) ? "report-page__scope-chip--on" : ""}`}
                                    disabled={!!savingScope[p.id]}
                                    onClick={() => handleToggleScope(id, p.id, column, active)}
                                  >
                                    {columnLabel(column)}
                                  </button>
                                ))}
                              </>
                            )}
                            {comboLabel && <span className="report-page__scope-chip report-page__scope-chip--value">→ {comboLabel}</span>}
                          </div>
                        )}
                      </li>
                    ));
                  })}
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
