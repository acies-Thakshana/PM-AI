import { useEffect, useState } from "react";
import type { AuditIssue, AuditReport as AuditReportData, OutliersResponse } from "../api/audit";
import { fetchOutliers } from "../api/audit";
import type { SwpTimesResult } from "../api/swp";
import { LOADING } from "../utils/loadingMessages";
import { friendlyAiError } from "../utils/aiError";
import AuditSummaryPanel from "./AuditSummaryPanel";
import ChatMessage from "./ChatMessage";
import IssueRowsModal from "./IssueRowsModal";
import OutlierBoxPlot from "./OutlierBoxPlot";
import OutlierCorrectionStep from "./OutlierCorrectionStep";
import ThinkingLoader from "./ThinkingLoader";
import TripInspectTable from "./TripInspectTable";
import "./AuditChat.css";

export type AuditBlock = "keep" | "review" | "trips" | "summary" | "download";

export interface AuditLogEntry {
  user: string;
  block: AuditBlock;
}

interface AuditChatProps {
  sessionId: string;
  apiSource: boolean;
  /** Bumped whenever a trip's times changed, so what is built on them is read again. */
  dataVersion: number;
  /** The outlier review is done (kept as they are, or a corrected file was uploaded). */
  unlocked: boolean;
  report: AuditReportData | undefined;
  loading: boolean;
  error: string | undefined;
  resolvingIssueId: string | null;
  log: AuditLogEntry[];
  onUnlock: () => void;
  onResolve: (issueId: string, decisionId: string, selectedItems?: string[]) => Promise<void>;
  onRevert: (issueId: string) => void;
  onCorrectedFile: (file: File) => void | Promise<unknown>;
  reuploading: boolean;
  reuploadError: string | null;
  onInspectKey: (key: string) => void;
  onInspectNumber: (number: string) => void;
  onTimesSaved: (tripKey: string, result: SwpTimesResult) => void;
  /** Where the decisions stand, to say when everything is settled. */
  canContinue: boolean;
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

const SEVERITY: Record<string, { text: string; cls: string }> = {
  critical: { text: "Needs review", cls: "audit-chat__sev--bad" },
  warning: { text: "Needs review", cls: "audit-chat__sev--warn" },
  info: { text: "For your information", cls: "audit-chat__sev--info" },
};

const COLUMN_SCOPED = new Set(["fully_empty_columns", "high_null_columns", "constant_value_columns"]);

function IssueRow({
  issue,
  sessionId,
  resolving,
  onResolve,
  onRevert,
}: {
  issue: AuditIssue;
  sessionId: string;
  resolving: boolean;
  onResolve: (issueId: string, decisionId: string, selectedItems?: string[]) => Promise<void>;
  onRevert: (issueId: string) => void;
}) {
  const [checked, setChecked] = useState<Set<string>>(() => new Set(issue.selectable_items));
  const [rows, setRows] = useState(false);
  const [more, setMore] = useState(false);
  const selectable = issue.selectable_items.length > 0;
  const unit = COLUMN_SCOPED.has(issue.category) ? "column" : "row";
  const resolved = issue.status === "resolved" && issue.resolution;
  const sev = SEVERITY[issue.severity] ?? SEVERITY.info;
  const dropOption = issue.options.find((o) => o.id === "drop_selected");
  const keepOption = issue.options.find((o) => o.id === "keep");

  const toggle = (item: string) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(item)) next.delete(item);
      else next.add(item);
      return next;
    });

  return (
    <div className={`audit-chat__issue${resolved ? " audit-chat__issue--done" : ""}`}>
      <div className="audit-chat__issue-main">
        <div className="audit-chat__issue-title">
          <b>{issue.title}</b>
          <span className={`audit-chat__sev ${resolved ? "audit-chat__sev--ok" : sev.cls}`}>{resolved ? "Resolved" : sev.text}</span>
        </div>
        <p className={!resolved && !more && issue.description.length > 220 ? "audit-chat__clamp" : undefined}>
          {resolved ? issue.resolution : issue.description}
        </p>
        {!resolved && issue.description.length > 220 && (
          <button type="button" className="audit-chat__link" onClick={() => setMore((v) => !v)}>
            {more ? "Show less" : "Show more"}
          </button>
        )}
        {!resolved && (
          <p className="audit-chat__meta">
            Affects {issue.affected_row_count} {unit}
            {issue.affected_row_count === 1 ? "" : "s"}.
            {issue.sample.length > 0 && (
              <>
                {" "}
                <button type="button" className="audit-chat__link" onClick={() => setRows(true)}>
                  See them
                </button>
              </>
            )}
          </p>
        )}
        {!resolved && issue.chart && (
          <div className="audit-chat__chart">
            <OutlierBoxPlot chart={issue.chart} />
          </div>
        )}
        {!resolved && selectable && (
          <div className="audit-chat__picks" role="group" aria-label="Choose which to drop">
            {issue.selectable_items.map((item) => (
              <button
                key={item}
                type="button"
                className="audit-chat__pick"
                aria-pressed={checked.has(item)}
                disabled={resolving}
                onClick={() => toggle(item)}
              >
                {item}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="audit-chat__actions">
        {resolved ? (
          <button type="button" className="audit-chat__pill" disabled={resolving} onClick={() => onRevert(issue.id)}>
            {resolving ? "Undoing…" : "Undo"}
          </button>
        ) : selectable ? (
          <>
            {dropOption && (
              <button
                type="button"
                className="audit-chat__pill audit-chat__pill--main"
                disabled={resolving || checked.size === 0}
                onClick={() => void onResolve(issue.id, dropOption.id, Array.from(checked))}
              >
                {dropOption.label} ({checked.size})
              </button>
            )}
            {keepOption && (
              <button type="button" className="audit-chat__pill" disabled={resolving} onClick={() => void onResolve(issue.id, keepOption.id)}>
                {keepOption.label}
              </button>
            )}
          </>
        ) : issue.requires_decision ? (
          issue.options.map((opt) => (
            <button
              key={opt.id}
              type="button"
              className={`audit-chat__pill${opt.id === "keep" ? "" : " audit-chat__pill--main"}`}
              disabled={resolving}
              onClick={() => void onResolve(issue.id, opt.id)}
            >
              {opt.label}
            </button>
          ))
        ) : null}
      </div>

      {rows && <IssueRowsModal title={issue.title} sessionId={sessionId} issueId={issue.id} onClose={() => setRows(false)} />}
    </div>
  );
}

/** The audit as a conversation. The assistant reports what it found; the PM answers with the quick replies. */
export default function AuditChat(props: AuditChatProps) {
  const { sessionId, apiSource, dataVersion, unlocked, report, loading, error, resolvingIssueId, log } = props;
  const [outliers, setOutliers] = useState<OutliersResponse | null>(null);
  const [outlierError, setOutlierError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setOutliers(null);
    setOutlierError(null);
    fetchOutliers(sessionId)
      .then((data) => !cancelled && setOutliers(data))
      .catch((e: Error) => !cancelled && setOutlierError(e.message));
    return () => {
      cancelled = true;
    };
  }, [sessionId, dataVersion]);

  const flagged = outliers ? outliers.segment.flagged_trips + outliers.temperature.too_warm_count + outliers.temperature.too_cold_count : 0;

  // Uploaded files with nothing flagged have nothing to review: straight on to the standard checks.
  useEffect(() => {
    if (outliers && flagged === 0 && !apiSource && !unlocked) props.onUnlock();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outliers, flagged, apiSource, unlocked]);

  const pending = report ? report.issues.filter((i) => i.requires_decision && i.status === "pending").length : 0;
  const lead = outliers?.segment.outlier_rows.slice(0, 5) ?? [];
  const warm = outliers?.temperature.by_product.flatMap((p) => p.trips.filter((t) => t.status !== "in_spec").map((t) => ({ ...t, product: p.product }))) ?? [];

  return (
    <>
      <ChatMessage>
        {!outliers && !outlierError && <ThinkingLoader messages={LOADING.outliers} variant="inline" />}
        {outlierError && <div className="upload-page__error">Could not check the outliers: {outlierError}</div>}
        {outliers && (
          <>
            <p>
              I checked all <b>{(outliers.segment.total_trips || outliers.temperature.total_trips).toLocaleString()}</b> trips before building anything on them.{" "}
              {flagged === 0
                ? "Nothing looks unusual."
                : `${flagged} trip${flagged === 1 ? "" : "s"} look unusual, so I want you to see them first.`}
            </p>
            <Tiles
              items={[
                { label: "Trips", value: (outliers.segment.total_trips || outliers.temperature.total_trips).toLocaleString() },
                { label: "Columns", value: String(outliers.segment.columns.length) },
                { label: "Unusual duration", value: String(outliers.segment.flagged_trips) },
                { label: "Temperature breaches", value: String(outliers.temperature.too_warm_count + outliers.temperature.too_cold_count) },
              ]}
            />
          </>
        )}
      </ChatMessage>

      {outliers && flagged > 0 && (
        <ChatMessage>
          <p>
            Segment days are compared with the trip&apos;s lane, and mean temperature with the product&apos;s other trips. Nothing is changed or sent to
            SWP. Here are the first few:
          </p>
          <div className="audit-chat__table">
            <table>
              <thead>
                <tr>
                  <th>Trip</th>
                  <th>Why</th>
                  <th>Value</th>
                  <th>Expected</th>
                </tr>
              </thead>
              <tbody>
                {lead.map((r, i) => (
                  <tr key={`s${i}`}>
                    <td>{r.trip_id ?? r.serial ?? "–"}</td>
                    <td>
                      Segment days on {r.origin} → {r.destination}
                    </td>
                    <td className="audit-chat__hot">{r.segment_days ?? "–"}</td>
                    <td>
                      {r.lower_fence_days ?? "–"} to {r.upper_fence_days ?? "–"}
                    </td>
                  </tr>
                ))}
                {warm.slice(0, Math.max(0, 5 - lead.length)).map((t, i) => (
                  <tr key={`t${i}`}>
                    <td>{t.trip_id ?? t.serial ?? "–"}</td>
                    <td>
                      Mean temperature, {t.product} ({t.status === "too_warm" ? "too warm" : "too cold"})
                    </td>
                    <td className="audit-chat__hot">{t.mean_temp ?? "–"} °C</td>
                    <td>
                      {t.limit_low ?? "–"} to {t.limit_high ?? "–"} °C
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!unlocked && <p>Do you want to keep them as they are, or look at them and correct some?</p>}
        </ChatMessage>
      )}

      {log.map((entry, i) => (
        <div key={i} className="chat-page__turn">
          <ChatMessage from="user">{entry.user}</ChatMessage>
          {entry.block === "keep" && (
            <ChatMessage>
              <p>Okay, they stay as they are. Now I will run the standard checks: duplicates, empty columns and anything else that looks wrong.</p>
            </ChatMessage>
          )}
          {entry.block === "review" && (
            <ChatMessage>
              <p>Here they are. Edit a value to correct it, or carry on when you are done.</p>
              <div className="audit-chat__card">
                <OutlierCorrectionStep
                  key={`${sessionId}:${dataVersion}`}
                  sessionId={sessionId}
                  onInspect={apiSource ? props.onInspectNumber : undefined}
                  onFileCorrected={props.onCorrectedFile}
                  onProceed={props.onUnlock}
                  apiData={apiSource}
                  uploading={props.reuploading}
                  uploadError={props.reuploadError}
                />
              </div>
            </ChatMessage>
          )}
          {entry.block === "trips" && (
            <ChatMessage>
              <p>Every trip with its mean temperature and segment days. Inspect one for its graph and map, or edit its times.</p>
              <div className="audit-chat__card">
                <TripInspectTable key={`${sessionId}:${dataVersion}`} sessionId={sessionId} onInspect={props.onInspectKey} onTimesSaved={props.onTimesSaved} />
              </div>
            </ChatMessage>
          )}
          {entry.block === "summary" && (
            <ChatMessage>
              <p>This is what changed in your data so far.</p>
              <div className="audit-chat__card">{report && <AuditSummaryPanel report={report} />}</div>
            </ChatMessage>
          )}
          {entry.block === "download" && (
            <ChatMessage>
              <p>Downloading the cleaned data. It has every decision you made applied.</p>
            </ChatMessage>
          )}
        </div>
      ))}

      {unlocked && loading && (
        <ChatMessage>
          <ThinkingLoader messages={LOADING.audit} hint="Running the standard data checks." intervalMs={3500} showElapsed />
        </ChatMessage>
      )}

      {unlocked && error && (
        <ChatMessage>
          <div className="upload-page__error">{friendlyAiError(error, error)}</div>
        </ChatMessage>
      )}

      {unlocked && report && (
        <>
          <ChatMessage>
            <p>
              {report.summary}{" "}
              {pending > 0
                ? `${pending} thing${pending === 1 ? " needs" : "s need"} your call.`
                : "Nothing is waiting on you."}
            </p>
            <Tiles
              items={[
                { label: "Rows checked", value: report.row_count.toLocaleString() },
                { label: "Columns", value: report.column_count.toLocaleString() },
                { label: "Issues found", value: String(report.issues.length) },
                { label: "Need a decision", value: String(pending) },
              ]}
            />
          </ChatMessage>

          {report.issues.length > 0 && (
            <ChatMessage>
              <div className="chat-card">
                <div className="chat-card__head">
                  What I found
                  <span>
                    {report.issues.filter((i) => i.requires_decision && i.status === "resolved").length} of{" "}
                    {report.issues.filter((i) => i.requires_decision).length} decided
                  </span>
                </div>
                <div className="audit-chat__issues">
                  {[...report.issues]
                    .sort((a, b) => Number(b.requires_decision) - Number(a.requires_decision))
                    .map((issue) => (
                      <IssueRow
                        key={issue.id}
                        issue={issue}
                        sessionId={sessionId}
                        resolving={resolvingIssueId === issue.id}
                        onResolve={props.onResolve}
                        onRevert={props.onRevert}
                      />
                    ))}
                </div>
              </div>
            </ChatMessage>
          )}

          {props.canContinue && (
            <ChatMessage>
              <p>
                That settles the audit. <b>{report.row_count.toLocaleString()}</b> rows are ready for feature building. Say the word and we move on.
              </p>
            </ChatMessage>
          )}
        </>
      )}
    </>
  );
}
