import { Spinner } from "../components/ThinkingLoader";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import { IconChevronLeft } from "../components/icons";
import SourceSelect from "../components/SourceSelect";
import FileUploadCard from "../components/FileUploadCard";
import StepIndicator from "../components/StepIndicator";
import ClientBriefInput from "../components/ClientBriefInput";
import SwpConfigPanel from "../components/SwpConfigPanel";
import { UPLOAD_SLOTS, AUDITED_SLOTS, isAudited } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { FilesState } from "../App";
import type { BriefState } from "../components/ClientBriefInput";
import type { SwpTripsResponse } from "../api/swp";
import { selectedTrips } from "../utils/swpTrips";
import type { SwpConfigState } from "../utils/swpTrips";
import { uploadOnly } from "../api/audit";
import { finalizeBrief } from "../api/brief";
import { hasBrief } from "../context/plannerSkipped";
import type { DataSource } from "../context/plannerSkipped";
import "./UploadPage.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

type ErrorsState = Partial<Record<UploadSlotId, string>>;

// Bundled example files (see backend/data/samples/, served statically at /samples/* by main.py) for the
// "Add all samples" button in upload mode. Not every slot has a sample; coldstream is left for the user.
const SAMPLE_FILES: { id: UploadSlotId; filename: string; mimeType: string }[] = [
  { id: "sensiwatch", filename: "sensiwatch_sample.xlsm", mimeType: "application/vnd.ms-excel.sheet.macroEnabled.12" },
  { id: "customerKpis", filename: "customer_kpi_profile_sample.json", mimeType: "application/json" },
  { id: "analysisProfile", filename: "analysis_profile_sample.json", mimeType: "application/json" },
];

// The API mode brings the trip data in itself; the two JSON profiles are files in both modes.
const PROFILE_SLOTS = UPLOAD_SLOTS.filter((s) => !isAudited(s.id));

interface UploadPageProps {
  files: FilesState;
  brief: BriefState;
  dataSource: DataSource;
  onSourceChange: (source: DataSource) => void;
  config: SwpConfigState;
  onConfigChange: (config: SwpConfigState) => void;
  trips: SwpTripsResponse | null;
  onTripsChange: (trips: SwpTripsResponse | null) => void;
  onSelect: (id: UploadSlotId, file: File) => void;
  onRemove: (id: UploadSlotId) => void;
  onClearAll: () => void;
  onBriefChange: (state: BriefState) => void;
  onUploadComplete: (sessionIds: Partial<Record<UploadSlotId, string>>, briefSignature: string) => void;
  /** The sessions already created from the files now selected (cleared whenever a file changes). */
  uploadedSessionIds: Partial<Record<UploadSlotId, string>>;
  uploadedBriefSignature: string | null;
}

export default function UploadPage({
  files,
  brief,
  dataSource,
  onSourceChange,
  config,
  onConfigChange,
  trips,
  onTripsChange,
  onSelect,
  onRemove,
  onClearAll,
  onBriefChange,
  onUploadComplete,
  uploadedSessionIds,
  uploadedBriefSignature,
}: UploadPageProps) {
  const navigate = useNavigate();
  const [errors, setErrors] = useState<ErrorsState>({});
  const [highlighted, setHighlighted] = useState<UploadSlotId | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [briefError, setBriefError] = useState<string | undefined>();
  const [samplesLoading, setSamplesLoading] = useState(false);
  const cardRefs: Partial<Record<UploadSlotId, HTMLDivElement | null>> = {};

  const apiMode = dataSource === "api";
  const chosen = selectedTrips(trips, config);
  const apiReady = !!trips && chosen.length > 0 && chosen.length <= trips.max_trips && config.sensors.length > 0;

  const handleSelect = (id: UploadSlotId, file: File) => {
    onSelect(id, file);
    setErrors((prev) => ({ ...prev, [id]: undefined }));
  };

  const handleAddAllSamples = async () => {
    setSamplesLoading(true);
    setUploadError(null);
    try {
      const loaded = await Promise.all(
        SAMPLE_FILES.map(async ({ id, filename, mimeType }) => {
          const response = await fetch(`${API_BASE_URL}/samples/${filename}`);
          if (!response.ok) throw new Error(`Could not load sample "${filename}" (${response.status}).`);
          const blob = await response.blob();
          return { id, file: new File([blob], filename, { type: mimeType }) };
        })
      );
      for (const { id, file } of loaded) handleSelect(id, file);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Could not load the sample files.");
    } finally {
      setSamplesLoading(false);
    }
  };

  const checkBrief = (): boolean => {
    const missing = !brief.rawText.trim();
    setBriefError(missing ? "Client brief is required." : undefined);
    if (missing) window.scrollTo({ top: 0, behavior: "smooth" });
    return !missing;
  };

  // API mode: the choices are made here; the trips themselves are loaded after the Trips page.
  const handleContinueApi = () => {
    if (!checkBrief() || !apiReady) return;
    navigate("/trips");
  };

  const handleContinueUpload = async () => {
    const nextErrors: ErrorsState = {};
    for (const slot of UPLOAD_SLOTS) {
      if (slot.required && !files[slot.id]) nextErrors[slot.id] = `${slot.title} is required.`;
    }
    setErrors(nextErrors);
    if (!checkBrief() || Object.keys(nextErrors).length > 0) return;

    // Same files and the same brief as the sessions we already have: carry on with them. Uploading again
    // would create new sessions and run the Planner (and everything after it) all over again.
    const briefSignature = `${brief.rawText} ${brief.finalText}`;
    const haveSessions = AUDITED_SLOTS.some((id) => uploadedSessionIds[id]);
    const allUploaded = AUDITED_SLOTS.every((id) => !files[id] || uploadedSessionIds[id]);
    if (haveSessions && allUploaded && briefSignature === uploadedBriefSignature) {
      navigate(hasBrief(brief) ? "/planner" : "/audit");
      return;
    }

    setUploading(true);
    setUploadError(null);
    try {
      const sessionIds: Partial<Record<UploadSlotId, string>> = {};
      for (const id of AUDITED_SLOTS) {
        const file = files[id];
        if (!file) continue;
        const result = await uploadOnly(id, file);
        sessionIds[id] = result.session_id;
      }
      const sessionIdsList = Object.values(sessionIds).filter((s): s is string => Boolean(s));
      if (sessionIdsList.length > 0) await finalizeBrief(brief, files, sessionIdsList);

      onUploadComplete(sessionIds, briefSignature);
      // No client brief = nothing for the Planner to plan: go straight to the data Audit.
      navigate(hasBrief(brief) ? "/planner" : "/audit");
    } catch (err: unknown) {
      setUploadError(err instanceof Error ? err.message : "Upload failed. Is the backend running?");
    } finally {
      setUploading(false);
    }
  };

  const handleContinue = apiMode ? handleContinueApi : handleContinueUpload;
  const continueLabel = apiMode ? "Continue to Trips" : "Upload & Continue";
  const continueDisabled = uploading || (apiMode && !apiReady);

  // A full page load (not a router navigation) so the app starts completely fresh on the Get Started page.
  const handleBack = () => window.location.assign("/");

  const handleJumpTo = (id: UploadSlotId) => {
    cardRefs[id]?.scrollIntoView({ behavior: "smooth", block: "center" });
    setHighlighted(id);
    setTimeout(() => setHighlighted((prev) => (prev === id ? null : prev)), 1600);
  };

  const selectedCount = Object.values(files).filter(Boolean).length;
  const slots = apiMode ? PROFILE_SLOTS : UPLOAD_SLOTS;

  const buttons = (
    <div className="upload-page__buttons">
      {!apiMode && (
        <button
          type="button"
          className="btn btn--secondary"
          onClick={handleAddAllSamples}
          disabled={uploading || samplesLoading}
          title="Fills every slot with a bundled example file, so you can skip hunting one down each time you try the app."
        >
          {samplesLoading ? <><Spinner />Loading samples…</> : "Add all samples"}
        </button>
      )}
      <button type="button" className="btn btn--secondary" onClick={onClearAll} disabled={uploading}>
        Clear All
      </button>
      <button type="button" className="btn btn--primary" onClick={handleContinue} disabled={continueDisabled}>
        {uploading ? <><Spinner />Uploading…</> : continueLabel}
      </button>
    </div>
  );

  return (
    <div className="upload-page">
      <Header subtitle="Data Configuration" />
      <main className="upload-page__main">
        <StepIndicator current={1} />

        <ClientBriefInput
          value={brief}
          error={briefError}
          onChange={(state) => {
            setBriefError(undefined);
            onBriefChange(state);
          }}
        />

        <div className="upload-page__intro">
          <h1 className="upload-page__heading">Source Data</h1>
          <div className="source-toggle" role="tablist" aria-label="Where the trip data comes from">
            {(["api", "upload"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                role="tab"
                aria-selected={dataSource === mode}
                className={`source-toggle__option${dataSource === mode ? " source-toggle__option--active" : ""}`}
                onClick={() => onSourceChange(mode)}
                disabled={uploading}
              >
                {mode === "api" ? "Configure (SWP API)" : "Upload files"}
              </button>
            ))}
          </div>
          <p className="upload-page__lede">
            {apiMode
              ? "Trip data is pulled from the SWP API. All trips of the program are fetched first; choose the departure dates, the sensors and the trips to bring in. Nothing is written back to SWP."
              : "Provide the SensiWatch export and a client brief to begin. ColdStream data, the Customer KPI Profile, and the Analysis Profile are optional but improve triage and reporting accuracy. SensiWatch and ColdStream files go through the data audit."}
          </p>
        </div>

        {!apiMode && (
          <div className="upload-page__search-row">
            <SourceSelect files={files} onSelect={handleJumpTo} />
          </div>
        )}

        {uploadError && <div className="upload-page__error">{uploadError}</div>}

        {apiMode && (
          <SwpConfigPanel
            config={config}
            onConfigChange={onConfigChange}
            trips={trips}
            onTripsChange={onTripsChange}
            disabled={uploading}
          />
        )}

        <div className="upload-page__actions">
          <div className="upload-page__left">
            <button type="button" className="btn btn--secondary" onClick={handleBack} disabled={uploading}>
              <IconChevronLeft /> Back
            </button>
            <span className="upload-page__count">
              {apiMode ? `${chosen.length} trip(s) selected` : `${selectedCount} of ${UPLOAD_SLOTS.length} files selected`}
            </span>
          </div>
          {buttons}
        </div>

        {apiMode && <h2 className="upload-page__subheading">Optional profiles</h2>}

        <div className="upload-page__grid">
          {slots.map((slot) => (
            <div
              key={slot.id}
              ref={(el) => {
                cardRefs[slot.id] = el;
              }}
            >
              <FileUploadCard
                config={slot}
                file={files[slot.id]}
                error={errors[slot.id]}
                highlighted={highlighted === slot.id}
                onSelect={(file) => handleSelect(slot.id, file)}
                onRemove={() => onRemove(slot.id)}
              />
            </div>
          ))}
        </div>

        <div className="upload-page__actions upload-page__actions--bottom">
          <button type="button" className="btn btn--secondary" onClick={handleBack} disabled={uploading}>
            <IconChevronLeft /> Back
          </button>
          <button type="button" className="btn btn--primary" onClick={handleContinue} disabled={continueDisabled}>
            {uploading ? <><Spinner />Uploading…</> : continueLabel}
          </button>
        </div>
      </main>
    </div>
  );
}
