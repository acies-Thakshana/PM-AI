import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import StatTile from "../components/StatTile";
import FeatureCard from "../components/FeatureCard";
import FeatureDetailModal from "../components/FeatureDetailModal";
import Modal from "../components/Modal";
import AddKpiForm from "../components/AddKpiForm";
import DataPreviewTable from "../components/DataPreviewTable";
import { IconDoc, IconGrid, IconSparkle, IconWarnTriangle, IconShieldCheck, IconDownload, IconClipboard, IconChevronLeft, IconChevronRight } from "../components/icons";
import {
  applyFeatures,
  downloadCleansedFileUrl,
  fetchPreview,
  uploadFeatureDefinitions,
  AuditApiError,
  type CustomFeature,
  type DataPreview,
  type FeatureDefinitionsSummary,
  type FeatureReport,
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
type AcceptedState = Partial<Record<UploadSlotId, CustomFeature[]>>;

export default function FeaturesPage({ files, auditReports }: FeaturesPageProps) {
  const navigate = useNavigate();
  const [reports, setReports] = useState<FeatureReportsState>({});
  const [loading, setLoading] = useState<LoadingState>({});
  const [errors, setErrors] = useState<ErrorsState>({});
  const [previews, setPreviews] = useState<PreviewsState>({});
  const [previewOpen, setPreviewOpen] = useState<PreviewOpenState>({});

  const [accepted, setAccepted] = useState<AcceptedState>({});
  const [showAddKpiForm, setShowAddKpiForm] = useState<LoadingState>({});
  const [addingKpi, setAddingKpi] = useState<LoadingState>({});

  const [defsSummary, setDefsSummary] = useState<FeatureDefinitionsSummary | null>(null);
  const [defsLoading, setDefsLoading] = useState(false);
  const [defsError, setDefsError] = useState<string | null>(null);

  const [openFeature, setOpenFeature] = useState<{ slotId: UploadSlotId; featureId: string } | null>(null);

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
      if (reports[id] || loading[id] || errors[id]) continue;
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

  const addCustomKpi = (id: UploadSlotId, kpi: CustomFeature) => {
    const sessionId = auditReports[id]!.session_id;
    const nextAccepted = [...(accepted[id] ?? []), kpi];
    setAddingKpi((prev) => ({ ...prev, [id]: true }));
    applyFeatures(sessionId, nextAccepted)
      .then((report) => {
        setReports((prev) => ({ ...prev, [id]: report }));
        setAccepted((prev) => ({ ...prev, [id]: nextAccepted }));
        setPreviews((prev) => ({ ...prev, [id]: undefined }));
        setShowAddKpiForm((prev) => ({ ...prev, [id]: false }));
      })
      .catch((err) =>
        setErrors((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not add that feature.",
        }))
      )
      .finally(() => setAddingKpi((prev) => ({ ...prev, [id]: false })));
  };

  if (AUDITED_SLOTS.every((id) => !files[id])) {
    return (
      <div className="features-page">
        <Header subtitle="Feature Engineering" />
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
        <Header subtitle="Feature Engineering" />
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
        <Header subtitle="Feature Engineering" />
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
      <Header subtitle="Feature Engineering" />
      <main className="features-page__main">
        <StepIndicator current={3} />

        <PageHeader
          icon={<IconShieldCheck />}
          title="Feature Engineering"
          subtitle="Review the engineered features below, or add a custom KPI of your own."
        />

        {defsLoading && <div className="features-page__loading">Reading feature definitions from {files.customerKpis!.name}…</div>}
        {defsError && <p className="features-page__error">{defsError}</p>}

        {slotsReady.map((id) => {
          const slot = UPLOAD_SLOTS.find((s) => s.id === id)!;
          const report = reports[id];
          const preview = previews[id];
          const slotAccepted = accepted[id] ?? [];
          const slotFormulas = Object.fromEntries(slotAccepted.map((s) => [s.id, s.formula]));
          const customFeatureCount = report ? report.features.filter((f) => f.id.startsWith("custom_")).length : 0;

          const customKpiSection = report && (
            <div className="features-page__custom-kpi">
              <div className="features-page__custom-kpi-head">
                <div className="features-page__panel-head-text">
                  <span className="features-page__panel-icon features-page__panel-icon--blue">
                    <IconClipboard />
                  </span>
                  <div>
                    <h3 className="features-page__custom-kpi-title">Add a Custom KPI</h3>
                    <p className="features-page__custom-kpi-hint">
                      Define your own duration, ratio, or month-extraction feature straight from this
                      data's columns -- no need to edit and re-upload the Customer KPI Profile file.
                    </p>
                  </div>
                </div>
              </div>
              <button
                type="button"
                className="features-page__btn features-page__btn--secondary features-page__panel-btn"
                onClick={() => setShowAddKpiForm((prev) => ({ ...prev, [id]: true }))}
              >
                + Add Custom KPI
              </button>
              {showAddKpiForm[id] && (
                <Modal title="Add a Custom KPI" onClose={() => setShowAddKpiForm((prev) => ({ ...prev, [id]: false }))}>
                  <AddKpiForm
                    columns={report.columns}
                    busy={!!addingKpi[id]}
                    onAdd={(kpi) => addCustomKpi(id, kpi)}
                    onCancel={() => setShowAddKpiForm((prev) => ({ ...prev, [id]: false }))}
                  />
                </Modal>
              )}
            </div>
          );

          return (
            <section className="features-page__card" key={id}>
              <div className="features-page__card-head">
                <div className="features-page__card-head-left">
                  <h2 className="features-page__slot-title">{slot.title}</h2>
                  <span className="features-page__pill">FEATURE REPORT</span>
                  {report && <span className="features-page__status-pill">Computed</span>}
                </div>
                <span className="features-page__filename">{files[id]!.name}</span>
              </div>

              {loading[id] && <div className="features-page__loading">Computing features…</div>}
              {errors[id] && <p className="features-page__error">{errors[id]}</p>}

              {report && (
                <>
                  <div className="features-page__stat-row">
                    <StatTile icon={<IconDoc />} color="blue" value={report.row_count.toLocaleString()} label="Rows" />
                    <StatTile icon={<IconGrid />} color="teal" value={report.column_count} label="Columns" />
                    <StatTile icon={<IconSparkle />} color="purple" value={report.features.length} label="Features Added" />
                    {customFeatureCount > 0 && (
                      <StatTile icon={<IconClipboard />} color="blue" value={customFeatureCount} label="Custom KPIs" />
                    )}
                    {report.skipped_notes.length > 0 && (
                      <StatTile icon={<IconWarnTriangle />} color="error" value={report.skipped_notes.length} label="Skipped" />
                    )}
                  </div>

                  {report.features.length > 0 && (
                    <div className="features-page__summary">
                      <p className="features-page__summary-title">
                        ✓ {report.features.length} feature{report.features.length === 1 ? "" : "s"} added in total
                      </p>
                      {[
                        { label: "Defined", items: report.features.filter((f) => !f.id.startsWith("custom_")) },
                        { label: "User Added", items: report.features.filter((f) => f.id.startsWith("custom_")) },
                      ]
                        .filter((group) => group.items.length > 0)
                        .map((group) => (
                          <div className="features-page__summary-group" key={group.label}>
                            <span className="features-page__summary-group-label">{group.label}</span>
                            <ul className="features-page__summary-list">
                              {group.items.map((f) => (
                                <li key={f.id}>
                                  <button
                                    type="button"
                                    className="features-page__summary-item"
                                    onClick={() => setOpenFeature({ slotId: id, featureId: f.id })}
                                  >
                                    <span className="features-page__summary-name">{f.name}</span>
                                    <code className="features-page__summary-col">{f.output_column}</code>
                                  </button>
                                </li>
                              ))}
                            </ul>
                          </div>
                        ))}
                    </div>
                  )}

                  {report.features.length === 0 ? (
                    <p className="features-page__none">
                      None of the uploaded feature definitions could be computed against this data.
                    </p>
                  ) : (
                    <>
                      <h3 className="features-page__section-title">
                        <IconSparkle /> Computed Features
                      </h3>
                      <div className="features-page__grid">
                        {report.features.map((f, idx) => (
                          <FeatureCard
                            key={f.id}
                            feature={f}
                            colorIndex={idx}
                            formula={slotFormulas[f.id]}
                            onExpand={() => setOpenFeature({ slotId: id, featureId: f.id })}
                          />
                        ))}
                      </div>
                    </>
                  )}

                  {report.skipped_notes.length > 0 && (
                    <ul className="features-page__skipped">
                      {report.skipped_notes.map((note, idx) => (
                        <li key={idx}>{note}</li>
                      ))}
                    </ul>
                  )}

                  {customKpiSection}

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
          <button type="button" className="features-page__btn features-page__btn--secondary features-page__nav-btn" onClick={() => navigate("/audit")}>
            <IconChevronLeft /> Back to Audit
          </button>
          <button type="button" className="features-page__btn features-page__btn--primary features-page__nav-btn" onClick={() => navigate("/analysis")}>
            Continue to Analysis <IconChevronRight />
          </button>
        </div>
      </main>

      {openFeature &&
        (() => {
          const openFeatureData = reports[openFeature.slotId]?.features.find((f) => f.id === openFeature.featureId);
          if (!openFeatureData) return null;
          const openFeatureFormula = (accepted[openFeature.slotId] ?? []).find((s) => s.id === openFeature.featureId)?.formula;
          return <FeatureDetailModal feature={openFeatureData} formula={openFeatureFormula} onClose={() => setOpenFeature(null)} />;
        })()}
    </div>
  );
}
