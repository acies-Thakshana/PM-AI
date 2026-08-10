import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import StatTile from "../components/StatTile";
import FeatureCard from "../components/FeatureCard";
import FeatureSuggestionCard from "../components/FeatureSuggestionCard";
import AddKpiForm from "../components/AddKpiForm";
import DataPreviewTable from "../components/DataPreviewTable";
import { IconDoc, IconGrid, IconSparkle, IconWarnTriangle, IconShieldCheck, IconDownload, IconClipboard } from "../components/icons";
import {
  applyFeatures,
  downloadCleansedFileUrl,
  fetchPreview,
  suggestFeatures,
  uploadFeatureDefinitions,
  AuditApiError,
  type DataPreview,
  type FeatureDefinitionsSummary,
  type FeatureReport,
  type FeatureSuggestion,
} from "../api/audit";
import { AUDITED_SLOTS, UPLOAD_SLOTS } from "../constants/uploadSlots";
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
type PreviewOpenState = Partial<Record<UploadSlotId, boolean>>;
type SuggestionsState = Partial<Record<UploadSlotId, FeatureSuggestion[]>>;
type AcceptedState = Partial<Record<UploadSlotId, FeatureSuggestion[]>>;
type BusyIdState = Partial<Record<UploadSlotId, string>>;

function joinClauses(clauses: string[]): string {
  if (clauses.length === 0) return "";
  if (clauses.length === 1) return `${clauses[0]}.`;
  return `${clauses.slice(0, -1).join(", ")}, and ${clauses[clauses.length - 1]}.`;
}

export default function FeaturesPage({ files, auditReports }: FeaturesPageProps) {
  const navigate = useNavigate();
  const [reports, setReports] = useState<FeatureReportsState>({});
  const [loading, setLoading] = useState<LoadingState>({});
  const [errors, setErrors] = useState<ErrorsState>({});
  const [previews, setPreviews] = useState<PreviewsState>({});
  const [previewOpen, setPreviewOpen] = useState<PreviewOpenState>({});

  const [suggestions, setSuggestions] = useState<SuggestionsState>({});
  const [suggestLoading, setSuggestLoading] = useState<LoadingState>({});
  const [suggestError, setSuggestError] = useState<ErrorsState>({});
  const [accepted, setAccepted] = useState<AcceptedState>({});
  const [applyingSuggestionId, setApplyingSuggestionId] = useState<BusyIdState>({});
  const [showAddKpiForm, setShowAddKpiForm] = useState<LoadingState>({});
  const [addingKpi, setAddingKpi] = useState<LoadingState>({});

  const [defsSummary, setDefsSummary] = useState<FeatureDefinitionsSummary | null>(null);
  const [defsLoading, setDefsLoading] = useState(false);
  const [defsError, setDefsError] = useState<string | null>(null);

  const slotsReady = AUDITED_SLOTS.filter((id) => files[id] && auditReports[id]?.status === "reviewed");
  const hasKpiFile = !!files.customerKpis;

  // Step 1: upload the Customer KPI Profile file itself (the feature
  // definitions + COO mapping live INSIDE it -- nothing is bundled/default).
  useEffect(() => {
    if (!hasKpiFile || defsSummary || defsLoading || defsError) return;
    setDefsLoading(true);
    uploadFeatureDefinitions(files.customerKpis!)
      .then(setDefsSummary)
      .catch((err) => setDefsError(err instanceof AuditApiError ? err.message : "Could not upload the Customer KPI Profile."))
      .finally(() => setDefsLoading(false));
  }, [hasKpiFile, files.customerKpis, defsSummary, defsLoading, defsError]);

  // Step 2: once definitions are uploaded, compute features for each audited slot.
  useEffect(() => {
    if (!defsSummary) return;
    for (const id of slotsReady) {
      if (reports[id] || loading[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      setLoading((prev) => ({ ...prev, [id]: true }));
      applyFeatures(sessionId)
        .then((report) => setReports((prev) => ({ ...prev, [id]: report })))
        .catch((err) =>
          setErrors((prev) => ({
            ...prev,
            [id]: err instanceof AuditApiError ? err.message : "Could not compute features.",
          }))
        )
        .finally(() => setLoading((prev) => ({ ...prev, [id]: false })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defsSummary, files, auditReports]);

  const togglePreview = (id: UploadSlotId) => {
    const willOpen = !previewOpen[id];
    setPreviewOpen((prev) => ({ ...prev, [id]: willOpen }));
    if (willOpen && !previews[id]) {
      const sessionId = auditReports[id]!.session_id;
      fetchPreview(sessionId, 30).then((preview) => setPreviews((prev) => ({ ...prev, [id]: preview })));
    }
  };

  const runSuggest = (id: UploadSlotId) => {
    const sessionId = auditReports[id]!.session_id;
    setSuggestLoading((prev) => ({ ...prev, [id]: true }));
    setSuggestError((prev) => ({ ...prev, [id]: undefined }));
    suggestFeatures(sessionId)
      .then((res) => setSuggestions((prev) => ({ ...prev, [id]: res.suggestions })))
      .catch((err) =>
        setSuggestError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not reach the suggestion agent.",
        }))
      )
      .finally(() => setSuggestLoading((prev) => ({ ...prev, [id]: false })));
  };

  // Shared by both the AI suggester and the manual "Add Custom KPI" form --
  // either way it's just another entry in the same extra_features list sent
  // to the same recompute endpoint, so both paths land in the same feature
  // grid and summary. Errors are set here but re-thrown so each caller can
  // decide what to do next (e.g. the KPI form keeps itself open on failure).
  const addFeature = (id: UploadSlotId, feature: FeatureSuggestion): Promise<void> => {
    const sessionId = auditReports[id]!.session_id;
    const nextAccepted = [...(accepted[id] ?? []), feature];
    return applyFeatures(sessionId, nextAccepted)
      .then((report) => {
        setReports((prev) => ({ ...prev, [id]: report }));
        setAccepted((prev) => ({ ...prev, [id]: nextAccepted }));
        setPreviews((prev) => ({ ...prev, [id]: undefined }));
      })
      .catch((err) => {
        setErrors((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not add that feature.",
        }));
        throw err;
      });
  };

  const acceptSuggestion = (id: UploadSlotId, suggestion: FeatureSuggestion) => {
    setApplyingSuggestionId((prev) => ({ ...prev, [id]: suggestion.id }));
    addFeature(id, suggestion)
      .catch(() => {})
      .finally(() => setApplyingSuggestionId((prev) => ({ ...prev, [id]: undefined })));
  };

  const addCustomKpi = (id: UploadSlotId, kpi: FeatureSuggestion) => {
    setAddingKpi((prev) => ({ ...prev, [id]: true }));
    addFeature(id, kpi)
      .then(() => setShowAddKpiForm((prev) => ({ ...prev, [id]: false })))
      .catch(() => {})
      .finally(() => setAddingKpi((prev) => ({ ...prev, [id]: false })));
  };

  if (AUDITED_SLOTS.every((id) => !files[id])) {
    return (
      <div className="features-page">
        <Header />
        <main className="features-page__main">
          <StepIndicator current={3} />
          <div className="features-page__empty">
            <p>No audited data yet.</p>
            <button type="button" className="features-page__btn features-page__btn--primary" onClick={() => navigate("/upload")}>
              Go to Upload
            </button>
          </div>
        </main>
      </div>
    );
  }

  if (slotsReady.length === 0) {
    return (
      <div className="features-page">
        <Header />
        <main className="features-page__main">
          <StepIndicator current={3} />
          <div className="features-page__empty">
            <p>Finish resolving the data audit before features can be computed.</p>
            <button type="button" className="features-page__btn features-page__btn--primary" onClick={() => navigate("/audit")}>
              Back to Audit
            </button>
          </div>
        </main>
      </div>
    );
  }

  if (!hasKpiFile) {
    return (
      <div className="features-page">
        <Header />
        <main className="features-page__main">
          <StepIndicator current={3} />
          <div className="features-page__empty">
            <p>
              No Customer KPI Profile has been uploaded. Feature definitions (what to compute, and any
              lookup tables like Country of Origin) live entirely in that file -- there's no default, so
              nothing is computed until it's uploaded.
            </p>
            <button type="button" className="features-page__btn features-page__btn--primary" onClick={() => navigate("/upload")}>
              Go to Upload
            </button>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="features-page">
      <Header />
      <main className="features-page__main">
        <StepIndicator current={3} />

        <PageHeader
          icon={<IconShieldCheck />}
          title="Feature Engineering"
          subtitle="Review the engineered features below, or ask the AI agent to suggest more from your data's own columns."
        />

        {defsLoading && <div className="features-page__loading">Reading feature definitions from {files.customerKpis!.name}…</div>}
        {defsError && <p className="features-page__error">{defsError}</p>}
        {defsSummary && (
          <p className="features-page__defs-summary">
            Loaded {defsSummary.feature_count} feature definition(s) from <strong>{defsSummary.filename}</strong>:{" "}
            {defsSummary.feature_names.join(", ")}.
          </p>
        )}

        {slotsReady.map((id) => {
          const slot = UPLOAD_SLOTS.find((s) => s.id === id)!;
          const report = reports[id];
          const preview = previews[id];
          const slotSuggestions = suggestions[id] ?? [];
          const slotAccepted = accepted[id] ?? [];
          const acceptedIds = new Set(slotAccepted.map((s) => s.id));
          const aiFeatureCount = report ? report.features.filter((f) => f.id.startsWith("ai_")).length : 0;
          const customFeatureCount = report ? report.features.filter((f) => f.id.startsWith("custom_")).length : 0;

          const bannerClauses: string[] = [];
          if (report) {
            if (report.features.length > 0) bannerClauses.push(`computed ${report.features.length} feature(s)`);
            if (aiFeatureCount > 0) bannerClauses.push(`${aiFeatureCount} of them AI-suggested`);
            if (customFeatureCount > 0) bannerClauses.push(`${customFeatureCount} added manually`);
            if (report.skipped_notes.length > 0) bannerClauses.push(`${report.skipped_notes.length} skipped`);
          }

          return (
            <section className="features-page__card" key={id}>
              <div className="features-page__card-head">
                <div className="features-page__card-head-left">
                  <h2 className="features-page__slot-title">{slot.title}</h2>
                  <span className="features-page__pill">FEATURE REPORT</span>
                </div>
                <div className="features-page__card-head-right">
                  <span className="features-page__filename">{files[id]!.name}</span>
                  {report && <span className="features-page__status-pill">Computed</span>}
                </div>
              </div>

              {loading[id] && <div className="features-page__loading">Computing features…</div>}
              {errors[id] && <p className="features-page__error">{errors[id]}</p>}

              {report && (
                <>
                  <div className="features-page__stat-row">
                    <StatTile icon={<IconDoc />} color="blue" value={report.row_count.toLocaleString()} label="Rows" />
                    <StatTile icon={<IconGrid />} color="teal" value={report.column_count} label="Columns" />
                    <StatTile icon={<IconSparkle />} color="purple" value={report.features.length} label="Features Added" />
                    {aiFeatureCount > 0 && (
                      <StatTile icon={<IconSparkle />} color="amber" value={aiFeatureCount} label="AI Suggested" />
                    )}
                    {customFeatureCount > 0 && (
                      <StatTile icon={<IconClipboard />} color="blue" value={customFeatureCount} label="Custom KPIs" />
                    )}
                    {report.skipped_notes.length > 0 && (
                      <StatTile icon={<IconWarnTriangle />} color="error" value={report.skipped_notes.length} label="Skipped" />
                    )}
                  </div>

                  {report.features.length > 0 && (
                    <div className="features-page__banner">
                      <span className="features-page__banner-icon">✓</span>
                      <div>
                        <p className="features-page__banner-title">Feature Engineering Complete</p>
                        <p className="features-page__banner-text">
                          {joinClauses(bannerClauses)} Data is ready for reporting and downstream analysis.
                        </p>
                      </div>
                    </div>
                  )}

                  <div className="features-page__ai-panel">
                    <div className="features-page__ai-panel-head">
                      <div>
                        <h3 className="features-page__ai-panel-title">
                          <IconSparkle /> AI Feature Suggestions
                        </h3>
                        <p className="features-page__ai-panel-hint">
                          The agent looks at this data's column names and proposes new fields it can
                          compute -- you choose which ones to add.
                        </p>
                      </div>
                      <button
                        type="button"
                        className="features-page__btn features-page__btn--primary"
                        disabled={suggestLoading[id]}
                        onClick={() => runSuggest(id)}
                      >
                        {suggestLoading[id] ? "Thinking…" : slotSuggestions.length > 0 ? "Suggest More" : "Suggest Features"}
                      </button>
                    </div>

                    {suggestError[id] && <p className="features-page__error">{suggestError[id]}</p>}

                    {slotSuggestions.length > 0 && (
                      <div className="features-page__ai-grid">
                        {slotSuggestions.map((s) => (
                          <FeatureSuggestionCard
                            key={s.id}
                            suggestion={s}
                            added={acceptedIds.has(s.id)}
                            busy={applyingSuggestionId[id] === s.id}
                            onAdd={() => acceptSuggestion(id, s)}
                          />
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="features-page__custom-kpi">
                    <div className="features-page__custom-kpi-head">
                      <div>
                        <h3 className="features-page__custom-kpi-title">Add a Custom KPI</h3>
                        <p className="features-page__custom-kpi-hint">
                          Define your own duration, ratio, or month-extraction feature straight from this
                          data's columns -- no need to edit and re-upload the Customer KPI Profile file.
                        </p>
                      </div>
                      <button
                        type="button"
                        className="features-page__btn features-page__btn--secondary"
                        onClick={() => setShowAddKpiForm((prev) => ({ ...prev, [id]: !prev[id] }))}
                      >
                        {showAddKpiForm[id] ? "Cancel" : "+ Add Custom KPI"}
                      </button>
                    </div>
                    {showAddKpiForm[id] && (
                      <AddKpiForm
                        columns={report.columns}
                        busy={!!addingKpi[id]}
                        onAdd={(kpi) => addCustomKpi(id, kpi)}
                        onCancel={() => setShowAddKpiForm((prev) => ({ ...prev, [id]: false }))}
                      />
                    )}
                  </div>

                  {report.features.length === 0 ? (
                    <p className="features-page__none">
                      None of the uploaded feature definitions could be computed against this data.
                    </p>
                  ) : (
                    <div className="features-page__grid">
                      {report.features.map((f) => (
                        <FeatureCard key={f.id} feature={f} />
                      ))}
                    </div>
                  )}

                  {report.skipped_notes.length > 0 && (
                    <ul className="features-page__skipped">
                      {report.skipped_notes.map((note, idx) => (
                        <li key={idx}>{note}</li>
                      ))}
                    </ul>
                  )}

                  {report.features.length > 0 && (
                    <div className="features-page__summary">
                      <p className="features-page__summary-title">
                        ✓ {report.features.length} feature{report.features.length === 1 ? "" : "s"} added in total
                      </p>
                      <ul className="features-page__summary-list">
                        {report.features.map((f) => (
                          <li key={f.id}>
                            <span className="features-page__summary-name">{f.name}</span>
                            <code className="features-page__summary-col">{f.output_column}</code>
                            {f.id.startsWith("ai_") && <span className="features-page__summary-ai-tag">AI</span>}
                            {f.id.startsWith("custom_") && <span className="features-page__summary-custom-tag">Custom</span>}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <div className="features-page__row-actions">
                    <button type="button" className="features-page__link-btn" onClick={() => togglePreview(id)}>
                      {previewOpen[id] ? "Hide" : "View"} audited + engineered data ({report.row_count.toLocaleString()} rows, {report.column_count} columns)
                    </button>
                    <a className="features-page__download-link" href={downloadCleansedFileUrl(report.session_id)} download>
                      <IconDownload />
                      Download engineered file
                    </a>
                  </div>

                  {previewOpen[id] && (preview ? <DataPreviewTable preview={preview} /> : <div className="features-page__loading">Loading preview…</div>)}
                </>
              )}
            </section>
          );
        })}

        <div className="features-page__actions">
          <button type="button" className="features-page__btn features-page__btn--secondary" onClick={() => navigate("/audit")}>
            Back to Audit
          </button>
        </div>
      </main>
    </div>
  );
}
