import { useState, type ReactNode } from "react";
import type { AnalysisDraft, AnalysisRepositoryEntry, OverallAnalysisReport } from "../api/audit";
import { LOADING } from "../utils/loadingMessages";
import { tidyText } from "../utils/tidyText";
import { friendlyAiError } from "../utils/aiError";
import ChatMessage from "./ChatMessage";
import ThinkingLoader from "./ThinkingLoader";
import "./AuditChat.css";
import "./FeaturesChat.css";
import "./AnalysisChat.css";

export type AnalysisBlock = "suggest" | "custom" | "draft";

export interface AnalysisLogEntry {
  user: string;
  block: AnalysisBlock;
  draftId?: number;
}

export interface AnalysisDraftState {
  request: { name: string; description: string };
  state: "working" | "ready" | "failed" | "added";
  draft?: AnalysisDraft;
  error?: string;
}

interface AnalysisChatProps {
  rows: number;
  columns: number;
  topLevel: AnalysisRepositoryEntry[];
  drilldownCount: number;
  running: number;
  blocked: number;
  repoLoading: boolean;
  repoError: string | undefined;
  defsLoading: boolean;
  defsError: string | null;
  overall: { report: OverallAnalysisReport | undefined; loading: boolean; error: string | undefined; waiting: boolean; onRetry: () => void };
  /** The analysis itself: its chart, its reading and its details. */
  renderCard: (entry: AnalysisRepositoryEntry) => ReactNode;
  log: AnalysisLogEntry[];
  drafts: Record<number, AnalysisDraftState>;
  pendingSuggestions: AnalysisRepositoryEntry[];
  suggestLoading: boolean;
  suggestError: string | undefined;
  applyingEntryId: string | undefined;
  onAcceptSuggestion: (entry: AnalysisRepositoryEntry) => void;
  onAddDraft: (draftId: number) => void;
  adding: boolean;
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

/** The analyses as a conversation: the headline first, then each result with its chart, and quick replies for more. */
export default function AnalysisChat(props: AnalysisChatProps) {
  const { topLevel, overall, log, drafts } = props;
  const done = topLevel.filter((e) => e.run_status === "done").length;

  return (
    <>
      {props.defsLoading && (
        <ChatMessage>
          <ThinkingLoader variant="inline" messages={["Reading your Analysis Profile…"]} />
        </ChatMessage>
      )}
      {props.defsError && (
        <ChatMessage>
          <div className="upload-page__error">{props.defsError}</div>
        </ChatMessage>
      )}
      {props.repoLoading && topLevel.length === 0 && (
        <ChatMessage>
          <ThinkingLoader messages={LOADING.analysisRepository} />
        </ChatMessage>
      )}
      {props.repoError && (
        <ChatMessage>
          <div className="upload-page__error">{friendlyAiError(props.repoError, props.repoError)}</div>
        </ChatMessage>
      )}

      {topLevel.length > 0 && (
        <ChatMessage>
          <p>
            {props.running > 0
              ? `I am running your ${topLevel.length} analyses on the audited data. ${done} of ${topLevel.length} are done, and I will summarise them when they finish.`
              : `I ran ${done} of your ${topLevel.length} analyses on the audited data.`}
          </p>
          <div className="chat-stats">
            <div className="chat-stat"><small>Rows</small><b>{props.rows.toLocaleString()}</b></div>
            <div className="chat-stat"><small>Columns</small><b>{props.columns.toLocaleString()}</b></div>
            <div className="chat-stat"><small>Analyses</small><b>{topLevel.length}</b></div>
            {props.drilldownCount > 0 && <div className="chat-stat"><small>Drill-downs</small><b>{props.drilldownCount}</b></div>}
          </div>
          {props.running > 0 && <ThinkingLoader messages={["Running the analyses…", "Reading the results…"]} variant="inline" />}
        </ChatMessage>
      )}

      {topLevel.length === 0 && !props.repoLoading && !props.repoError && (
        <ChatMessage>
          <p>There are no analyses yet. Ask me to suggest some, or describe your own.</p>
        </ChatMessage>
      )}

      {(overall.report || overall.loading || overall.error) && (
        <ChatMessage>
          {overall.loading ? (
            <ThinkingLoader variant="inline" messages={overall.report ? ["Updating the summary with the latest analyses…"] : LOADING.summary} />
          ) : overall.error ? (
            <>
              <div className="upload-page__error">{friendlyAiError(overall.error, overall.error)}</div>
              <div>
                <button type="button" className="audit-chat__pill" onClick={overall.onRetry}>
                  Try the summary again
                </button>
              </div>
            </>
          ) : (
            overall.report && (
              <>
                <p>{overall.report.narrative}</p>
                {overall.report.highlights.length > 0 && (
                  <div className="analysis-chat__highlights">
                    {overall.report.highlights.map((h, i) => (
                      <div key={i} className="analysis-chat__highlight">
                        <small>{h.label}</small>
                        <b>{h.value}</b>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )
          )}
        </ChatMessage>
      )}

      {topLevel.length > 0 && (
        <ChatMessage>
          <p>Here is each one. Open an analysis for its details and to drill down.</p>
          <div className="analysis-chat__grid">{topLevel.map((entry) => <div key={entry.id}>{props.renderCard(entry)}</div>)}</div>
        </ChatMessage>
      )}

      {props.blocked > 0 && (
        <ChatMessage>
          <p>
            {props.blocked} {props.blocked === 1 ? "analysis is" : "analyses are"} waiting on a feature it needs. Open it to choose or compute the feature.
          </p>
        </ChatMessage>
      )}

      {log.map((entry, i) => (
        <div key={i} className="chat-page__turn">
          <ChatMessage from="user">{entry.user}</ChatMessage>

          {entry.block === "suggest" && (
            <ChatMessage>
              {props.suggestLoading ? (
                <ThinkingLoader messages={["Reading your columns…", "Thinking of useful tables…"]} variant="inline" />
              ) : props.suggestError ? (
                <div className="upload-page__error">{friendlyAiError(props.suggestError, props.suggestError)}</div>
              ) : props.pendingSuggestions.length === 0 ? (
                <p>I have no new suggestions right now.</p>
              ) : (
                <>
                  <p>
                    Here {props.pendingSuggestions.length === 1 ? "is one" : `are ${props.pendingSuggestions.length}`} I could add, based on your
                    columns.
                  </p>
                  <div className="chat-card">
                    <div className="audit-chat__issues">
                      {props.pendingSuggestions.map((s) => (
                        <div className="audit-chat__issue" key={s.id}>
                          <div className="audit-chat__issue-main">
                            <div className="audit-chat__issue-title">
                              <b>{s.name}</b>
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
                              {props.applyingEntryId === s.id ? "Adding…" : "Add this analysis"}
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
                Describe the analysis in a sentence and I will work out the grouping and the measures, then test it. For example: average time above 8 °C
                by lane, or the share of late arrivals by carrier.
              </p>
            </ChatMessage>
          )}

          {entry.block === "draft" && entry.draftId !== undefined && drafts[entry.draftId] && (
            <ChatMessage>
              {(() => {
                const d = drafts[entry.draftId!];
                if (d.state === "working") return <ThinkingLoader messages={["Working out the grouping…", "Testing it on your data…"]} variant="inline" />;
                if (d.state === "failed" || !d.draft) return <div className="upload-page__error">{d.error ?? "I could not work that out."}</div>;
                const draft = d.draft;
                return (
                  <>
                    <p>
                      Here is my plan for {d.request.name}.{" "}
                      {draft.group_by.length > 0 ? `It groups by ${draft.group_by.join(", ")}` : "It looks at the data as a whole"}
                      {draft.metrics.length > 0 ? ` and measures ${draft.metrics.join(", ")}.` : "."}
                    </p>
                    <div className="chat-card">
                      <div className="chat-card__body">
                        <div>
                          <span className="chat-card__label">Calculation</span>
                          <code className="features-chat__formula">{draft.formula}</code>
                        </div>
                        {draft.chart && <p className="audit-chat__meta">Best shown as a {draft.chart.chart_type.replace(/_/g, " ")}. {draft.chart.reason}</p>}
                      </div>
                      <div className="chat-card__foot">
                        {d.state === "added" ? (
                          <span className="audit-chat__sev audit-chat__sev--ok">Added</span>
                        ) : (
                          <button type="button" className="audit-chat__pill audit-chat__pill--main" disabled={props.adding} onClick={() => props.onAddDraft(entry.draftId!)}>
                            {props.adding ? "Adding…" : "Add this analysis"}
                          </button>
                        )}
                      </div>
                    </div>
                  </>
                );
              })()}
            </ChatMessage>
          )}
        </div>
      ))}
    </>
  );
}
