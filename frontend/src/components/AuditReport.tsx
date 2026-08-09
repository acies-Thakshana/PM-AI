import type { AuditReport as AuditReportData } from "../api/audit";
import AuditIssueCard from "./AuditIssueCard";
import "./AuditReport.css";

interface AuditReportProps {
  report: AuditReportData;
  onResolve: (issueId: string, decisionId: string, selectedItems?: string[]) => void;
  resolvingIssueId: string | null;
}

export default function AuditReport({ report, onResolve, resolvingIssueId }: AuditReportProps) {
  const decisionIssues = report.issues.filter((i) => i.requires_decision);
  const pendingCount = decisionIssues.filter((i) => i.status === "pending").length;
  const resolvedCount = decisionIssues.length - pendingCount;
  const criticalCount = report.issues.filter((i) => i.severity === "critical").length;
  const warningCount = report.issues.filter((i) => i.severity === "warning").length;

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
        <div className="audit-report__tile">
          <span className="audit-report__tile-value">{report.row_count.toLocaleString()}</span>
          <span className="audit-report__tile-label">Rows</span>
        </div>
        <div className="audit-report__tile">
          <span className="audit-report__tile-value">{report.column_count}</span>
          <span className="audit-report__tile-label">Columns</span>
        </div>
        <div className="audit-report__tile">
          <span className="audit-report__tile-value">{report.issues.length}</span>
          <span className="audit-report__tile-label">Findings</span>
        </div>
        {criticalCount > 0 && (
          <div className="audit-report__tile audit-report__tile--critical">
            <span className="audit-report__tile-value">{criticalCount}</span>
            <span className="audit-report__tile-label">Critical</span>
          </div>
        )}
        {warningCount > 0 && (
          <div className="audit-report__tile audit-report__tile--warning">
            <span className="audit-report__tile-value">{warningCount}</span>
            <span className="audit-report__tile-label">Warning</span>
          </div>
        )}
        <div className="audit-report__tile">
          <span className="audit-report__tile-value">
            {resolvedCount}/{decisionIssues.length}
          </span>
          <span className="audit-report__tile-label">Decisions</span>
        </div>
      </div>

      {report.summary && <p className="audit-report__summary">{report.summary}</p>}

      {report.issues.length > 0 && (
        <div className="audit-report__issues">
          {report.issues.map((issue) => (
            <AuditIssueCard
              key={issue.id}
              issue={issue}
              onResolve={onResolve}
              resolving={resolvingIssueId === issue.id}
            />
          ))}
        </div>
      )}
    </div>
  );
}
