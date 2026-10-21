import { useState } from "react";
import type { DataPreview, FeatureDraft, FeatureReport, FeatureRepositoryEntry, FeatureResult } from "../api/audit";
import { LOADING } from "../utils/loadingMessages";
import { tidyText } from "../utils/tidyText";
import { friendlyAiError } from "../utils/aiError";
import ChatMessage from "./ChatMessage";
import DataPreviewTable from "./DataPreviewTable";
import ThinkingLoader from "./ThinkingLoader";
import "./AuditChat.css";
import "./FeaturesChat.css";

export type FeaturesBlock = "suggest" | "custom" | "preview" | "download" | "draft";

export interface FeaturesLogEntry {
  user: string;
  block: FeaturesBlock;
  /** For a drafted custom KPI: which draft this message shows. */
  draftId?: number;
}

export interface KpiDraftState {
  request: { name: string; description: string };
  state: "working" | "ready" | "failed" | "added";
  draft?: FeatureDraft;
  error?: string;
}

interface FeaturesChatProps {
  report: FeatureReport | undefined;
  loading: boolean;
  error: string | undefined;
  defsLoading: boolean;
  defsError: string | null;
  requiredFor: (featureId: string) => string[];
  log: FeaturesLogEntry[];
  drafts: Record<number, KpiDraftState>;
  pendingSuggestions: FeatureRepositoryEntry[];
  suggestLoading: boolean;
  suggestError: string | undefined;
  applyingEntryId: string | undefined;
  preview: DataPreview | undefined;
  onOpenFeature: (featureId: string) => void;
  onAcceptSuggestion: (entry: FeatureRepositoryEntry) => void;
  onAddDraft: (draftId: number) => void;
  adding: boolean;
}

const SOURCE: Record<string, { text: string; cls: string }> = {
  predefined: { text: "From your KPI profile", cls: "audit-chat__sev--ok" },
  planner: { text: "From your plan", cls: "audit-chat__sev--info" },
  custom: { text: "Your own", cls: "audit-chat__sev--info" },
  ai_suggested: { text: "AI suggested", cls: "audit-chat__sev--warn" },
};

function coverage(f: FeatureResult): number {
  const total = f.non_null_count + f.null_count;
  return total > 0 ? Math.round((f.non_null_count / total) * 100) : 0;
}

function Tiles({ items }: { items: { label: string; value: string }[] }) {
  return (
    <div className="chat-stats">
      {items.map((s) => (
        <div className="chat-stat" key={s.label}>
          <small>{s.label}</small>
          <b>{s.value}</b>
        </div>
      ))}
    </div>
  );
}

function Clamped({ text }: { text: string }) {
  const [more, setMore] = useState(false);
  const long = text.length > 200;
  return (
    <>
      <p className={long && !more ? "audit-chat__clamp" : undefined}>{text}</p>
      {long && (
        <button type="button" className="audit-chat__link" onClick={() => setMore((v) => !v)}>
          {more ? "Show less" : "Show more"}
        </button>
      )}
    </>
  );
}

/** The features as a conversation: what was built, how complete each one is, and the quick replies to add more. */
export default function FeaturesChat(props: FeaturesChatProps) {
  const { report, loading, error, defsLoading, defsError, log, drafts } = props;

  return (
    <>
      {defsLoading && (
        <ChatMessage>
          <ThinkingLoader variant="inline" messages={["Reading your Customer KPI Profile…"]} />
        </ChatMessage>
      )}
      {defsError && (
        <ChatMessage>
          <div className="upload-page__error">{defsError}</div>
        </ChatMessage>
      )}

      {loading && (
        <ChatMessage>
          <p>Building the features from your plan on the audited data.</p>
          <ThinkingLoader messages={LOADING.features} hint="I plan and calculate each new column." intervalMs={3500} showElapsed />
        </ChatMessage>
      )}
      {error && (
        <ChatMessage>
          <div className="upload-page__error">{friendlyAiError(error, error)}</div>
        </ChatMessage>
      )}

      {report && (
        <>
          <ChatMessage>
            <p>
              {report.features.length === 0
                ? "I have not built any features yet. Ask me to suggest some, or describe your own."
                : `I built ${report.features.length} feature${report.features.length === 1 ? "" : "s"} on the audited data. Coverage shows how many trips had everything needed to compute each one.`}
            </p>
            <Tiles
              items={[
                { label: "Rows", value: report.row_count.toLocaleString() },
                { label: "Columns", value: report.column_count.toLocaleString() },
                { label: "Features added", value: String(report.features.length) },
                ...(report.skipped_notes.length > 0 ? [{ label: "Skipped", value: String(report.skipped_notes.length) }] : []),
              ]}
            />
          </ChatMessage>

          {report.features.length > 0 && (
            <ChatMessage>
              <div className="chat-card">
                <div className="chat-card__head">
                  Features
                  <span>{report.features.length} built</span>
                </div>
                <div className="audit-chat__issues">
                  {report.features.map((f) => {
                    const src = SOURCE[f.source] ?? SOURCE.planner;
                    const needed = props.requiredFor(f.id);
                    const pct = coverage(f);
                    return (
                      <div className="audit-chat__issue" key={f.id}>
                        <div className="audit-chat__issue-main">
                          <div className="audit-chat__issue-title">
                            <b>{f.name}</b>
                            <span className={`audit-chat__sev ${src.cls}`}>{src.text}</span>
                            {needed.length > 0 && <span className="audit-chat__sev audit-chat__sev--bad">Needed by {needed.join(", ")}</span>}
                          </div>
                          <Clamped text={tidyText(f.description)} />
                          <p className="audit-chat__meta">
                            Column <code className="features-chat__code">{f.output_column}</code>
                          </p>
                        </div>
                        <div className="features-chat__side">
                          <div className="features-chat__cov" title={`${pct}% coverage`}>
                            <i style={{ width: `${pct}%` }} />
                          </div>
                          <span className="features-chat__pct">{pct}%</span>
                          <button type="button" className="audit-chat__pill" onClick={() => props.onOpenFeature(f.id)}>
                            Details
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </ChatMessage>
          )}

          {report.skipped_notes.length > 0 && (
            <ChatMessage>
              <p>I skipped {report.skipped_notes.length === 1 ? "one thing" : `${report.skipped_notes.length} things`}:</p>
              <ul className="features-chat__skipped">
                {report.skipped_notes.map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            </ChatMessage>
          )}
        </>
      )}

      {log.map((entry, i) => (
        <div key={i} className="chat-page__turn">
          <ChatMessage from="user">{entry.user}</ChatMessage>

          {entry.block === "suggest" && (
            <ChatMessage>
              {props.suggestLoading ? (
                <ThinkingLoader messages={["Reading your column names…", "Thinking of useful fields…"]} variant="inline" />
              ) : props.suggestError ? (
                <div className="upload-page__error">{friendlyAiError(props.suggestError, props.suggestError)}</div>
              ) : props.pendingSuggestions.length === 0 ? (
                <p>I have no new suggestions right now.</p>
              ) : (
                <>
                  <p>
                    Here {props.pendingSuggestions.length === 1 ? "is one" : `are ${props.pendingSuggestions.length}`} I could add. I looked at your
                    column names and picked fields I can compute.
                  </p>
                  <div className="chat-card">
                    <div className="audit-chat__issues">
                      {props.pendingSuggestions.map((s) => (
                        <div className="audit-chat__issue" key={s.id}>
                          <div className="audit-chat__issue-main">
                            <div className="audit-chat__issue-title">
                              <b>{s.name}</b>
                              <code className="features-chat__code">{s.output_column}</code>
                            </div>
                            <Clamped text={tidyText(s.description)} />
                          </div>
                          <div className="audit-chat__actions">
                            <button
                              type="button"
                              className="audit-chat__pill audit-chat__pill--main"
                              disabled={props.applyingEntryId === s.id}
                              onClick={() => props.onAcceptSuggestion(s)}
                            >
                              {props.applyingEntryId === s.id ? "Adding…" : "Add this feature"}
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </ChatMessage>
          )}

          {entry.block === "custom" && (
            <ChatMessage>
              <p>
                Describe the KPI you want in a sentence and I will write the formula and test it on your data. For example: hours between departure and
                arrival, or the share of readings above 8 °C.
              </p>
            </ChatMessage>
          )}

          {entry.block === "draft" && entry.draftId !== undefined && drafts[entry.draftId] && (
            <ChatMessage>
              {(() => {
                const d = drafts[entry.draftId!];
                if (d.state === "working") return <ThinkingLoader messages={["Writing the formula…", "Testing it on your data…"]} variant="inline" />;
                if (d.state === "failed" || !d.draft) return <div className="upload-page__error">{d.error ?? "I could not write a formula for that."}</div>;
                const draft = d.draft;
                return (
                  <>
                    <p>
                      {draft.status === "ok"
                        ? `Here is my formula for ${d.request.name}. I tested it on your data.`
                        : `I could not get a working formula for ${d.request.name}.`}
                    </p>
                    <div className="chat-card">
                      <div className="chat-card__body">
                        <div>
                          <span className="chat-card__label">Formula</span>
                          <code className="features-chat__formula">{draft.formula}</code>
                        </div>
                        {draft.summary && (
                          <p className="audit-chat__meta">
                            {draft.summary.non_null_count.toLocaleString()} rows have a value, {draft.summary.null_count.toLocaleString()} do not.
                            {draft.validation_note ? ` ${draft.validation_note}` : ""}
                          </p>
                        )}
                        {draft.error && <div className="upload-page__error">{draft.error}</div>}
                      </div>
                      <div className="chat-card__foot">
                        {d.state === "added" ? (
                          <span className="audit-chat__sev audit-chat__sev--ok">Added</span>
                        ) : (
                          <button
                            type="button"
                            className="audit-chat__pill audit-chat__pill--main"
                            disabled={draft.status !== "ok" || props.adding}
                            onClick={() => props.onAddDraft(entry.draftId!)}
                          >
                            {props.adding ? "Adding…" : "Add this KPI"}
                          </button>
                        )}
                      </div>
                    </div>
                  </>
                );
              })()}
            </ChatMessage>
          )}

          {entry.block === "preview" && (
            <ChatMessage>
              <p>The audited data with your new columns. These are the first rows.</p>
              <div className="audit-chat__card">
                {props.preview ? <DataPreviewTable preview={props.preview} /> : <ThinkingLoader variant="inline" messages={LOADING.preview} />}
              </div>
            </ChatMessage>
          )}

          {entry.block === "download" && (
            <ChatMessage>
              <p>Downloading the engineered file. It has the audit decisions and every new column.</p>
            </ChatMessage>
          )}
        </div>
      ))}
    </>
  );
}
