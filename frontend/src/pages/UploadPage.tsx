import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import FileUploadCard from "../components/FileUploadCard";
import ChatComposer from "../components/ChatComposer";
import type { ChatAttachment } from "../components/ChatComposer";
import ChatMessage from "../components/ChatMessage";
import ClientBriefInput from "../components/ClientBriefInput";
import SwpConfigPanel from "../components/SwpConfigPanel";
import { UPLOAD_SLOTS, AUDITED_SLOTS, isAudited } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { FilesState } from "../App";
import type { BriefState } from "../components/ClientBriefInput";
import type { SwpTripsResponse, TripEdits } from "../api/swp";
import { loadTrips } from "../api/swp";
import ApiProgress from "../components/ApiProgress";
import { selectedTrips } from "../utils/swpTrips";
import type { SwpConfigState } from "../utils/swpTrips";
import { uploadOnly } from "../api/audit";
import { finalizeBrief } from "../api/brief";
import { hasBrief } from "../context/plannerSkipped";
import type { DataSource } from "../context/plannerSkipped";
import "../components/ChatMessage.css";
import "../components/StageChat.css";
import { PlannerThread, usePlannerChat } from "./PlannerPage";
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
// The trip files, used when the data comes from uploads instead of the SWP API.
const TRIP_SLOTS = UPLOAD_SLOTS.filter((s) => isAudited(s.id));

interface UploadPageProps {
  files: FilesState;
  brief: BriefState;
  dataSource: DataSource;
  onSourceChange: (source: DataSource) => void;
  config: SwpConfigState;
  onConfigChange: (config: SwpConfigState) => void;
  trips: SwpTripsResponse | null;
  onTripsChange: (trips: SwpTripsResponse | null) => void;
  edits: TripEdits;
  onEditsChange: (edits: TripEdits) => void;
  /** The arrived trips were loaded from the store into one audit session. */
  onLoadComplete: (sessionId: string, label: File, signature: string) => void;
  onSelect: (id: UploadSlotId, file: File) => void;
  onRemove: (id: UploadSlotId) => void;
  /** The audit session of the program in play: the Planner runs on it as soon as there is one. */
  sessionId: string | null;
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
  edits,
  onEditsChange,
  onLoadComplete,
  onSelect,
  onRemove,
  sessionId,
  onBriefChange,
  onUploadComplete,
  uploadedSessionIds,
  uploadedBriefSignature,
}: UploadPageProps) {
  const navigate = useNavigate();
  const [errors, setErrors] = useState<ErrorsState>({});
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [briefError, setBriefError] = useState<string | undefined>();
  const [samplesLoading, setSamplesLoading] = useState(false);
  const [progressId, setProgressId] = useState<string | null>(null);
  const briefRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  // Where the fetched trips are shown: their own message, once there are trips.
  const [resultsHost, setResultsHost] = useState<HTMLDivElement | null>(null);
  // The PM's replies in this conversation before planning starts, and what the assistant answered.
  interface Turn {
    user: string;
    reply?: string;
    editor?: boolean;
  }
  const [turns, setTurns] = useState<Turn[]>([]);
  const [showEditor, setShowEditor] = useState(false);
  const [editorHost, setEditorHost] = useState<HTMLDivElement | null>(null);

  // With a client brief, the Planner starts in this same conversation as soon as the data is loaded.
  const planning = !!sessionId && hasBrief(brief);
  const planner = usePlannerChat(planning ? sessionId : null, files);

  // When the Planner starts, the conversation moves down to it.
  useEffect(() => {
    if (planning) endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [planning]);

  const apiMode = dataSource === "api";
  // Only trips fetched for the program id now typed count.
  const tripsForProgram = trips && trips.program_id === config.programId.trim() ? trips : null;
  // Only arrived trips go on (counting status changes made here).
  const chosen = selectedTrips(tripsForProgram, config, edits);
  const apiReady =
    !!tripsForProgram && chosen.length > 0 && chosen.length <= tripsForProgram.max_trips &&
    config.sensors.some((s) => s === "Temperature" || s === "Light");

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
    if (missing) briefRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    return !missing;
  };

  // API mode: load the chosen arrived trips (from the store, no API calls for trips already fetched) and go on.
  const handleContinueApi = async () => {
    if (!checkBrief() || !apiReady) return;
    const ids = chosen.map((t) => t.trip_id);
    // Same choices and the same brief as the session we already have: carry on with it instead of loading (and
    // planning) all over again.
    const signature = JSON.stringify([brief.rawText, brief.finalText, config.programId, config.sensors, ids, edits]);
    if (uploadedSessionIds.sensiwatch && signature === uploadedBriefSignature) {
      if (!hasBrief(brief)) navigate("/audit");
      return;
    }
    setUploading(true);
    setUploadError(null);
    const progress = crypto.randomUUID();
    setProgressId(progress);
    try {
      const loaded = await loadTrips({
        program_id: config.programId.trim() || null,
        progress_id: progress,
        trip_ids: ids,
        sensors: config.sensors,
        edits: Object.fromEntries(ids.filter((id) => edits[id]).map((id) => [id, edits[id]])),
      });
      // The Planner and the later steps only look at the file's name, so a stand-in carries the label.
      const label = new File([], loaded.filename);
      await finalizeBrief(brief, { ...files, sensiwatch: label }, [loaded.session_id]);
      onLoadComplete(loaded.session_id, label, signature);
      if (!hasBrief(brief)) navigate("/audit");
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Could not load the trips. Is the backend running?");
    } finally {
      setUploading(false);
      setProgressId(null);
    }
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
      if (!hasBrief(brief)) navigate("/audit");
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
      if (!hasBrief(brief)) navigate("/audit");
    } catch (err: unknown) {
      setUploadError(err instanceof Error ? err.message : "Upload failed. Is the backend running?");
    } finally {
      setUploading(false);
    }
  };

  const scrollDown = () => window.setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }), 60);

  // "Load the arrived trips" as a chat reply: it shows as the PM's message, then the assistant gets on with it.
  const requestLoad = (said?: string) => {
    setTurns((prev) => [...prev, { user: said ?? `Load the ${chosen.length} arrived trip${chosen.length === 1 ? "" : "s"}` }]);
    scrollDown();
    void handleContinueApi();
  };

  const requestEdit = (said?: string) => {
    if (showEditor) return;
    setShowEditor(true);
    setTurns((prev) => [
      ...prev,
      {
        user: said ?? "Let me review and edit the trips",
        reply: "Here they are. Mark an in-transit trip as arrived to include it (this changes the app only, not SWP), or paste trip IDs to load just some.",
        editor: true,
      },
    ]);
    scrollDown();
  };

  // Before planning, the message box takes a short "load" or "show me the trips" as a reply to the assistant;
  // anything else goes into the client brief (the Planner reads it from there). Once the Planner has started, it asks
  // the Planner for different or more suggestions.
  const handleSend = (text: string) => {
    if (planning) {
      void planner.handleRequestMore(text);
      return;
    }
    const short = text.trim().split(/\s+/).length <= 8;
    if (short && apiMode && tripsForProgram && /\b(load|continue|proceed|go ahead)\b/i.test(text)) {
      requestLoad(text);
      return;
    }
    if (short && apiMode && tripsForProgram && /\b(edit|review|show|list)\b/i.test(text) && /\btrips?\b/i.test(text)) {
      requestEdit(text);
      return;
    }
    const joined = brief.rawText.trim() ? `${brief.rawText.trim()}\n\n${text}` : text;
    setBriefError(undefined);
    onBriefChange({ ...brief, rawText: joined, finalText: joined, isEnglish: true });
    setTurns((prev) => [...prev, { user: text, reply: "Added to the client brief. I will read it when I plan." }]);
    scrollDown();
  };

  const handleContinue = apiMode ? handleContinueApi : handleContinueUpload;
  const continueDisabled = uploading || (apiMode && !apiReady);

  const attachments: ChatAttachment[] = PROFILE_SLOTS.map((slot) => ({
    id: slot.id,
    label: slot.title,
    accept: slot.accept,
    fileName: files[slot.id]?.name,
  }));

  const renderSlot = (slot: (typeof UPLOAD_SLOTS)[number]) => (
    <FileUploadCard
      key={slot.id}
      config={slot}
      file={files[slot.id]}
      error={errors[slot.id]}
      onSelect={(file) => handleSelect(slot.id, file)}
      onRemove={() => onRemove(slot.id)}
    />
  );

  return (
    <div className="upload-page chat-page">
      <div className="chat-page__scroll">
        <div className="chat-page__thread">
          <ChatMessage>
            <p>
              Hi, I&apos;m your program manager assistant. Tell me about the program and I will pull the trips, suggest
              what to build, and take you through the audit.
            </p>
            <div className="chat-card" ref={briefRef}>
              <div className="chat-card__head">
                Program setup
                <span>{apiMode ? "SWP API" : "Uploaded files"}</span>
              </div>
              <div className="chat-card__body">
                <div>
                  <span className="chat-card__label">
                    Client brief <span className="cb__badge-required">Required</span>
                  </span>
                  <ClientBriefInput
                    value={brief}
                    error={briefError}
                    onChange={(state) => {
                      setBriefError(undefined);
                      onBriefChange(state);
                    }}
                  />
                </div>

                <div>
                  <span className="chat-card__label">Source data</span>
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
                        {mode === "api" ? "SWP API" : "Upload files"}
                      </button>
                    ))}
                  </div>
                  <p className="upload-page__lede">
                    {apiMode
                      ? "Every trip of the program is fetched first. Then choose the departure dates and the sensors. Nothing is written back to SWP."
                      : "Upload the SensiWatch export to begin. The ColdStream export is optional. Both files go through the data audit."}
                  </p>
                </div>

                {apiMode ? (
                  <SwpConfigPanel
                    config={config}
                    onConfigChange={onConfigChange}
                    trips={trips}
                    onTripsChange={onTripsChange}
                    edits={edits}
                    onEditsChange={onEditsChange}
                    disabled={uploading}
                    resultsHost={resultsHost}
                    editorHost={editorHost}
                    showEditor={showEditor}
                  />
                ) : (
                  <div className="upload-page__grid">{TRIP_SLOTS.map(renderSlot)}</div>
                )}
              </div>
            </div>
          </ChatMessage>

          {apiMode && tripsForProgram && (
            <ChatMessage>
              <div className="chat-msg__host" ref={setResultsHost} />
            </ChatMessage>
          )}

          {turns.map((turn, i) => (
            <div key={i} className="chat-page__turn">
              <ChatMessage from="user">{turn.user}</ChatMessage>
              {turn.reply && (
                <ChatMessage>
                  <p>{turn.reply}</p>
                  {turn.editor && <div className="chat-msg__host" ref={setEditorHost} />}
                </ChatMessage>
              )}
            </div>
          ))}

          {uploading && apiMode && (
            <ChatMessage>
              <ApiProgress progressId={progressId} fallback="Loading the arrived trips…" />
            </ChatMessage>
          )}

          {uploadError && (
            <ChatMessage>
              <div className="upload-page__error">{uploadError}</div>
            </ChatMessage>
          )}

          {planning && <PlannerThread planner={planner} />}

          <div ref={endRef} />
        </div>
      </div>

      <div className="chat-page__dock">
        <div className="chat-page__dock-inner">
          <div className="stage-chips">
            {planning && planner.error && !planner.result && (
              <button type="button" className="stage-chip stage-chip--main" onClick={planner.retry}>
                Try again
              </button>
            )}
            {planning && planner.result && (
              <>
                <button type="button" className="stage-chip stage-chip--main" disabled={planner.saving} onClick={() => void planner.handleProceed()}>
                  Continue to Audit
                </button>
                <button type="button" className="stage-chip" disabled={planner.moreLoading} onClick={() => void planner.handleRequestMore()}>
                  Suggest more of each
                </button>
              </>
            )}
            {!planning && apiMode && tripsForProgram && (
              <>
                <button type="button" className="stage-chip stage-chip--main" disabled={continueDisabled} onClick={() => requestLoad()}>
                  Load {chosen.length} arrived trip{chosen.length === 1 ? "" : "s"}
                </button>
                {!showEditor && (
                  <button type="button" className="stage-chip" disabled={uploading} onClick={() => requestEdit()}>
                    Review and edit the trips
                  </button>
                )}
              </>
            )}
            {!planning && !apiMode && (
              <>
                <button type="button" className="stage-chip stage-chip--main" disabled={continueDisabled} onClick={() => handleContinue()}>
                  Upload and continue
                </button>
                <button type="button" className="stage-chip" disabled={uploading || samplesLoading} onClick={() => void handleAddAllSamples()}>
                  {samplesLoading ? "Loading samples…" : "Add all sample files"}
                </button>
              </>
            )}
          </div>
          <ChatComposer
            placeholder={planning ? "Ask for different or more suggestions…" : "Add to the client brief, or attach a profile with the paperclip…"}
            label={planning ? "Message to the Planner" : "Add to the client brief"}
            onSend={handleSend}
            disabled={uploading || (planning && (!planner.result || planner.moreLoading))}
            attachments={attachments}
            onAttach={(id, file) => handleSelect(id as UploadSlotId, file)}
            onDetach={(id) => onRemove(id as UploadSlotId)}
          />
        </div>
      </div>
    </div>
  );
}
