import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import StatTile from "../components/StatTile";
import PivotFilterBar from "../components/PivotFilterBar";
import { IconClipboard, IconChevronLeft, IconDoc, IconDownload, IconGrid, IconSparkle, IconWarnTriangle } from "../components/icons";
import {
  downloadReportUrl,
  fetchPivotReport,
  fetchReportFilters,
  fetchReportFilterScope,
  fetchReportTitles,
  saveReportFilters,
  saveReportFilterScope,
  saveReportTitle,
  AuditApiError,
  type PivotFilter,
  type PivotReport,
  type PivotResult,
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
type ReportFiltersState = Partial<Record<UploadSlotId, PivotFilter[]>>;
type LoadingState = Partial<Record<UploadSlotId, boolean>>;
type ErrorsState = Partial<Record<UploadSlotId, string>>;

// The raw column the data uses for a shipment's departure -- not one of the
// categorical filterable_columns slicers, so it gets its own date-range
// control alongside them.
const DEPARTURE_COLUMN = "Actual Departure Time CET";
// Mirrors the backend's report_generator.MAX_COMBOS_PER_PIVOT.
const MAX_COMBOS = 12;

function selectionsFromFilters(filters: PivotFilter[], filterableColumns: string[]): Record<string, string[] | undefined> {
  const selections: Record<string, string[] | undefined> = {};
  for (const f of filters) {
    if (f.op === "in" && filterableColumns.includes(f.column)) {
      selections[f.column] = (Array.isArray(f.value) ? f.value : [f.value]).map(String);
    }
  }
  return selections;
}

function globalColumnsFor(pivots: PivotResult[]): string[] {
  const columns = new Set<string>();
  for (const p of pivots) for (const c of p.filterable_columns) columns.add(c);
  return [...columns];
}

function globalOptionsFor(pivots: PivotResult[], columns: string[]): Record<string, string[]> {
  const options: Record<string, string[]> = {};
  for (const column of columns) {
    const values = new Set<string>();
    for (const p of pivots) for (const v of p.filter_options[column] ?? []) values.add(v);
    options[column] = [...values].sort();
  }
  return options;
}

function globalCombinationsFor(pivots: PivotResult[]): Record<string, string>[] {
  return pivots.flatMap((p) => p.filter_combinations);
}

function rangeFromFilters(filters: PivotFilter[]): { start: string; end: string } {
  const gte = filters.find((f) => f.column === DEPARTURE_COLUMN && f.op === "gte");
  const lte = filters.find((f) => f.column === DEPARTURE_COLUMN && f.op === "lte");
  return {
    start: typeof gte?.value === "string" ? gte.value.slice(0, 10) : "",
    end: typeof lte?.value === "string" ? lte.value.slice(0, 10) : "",
  };
}

// A column with 2+ selected values fans out into one slide per value, for
// EVERY table -- multiple such columns cartesian-product together.
function comboCount(filters: PivotFilter[]): number {
  const multiplierSizes = filters
    .filter((f) => f.op === "in" && Array.isArray(f.value) && f.value.length > 1)
    .map((f) => (f.value as unknown[]).length);
  const total = multiplierSizes.reduce((acc, n) => acc * n, 1);
  return Math.min(total, MAX_COMBOS);
}

// Which columns the shared filter is actually constraining right now --
// only these are worth a per-pivot "apply this to me?" toggle.
function activeColumns(filters: PivotFilter[]): string[] {
  return [...new Set(filters.map((f) => f.column))];
}

function columnLabel(column: string): string {
  return column === DEPARTURE_COLUMN ? "Departure time" : column;
}

// A pivot with no scope override respects every active column (today's
// "same scope everywhere" default); an override restricts it to just the
// listed columns, so e.g. an Origin multiplier can be ignored for one pivot
// while still multiplying every other one.
function comboCountForScope(filters: PivotFilter[], allowed: string[] | undefined): number {
  const scoped = allowed === undefined ? filters : filters.filter((f) => allowed.includes(f.column));
  return comboCount(scoped);
}

export default function ReportPage({ files, auditReports }: ReportPageProps) {
  const navigate = useNavigate();

  const [reports, setReports] = useState<PivotReportsState>({});
  const [loading, setLoading] = useState<LoadingState>({});
  const [errors, setErrors] = useState<ErrorsState>({});

  const [reportFilters, setReportFilters] = useState<ReportFiltersState>({});
  const [filtersLoading, setFiltersLoading] = useState<LoadingState>({});
  const [savingFilters, setSavingFilters] = useState<LoadingState>({});
  const [rangeDraft, setRangeDraft] = useState<Partial<Record<UploadSlotId, { start: string; end: string }>>>({});

  const [filterScope, setFilterScope] = useState<Partial<Record<UploadSlotId, Record<string, string[]>>>>({});
  const [scopeLoading, setScopeLoading] = useState<LoadingState>({});
  const [savingScope, setSavingScope] = useState<Record<string, boolean>>({});

  const [titles, setTitles] = useState<Partial<Record<UploadSlotId, Record<string, string>>>>({});
  const [titlesLoading, setTitlesLoading] = useState<LoadingState>({});
  const [savingTitle, setSavingTitle] = useState<Record<string, boolean>>({});

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

  useEffect(() => {
    for (const id of slotsReady) {
      if (reportFilters[id] || filtersLoading[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      setFiltersLoading((prev) => ({ ...prev, [id]: true }));
      fetchReportFilters(sessionId)
        .then((res) => setReportFilters((prev) => ({ ...prev, [id]: res.filters })))
        .catch((err) =>
          setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not load report filters." }))
        )
        .finally(() => setFiltersLoading((prev) => ({ ...prev, [id]: false })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slotsReady, auditReports]);

  useEffect(() => {
    for (const id of slotsReady) {
      if (filterScope[id] || scopeLoading[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      setScopeLoading((prev) => ({ ...prev, [id]: true }));
      fetchReportFilterScope(sessionId)
        .then((res) => setFilterScope((prev) => ({ ...prev, [id]: res.scope })))
        .catch((err) =>
          setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not load filter scope." }))
        )
        .finally(() => setScopeLoading((prev) => ({ ...prev, [id]: false })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slotsReady, auditReports]);

  useEffect(() => {
    for (const id of slotsReady) {
      if (titles[id] || titlesLoading[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      setTitlesLoading((prev) => ({ ...prev, [id]: true }));
      fetchReportTitles(sessionId)
        .then((res) => setTitles((prev) => ({ ...prev, [id]: res.titles })))
        .catch((err) =>
          setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not load slide titles." }))
        )
        .finally(() => setTitlesLoading((prev) => ({ ...prev, [id]: false })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slotsReady, auditReports]);

  const handleSaveTitle = (id: UploadSlotId, pivotId: string, title: string) => {
    const sessionId = auditReports[id]!.session_id;
    setSavingTitle((prev) => ({ ...prev, [pivotId]: true }));
    saveReportTitle(sessionId, pivotId, title)
      .then((res) => setTitles((prev) => ({ ...prev, [id]: res.titles })))
      .catch((err) =>
        setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not rename the slide." }))
      )
      .finally(() => setSavingTitle((prev) => ({ ...prev, [pivotId]: false })));
  };

  // Toggles ONE column on/off for ONE pivot -- starts from the full active
  // set if this pivot has no override yet, and clears the override entirely
  // if toggling lands back on the full set (so it stays "default" rather
  // than an explicit list that happens to match).
  const handleToggleScope = (id: UploadSlotId, pivotId: string, column: string, allActive: string[]) => {
    const sessionId = auditReports[id]!.session_id;
    const baseline = filterScope[id]?.[pivotId] ?? allActive;
    const next = baseline.includes(column) ? baseline.filter((c) => c !== column) : [...baseline, column];
    const isFullSet = next.length === allActive.length && allActive.every((c) => next.includes(c));
    setSavingScope((prev) => ({ ...prev, [pivotId]: true }));
    saveReportFilterScope(sessionId, pivotId, isFullSet ? null : next)
      .then((res) => setFilterScope((prev) => ({ ...prev, [id]: res.scope })))
      .catch((err) =>
        setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not save filter scope." }))
      )
      .finally(() => setSavingScope((prev) => ({ ...prev, [pivotId]: false })));
  };

  const saveFilters = (id: UploadSlotId, filters: PivotFilter[]) => {
    const sessionId = auditReports[id]!.session_id;
    setSavingFilters((prev) => ({ ...prev, [id]: true }));
    saveReportFilters(sessionId, filters)
      .then((res) => setReportFilters((prev) => ({ ...prev, [id]: res.filters })))
      .catch((err) =>
        setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not save filters." }))
      )
      .finally(() => setSavingFilters((prev) => ({ ...prev, [id]: false })));
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
          subtitle="One shared filter for the whole report -- pick 2+ values for a column (e.g. Origin) and every table below gets one slide per value instead of one slide combining them."
        />

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
                  setRangeDraft((prev) => ({ ...prev, [id]: { ...range, [field]: value } }));
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
                            setRangeDraft((prev) => ({ ...prev, [id]: { start: "", end: "" } }));
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
                  {report.pivots.map((p, idx) => {
                    const active = activeColumns(filters);
                    const override = filterScope[id]?.[p.id];
                    const applied = override ?? active;
                    const pivotSlides = comboCountForScope(filters, override);
                    const currentTitle = titles[id]?.[p.id] ?? p.name;
                    return (
                      <li key={p.id} className="report-page__included-item-wrap">
                        <div className="report-page__included-row">
                          <span className="report-page__slide-label">Slide {idx + 1}</span>
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
                          <span className="report-page__included-metrics">
                            {p.metric_labels.join(", ")}
                            {pivotSlides > 1 ? ` · ${pivotSlides} slides` : ""}
                          </span>
                        </div>
                        {active.length > 0 && (
                          <div className="report-page__scope-row">
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
                          </div>
                        )}
                      </li>
                    );
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
