import { useState } from "react";
import type { AuditIssue, Severity } from "../api/audit";
import { IconChevronRight } from "./icons";
import "./AuditIssueCard.css";

export const COLUMN_SCOPED_CATEGORIES = new Set(["fully_empty_columns", "high_null_columns", "constant_value_columns"]);

const IMPACT_LABELS: Record<Severity, string> = {
  critical: "Data accuracy",
  warning: "Data completeness",
  info: "Data cleanliness",
};

const CHIP_PREVIEW_LIMIT = 6;

function recommendationFor(category: string): string {
  const base = category.split("::")[0];
  switch (base) {
    case "fully_empty_columns":
    case "high_null_columns":
    case "constant_value_columns":
      return "Consider dropping these columns.";
    case "exact_duplicate_rows":
    case "key_duplicate_rows":
      return "Consider removing the duplicate rows.";
    case "range_violations":
      return "Consider removing these inconsistent rows.";
    case "statistical_outliers":
      return "Worth a look before these feed into KPIs.";
    case "missing_identifier":
      return "Consider removing rows missing this field.";
    default:
      return "Review and decide below.";
  }
}

interface AuditIssueCardProps {
  issue: AuditIssue;
  onResolve: (issueId: string, decisionId: string, selectedItems?: string[]) => void;
  onRevert: (issueId: string) => void;
  resolving: boolean;
  // True when this resolution changed the data (dropped columns / removed
  // rows) but a later data-changing resolution now sits on top of it, so
  // reverting it out of order isn't safe -- the button stays visible but
  // disabled with an explanation, rather than reverting silently wrong.
  revertLocked: boolean;
}

// Resolution text like "Dropped 10 column(s): A, B, C." splits into a short
// headline plus an optional detail list, so a 10-column drop doesn't dump a
// wall of names into the card by default.
function splitResolution(resolution: string): { headline: string; detail: string | null } {
  const idx = resolution.indexOf(": ");
  if (idx === -1) return { headline: resolution, detail: null };
  return { headline: `${resolution.slice(0, idx)}.`, detail: resolution.slice(idx + 2) };
}

export default function AuditIssueCard({ issue, onResolve, onRevert, resolving, revertLocked }: AuditIssueCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [showSample, setShowSample] = useState(false);
  const [showResolutionDetail, setShowResolutionDetail] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(() => new Set(issue.selectable_items));
  const unit = COLUMN_SCOPED_CATEGORIES.has(issue.category) ? "column(s)" : "row(s)";
  const isSelectable = issue.selectable_items.length > 0;
  const resolutionParts = issue.resolution ? splitResolution(issue.resolution) : null;

  const toggleItem = (item: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(item)) next.delete(item);
      else next.add(item);
      return next;
    });
  };

  const dropOption = issue.options.find((o) => o.id === "drop_selected");
  const keepOption = issue.options.find((o) => o.id === "keep");
  const previewItems = issue.selectable_items.slice(0, CHIP_PREVIEW_LIMIT);
  const hiddenItemCount = issue.selectable_items.length - previewItems.length;

  return (
    <div className={`audit-issue audit-issue--${issue.severity} ${issue.status === "resolved" ? "audit-issue--resolved" : ""}`}>
      <div className="audit-issue__top">
        <span className={`audit-issue__severity audit-issue__severity--${issue.severity}`}>{issue.severity}</span>
        <h4 className="audit-issue__title">{issue.title}</h4>
        <span className="audit-issue__affected">
          {issue.affected_row_count} {unit}
        </span>
      </div>
      <p className="audit-issue__description">{issue.description}</p>

      {issue.status === "resolved" && resolutionParts ? (
        <div className="audit-issue__resolved-block">
          <div className="audit-issue__resolved-row">
            <p className="audit-issue__resolution">
              <span className="audit-issue__resolution-icon">✓</span>
              {resolutionParts.headline}
            </p>
            <button
              type="button"
              className="audit-issue__link audit-issue__revert-btn"
              disabled={resolving || revertLocked}
              title={revertLocked ? "Revert the most recent data change first" : undefined}
              onClick={() => onRevert(issue.id)}
            >
              {resolving ? "Reverting…" : "Revert"}
            </button>
          </div>
          {resolutionParts.detail && (
            <>
              <button
                type="button"
                className="audit-issue__sample-toggle"
                onClick={() => setShowResolutionDetail((s) => !s)}
              >
                {showResolutionDetail ? "Hide list" : "Show full list"}
              </button>
              {showResolutionDetail && <p className="audit-issue__resolution-detail">{resolutionParts.detail}</p>}
            </>
          )}
        </div>
      ) : !expanded ? (
        <div className="audit-issue__collapsed">
          {isSelectable && (
            <div className="audit-issue__chip-row">
              {previewItems.map((item) => (
                <span key={item} className="audit-issue__chip">
                  {item}
                </span>
              ))}
              {hiddenItemCount > 0 && <span className="audit-issue__chip audit-issue__chip--more">+{hiddenItemCount} more</span>}
            </div>
          )}
          <div className="audit-issue__collapsed-footer">
            <div className="audit-issue__meta">
              <span className="audit-issue__meta-item">
                <span className={`audit-issue__impact-dot audit-issue__impact-dot--${issue.severity}`} />
                Impact: {IMPACT_LABELS[issue.severity]}
              </span>
              <span className="audit-issue__meta-item audit-issue__meta-item--muted">{recommendationFor(issue.category)}</span>
            </div>
            {issue.requires_decision && (
              <button type="button" className="audit-issue__review-btn" onClick={() => setExpanded(true)}>
                Review &amp; Decide
                <IconChevronRight />
              </button>
            )}
          </div>
        </div>
      ) : (
        <div className="audit-issue__expanded">
          {issue.sample.length > 0 && (
            <button type="button" className="audit-issue__sample-toggle" onClick={() => setShowSample((s) => !s)}>
              {showSample ? "Hide" : "Show"} sample rows ({issue.sample.length})
            </button>
          )}
          {showSample && issue.sample.length > 0 && (
            <div className="audit-issue__sample-wrap">
              <table className="audit-issue__sample-table">
                <thead>
                  <tr>
                    {Object.keys(issue.sample[0]).map((col) => (
                      <th key={col}>{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {issue.sample.map((row, idx) => (
                    <tr key={idx}>
                      {Object.keys(issue.sample[0]).map((col) => (
                        <td key={col}>{row[col] === null || row[col] === undefined ? "—" : String(row[col])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {isSelectable ? (
            <div className="audit-issue__checklist-block">
              <div className="audit-issue__checklist-toolbar">
                <span className="audit-issue__checklist-count">{checked.size} of {issue.selectable_items.length} selected</span>
                <div className="audit-issue__checklist-links">
                  <button type="button" className="audit-issue__link" onClick={() => setChecked(new Set(issue.selectable_items))}>
                    Select all
                  </button>
                  <button type="button" className="audit-issue__link" onClick={() => setChecked(new Set())}>
                    Select none
                  </button>
                </div>
              </div>
              <ul className="audit-issue__checklist">
                {issue.selectable_items.map((item) => (
                  <li key={item} className="audit-issue__checklist-item">
                    <label>
                      <input
                        type="checkbox"
                        checked={checked.has(item)}
                        disabled={resolving}
                        onChange={() => toggleItem(item)}
                      />
                      <span>{item}</span>
                    </label>
                  </li>
                ))}
              </ul>
              <div className="audit-issue__actions">
                {dropOption && (
                  <button
                    type="button"
                    className="audit-issue__btn audit-issue__btn--primary"
                    disabled={resolving || checked.size === 0}
                    onClick={() => onResolve(issue.id, dropOption.id, Array.from(checked))}
                  >
                    {dropOption.label} ({checked.size})
                  </button>
                )}
                {keepOption && (
                  <button
                    type="button"
                    className="audit-issue__btn audit-issue__btn--secondary"
                    disabled={resolving}
                    onClick={() => onResolve(issue.id, keepOption.id)}
                  >
                    {keepOption.label}
                  </button>
                )}
                <button type="button" className="audit-issue__link audit-issue__collapse-btn" onClick={() => setExpanded(false)}>
                  Collapse
                </button>
              </div>
            </div>
          ) : issue.requires_decision ? (
            <div className="audit-issue__actions">
              {issue.options.map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  className={`audit-issue__btn ${opt.id === "keep" ? "audit-issue__btn--secondary" : "audit-issue__btn--primary"}`}
                  disabled={resolving}
                  onClick={() => onResolve(issue.id, opt.id)}
                >
                  {opt.label}
                </button>
              ))}
              <button type="button" className="audit-issue__link audit-issue__collapse-btn" onClick={() => setExpanded(false)}>
                Collapse
              </button>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
