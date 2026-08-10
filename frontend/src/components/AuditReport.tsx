import { useMemo, useState } from "react";
import type { AuditIssue, AuditReport as AuditReportData } from "../api/audit";
import AuditIssueCard, { COLUMN_SCOPED_CATEGORIES } from "./AuditIssueCard";
import StatTile from "./StatTile";
import { IconDoc, IconGrid, IconSearch, IconWarnTriangle, IconClipboard, IconInfo } from "./icons";
import "./AuditReport.css";

interface AuditReportProps {
  report: AuditReportData;
  onResolve: (issueId: string, decisionId: string, selectedItems?: string[]) => void;
  onRevert: (issueId: string) => void;
  resolvingIssueId: string | null;
}

type Tab = "quality" | "suggestions";

// Minor/statistical categories go in the Suggestions tab; everything else
// (structural problems, duplicates, logic violations, missing identifiers)
// is a core data-quality question that blocks confident analysis.
const SUGGESTION_CATEGORIES = new Set(["high_null_columns", "constant_value_columns"]);

function classifyIssue(issue: AuditIssue): Tab {
  if (issue.category.startsWith("statistical_outliers::")) return "suggestions";
  if (SUGGESTION_CATEGORIES.has(issue.category)) return "suggestions";
  return "quality";
}

// Resolution text is always machine-generated (see backend apply_decision) so
// the leading count is safe to parse back out for a rollup, rather than
// re-deriving it from selectable_items/affected_row_count which may have
// shifted since the issue was first detected.
function parseLeadingCount(resolution: string): number | null {
  const match = resolution.match(/^(?:Dropped|Removed) (\d+)/);
  return match ? Number(match[1]) : null;
}

function summarizeChanges(resolvedIssues: AuditIssue[]) {
  let columnsDropped = 0;
  let rowsRemoved = 0;
  let keptCount = 0;
  for (const issue of resolvedIssues) {
    const resolution = issue.resolution ?? "";
    if (resolution.startsWith("Kept")) {
      keptCount += 1;
      continue;
    }
    const count = parseLeadingCount(resolution);
    if (count === null) continue;
    if (COLUMN_SCOPED_CATEGORIES.has(issue.category)) columnsDropped += count;
    else rowsRemoved += count;
  }
  return { columnsDropped, rowsRemoved, keptCount };
}

function pluralize(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function joinClauses(clauses: string[]): string {
  if (clauses.length === 0) return "";
  if (clauses.length === 1) return `${clauses[0]}.`;
  return `${clauses.slice(0, -1).join(", ")}, and ${clauses[clauses.length - 1]}.`;
}

export default function AuditReport({ report, onResolve, onRevert, resolvingIssueId }: AuditReportProps) {
  const decisionIssues = report.issues.filter((i) => i.requires_decision);
  const pendingCount = decisionIssues.filter((i) => i.status === "pending").length;
  const resolvedCount = decisionIssues.length - pendingCount;
  const criticalCount = report.issues.filter((i) => i.severity === "critical").length;
  const warningCount = report.issues.filter((i) => i.severity === "warning").length;

  const qualityIssues = useMemo(() => report.issues.filter((i) => classifyIssue(i) === "quality"), [report.issues]);
  const suggestionIssues = useMemo(
    () => report.issues.filter((i) => classifyIssue(i) === "suggestions"),
    [report.issues]
  );
  const resolvedIssues = useMemo(
    () => decisionIssues.filter((i) => i.status === "resolved" && i.resolution),
    [decisionIssues]
  );

  const [activeTab, setActiveTab] = useState<Tab>("quality");
  const [showChangeDetails, setShowChangeDetails] = useState(false);

  const activeIssues = activeTab === "quality" ? qualityIssues : suggestionIssues;

  const changeTotals = useMemo(() => summarizeChanges(resolvedIssues), [resolvedIssues]);
  const originalRowCount = report.row_count + changeTotals.rowsRemoved;
  const originalColumnCount = report.column_count + changeTotals.columnsDropped;
  const datasetChanged = changeTotals.columnsDropped > 0 || changeTotals.rowsRemoved > 0;

  const summaryClauses: string[] = [];
  if (changeTotals.columnsDropped > 0) summaryClauses.push(`dropped ${pluralize(changeTotals.columnsDropped, "column")}`);
  if (changeTotals.rowsRemoved > 0) summaryClauses.push(`removed ${pluralize(changeTotals.rowsRemoved, "row")}`);
  if (changeTotals.keptCount > 0) summaryClauses.push(`kept ${pluralize(changeTotals.keptCount, "finding")} as-is`);
  const summarySentence = joinClauses(summaryClauses);

  return (
    <div className="audit-report">
      <div className="audit-report__header">
        <span className="audit-report__label">Data Audit Agent</span>
        <span
          className={`audit-report__status audit-report__status--${
            report.status === "reviewed" ? "reviewed" : "pending"
          }`}
        >
          {report.status === "reviewed" ? "Reviewed" : `${pendingCount} decision${pendingCount === 1 ? "" : "s"} needed`}
        </span>
      </div>

      <div className="audit-report__overview">
        <StatTile icon={<IconDoc />} color="blue" value={report.row_count.toLocaleString()} label="Rows" />
        <StatTile icon={<IconGrid />} color="teal" value={report.column_count} label="Columns" />
        <StatTile icon={<IconSearch />} color="purple" value={report.issues.length} label="Findings" />
        {criticalCount > 0 && <StatTile icon={<IconWarnTriangle />} color="error" value={criticalCount} label="Critical" />}
        {warningCount > 0 && <StatTile icon={<IconWarnTriangle />} color="amber" value={warningCount} label="Warning" />}
        <StatTile icon={<IconClipboard />} color="blue" value={`${resolvedCount}/${decisionIssues.length}`} label="Decisions" />
      </div>

      {report.summary && (
        <div className="audit-report__summary">
          <span className="audit-report__summary-icon">
            <IconInfo />
          </span>
          <p className="audit-report__summary-text">{report.summary}</p>
        </div>
      )}

      {resolvedCount > 0 && (
        <div
          className={`audit-report__changes ${
            report.status === "reviewed" ? "audit-report__changes--complete" : ""
          }`}
        >
          <div className="audit-report__changes-head">
            <span className="audit-report__changes-icon">{report.status === "reviewed" ? "✓" : "…"}</span>
            <div className="audit-report__changes-copy">
              <p className="audit-report__changes-title">
                {report.status === "reviewed"
                  ? "Audit complete -- here's what changed"
                  : `${resolvedCount} of ${decisionIssues.length} findings resolved so far`}
              </p>
              <p className="audit-report__changes-sentence">
                {summarySentence || "No changes made yet -- every finding so far was kept as-is."}
                {datasetChanged && (
                  <>
                    {" "}Dataset is now <strong>{report.row_count.toLocaleString()}</strong> rows ×{" "}
                    <strong>{report.column_count}</strong> columns (from {originalRowCount.toLocaleString()} ×{" "}
                    {originalColumnCount}).
                  </>
                )}
              </p>
            </div>
          </div>
          <button
            type="button"
            className="audit-report__changes-toggle"
            onClick={() => setShowChangeDetails((s) => !s)}
          >
            {showChangeDetails ? "Hide details" : `View details (${resolvedCount})`}
          </button>
          {showChangeDetails && (
            <ul className="audit-report__changes-list">
              {resolvedIssues.map((issue) => (
                <li key={issue.id}>
                  <span className="audit-report__changes-item-title">{issue.title}:</span> {issue.resolution}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {report.issues.length > 0 && (
        <>
          <div className="audit-report__tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "quality"}
              className={`audit-report__tab ${activeTab === "quality" ? "audit-report__tab--active" : ""}`}
              onClick={() => setActiveTab("quality")}
            >
              Overall Data Quality Check
              <span className="audit-report__tab-count">{qualityIssues.length}</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "suggestions"}
              className={`audit-report__tab ${activeTab === "suggestions" ? "audit-report__tab--active" : ""}`}
              onClick={() => setActiveTab("suggestions")}
            >
              Suggestions
              <span className="audit-report__tab-count">{suggestionIssues.length}</span>
            </button>
          </div>

          <div className="audit-report__issues">
            {activeIssues.length > 0 ? (
              activeIssues.map((issue) => (
                <AuditIssueCard
                  key={issue.id}
                  issue={issue}
                  onResolve={onResolve}
                  onRevert={onRevert}
                  resolving={resolvingIssueId === issue.id}
                  revertLocked={
                    issue.status === "resolved" &&
                    !(issue.resolution ?? "").startsWith("Kept") &&
                    issue.id !== report.revertible_issue_id
                  }
                />
              ))
            ) : (
              <p className="audit-report__empty-tab">
                {activeTab === "quality" ? "No core data-quality issues found." : "No minor suggestions found."}
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
