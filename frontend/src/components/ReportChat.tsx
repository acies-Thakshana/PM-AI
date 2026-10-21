import { friendlyAiError } from "../utils/aiError";
import { LOADING } from "../utils/loadingMessages";
import type { AnalysisRepositoryEntry, LanguageOption } from "../api/audit";
import AnalysisChart from "./AnalysisChart";
import ChatMessage from "./ChatMessage";
import ThinkingLoader from "./ThinkingLoader";
import "./AuditChat.css";
import "./ReportChat.css";

export type ReportBlock = "download" | "language" | "summary" | "edit";

export interface ReportLogEntry {
  user: string;
  block: ReportBlock;
}

export interface ReportSlideRow {
  entry: AnalysisRepositoryEntry;
  depth: number;
  name: string;
  interpretation: string | null | undefined;
  subtitle: string;
  number: string | number | undefined;
  stale: boolean;
  included: boolean;
  chartOpen: boolean;
}

interface ReportChatProps {
  analyses: number;
  aiSuggested: number;
  addedSlides: number;
  bullets: string[] | null;
  summaryLoading: boolean;
  summaryError: string | undefined;
  onRetrySummary: () => void;
  rows: ReportSlideRow[];
  onToggle: (entryId: string) => void;
  onToggleChart: (entryId: string) => void;
  languages: LanguageOption[];
  language: string;
  onLanguage: (code: string) => void;
  log: ReportLogEntry[];
  exporting: boolean;
  exportError: string | undefined;
  noSelection: boolean;
}

/** The report as a conversation: the key messages first, then the slides it would contain, then quick replies to
 * change the language, edit the slides or download the file. */
export default function ReportChat(props: ReportChatProps) {
  const { rows, bullets, log } = props;
  const included = rows.filter((r) => r.included).length;
  const lastDownload = log.map((e) => e.block).lastIndexOf("download");

  return (
    <>
      <ChatMessage>
        <p>
          I can turn your {props.analyses} finished analys{props.analyses === 1 ? "is" : "es"} into a PowerPoint with charts you can edit.{" "}
          {included === 0 ? "Nothing is included yet, so choose at least one slide below." : `${included} slide${included === 1 ? " is" : "s are"} included.`}
        </p>
        <div className="chat-stats">
          <div className="chat-stat"><small>Analyses</small><b>{props.analyses}</b></div>
          <div className="chat-stat"><small>In the report</small><b>{included}</b></div>
          {props.aiSuggested > 0 && <div className="chat-stat"><small>AI suggested</small><b>{props.aiSuggested}</b></div>}
          {props.addedSlides > 0 && <div className="chat-stat"><small>Slides you added</small><b>{props.addedSlides}</b></div>}
        </div>
      </ChatMessage>

      <ChatMessage>
        {props.summaryError ? (
          <>
            <div className="upload-page__error">{friendlyAiError(props.summaryError, props.summaryError)}</div>
            <div>
              <button type="button" className="audit-chat__pill" onClick={props.onRetrySummary}>
                Try the summary again
              </button>
            </div>
          </>
        ) : props.summaryLoading && !bullets ? (
          <ThinkingLoader messages={LOADING.reportSummary} variant="inline" />
        ) : bullets ? (
          <>
            <p>The closing slide will say:</p>
            <ul className="report-chat__bullets">
              {bullets.map((b, i) => (
                <li key={i}>{b}</li>
              ))}
            </ul>
          </>
        ) : (
          <p>Choose at least one slide and I will write the closing summary.</p>
        )}
      </ChatMessage>

      <ChatMessage>
        <div className="chat-card">
          <div className="chat-card__head">
            This report will include
            <span>
              {included} of {rows.length} slides
            </span>
          </div>
          <div className="audit-chat__issues">
            {rows.map((r) => (
              <div className={`audit-chat__issue${r.included ? " audit-chat__issue--done" : ""}`} key={r.entry.id} style={r.depth > 0 ? { paddingLeft: 18 + r.depth * 24 } : undefined}>
                <div className="audit-chat__issue-main">
                  <div className="audit-chat__issue-title">
                    <b>{r.name}</b>
                    <span className={`audit-chat__sev ${r.included ? "audit-chat__sev--ok" : "audit-chat__sev--info"}`}>
                      {r.stale ? "Out of date" : r.number ? `Slide ${r.number}` : "Not included"}
                    </span>
                  </div>
                  {r.subtitle && <p className="audit-chat__meta">{r.subtitle}</p>}
                  {r.stale && <p className="audit-chat__meta">An earlier level changed. Refresh it in Analysis to include it.</p>}
                  {r.interpretation && <p className="report-chat__reading">{r.interpretation}</p>}
                  <button type="button" className="audit-chat__link" onClick={() => props.onToggleChart(r.entry.id)}>
                    {r.chartOpen ? "Hide chart" : "Show chart"}
                  </button>
                  {r.chartOpen && (
                    <div className="report-chat__chart">
                      <AnalysisChart chartSpec={r.entry.chart_spec} chartType={r.entry.chart_type} resultTable={r.entry.result_table} />
                    </div>
                  )}
                </div>
                <div className="audit-chat__actions">
                  <button
                    type="button"
                    className={`audit-chat__pill${r.included ? "" : " audit-chat__pill--main"}`}
                    disabled={r.stale}
                    onClick={() => props.onToggle(r.entry.id)}
                  >
                    {r.included ? "Leave out" : "Include"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </ChatMessage>

      {log.map((entry, i) => (
        <div key={i} className="chat-page__turn">
          <ChatMessage from="user">{entry.user}</ChatMessage>

          {entry.block === "language" && (
            <ChatMessage>
              <p>Which language should the report be in? The slide text, the charts' labels and the summary are translated.</p>
              <div className="report-chat__langs" role="group" aria-label="Report language">
                {props.languages.map((l) => (
                  <button
                    key={l.code}
                    type="button"
                    className={`audit-chat__pill${props.language === l.code ? " audit-chat__pill--main" : ""}`}
                    onClick={() => props.onLanguage(l.code)}
                  >
                    {l.name}
                  </button>
                ))}
              </div>
            </ChatMessage>
          )}

          {entry.block === "summary" && (
            <ChatMessage>
              <p>I will write the closing summary again from the slides that are included.</p>
            </ChatMessage>
          )}

          {entry.block === "edit" && (
            <ChatMessage>
              <p>I opened the slide editor. Change a heading or a note, reorder the slides, or add one of your own.</p>
            </ChatMessage>
          )}

          {entry.block === "download" && (
            <ChatMessage>
              {i === lastDownload && props.exporting ? (
                <ThinkingLoader messages={["Building your report…", "Drawing the charts…"]} variant="inline" />
              ) : i === lastDownload && props.exportError ? (
                <div className="upload-page__error">{friendlyAiError(props.exportError, props.exportError)}</div>
              ) : i === lastDownload && props.noSelection ? (
                <p>There is nothing to download yet. Include at least one slide first.</p>
              ) : (
                <p>Your report is downloaded as a PowerPoint.</p>
              )}
            </ChatMessage>
          )}
        </div>
      ))}
    </>
  );
}
