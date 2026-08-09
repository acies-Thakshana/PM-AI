import { useState } from "react";
import type { AuditIssue } from "../api/audit";
import "./AuditIssueCard.css";

const COLUMN_SCOPED_CATEGORIES = new Set(["fully_empty_columns", "high_null_columns", "constant_value_columns"]);

interface AuditIssueCardProps {
  issue: AuditIssue;
  onResolve: (issueId: string, decisionId: string, selectedItems?: string[]) => void;
  resolving: boolean;
}

export default function AuditIssueCard({ issue, onResolve, resolving }: AuditIssueCardProps) {
  const [showSample, setShowSample] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(() => new Set(issue.selectable_items));
  const unit = COLUMN_SCOPED_CATEGORIES.has(issue.category) ? "column(s)" : "row(s)";
  const isSelectable = issue.selectable_items.length > 0;

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

      {issue.status === "resolved" ? (
        <p className="audit-issue__resolution">✓ {issue.resolution}</p>
      ) : isSelectable ? (
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
        </div>
      ) : null}
    </div>
  );
}
