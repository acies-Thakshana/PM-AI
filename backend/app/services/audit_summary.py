"""Deterministic headline sentence for an audit report -- rolls the
findings' severities into one short verdict. Never invents a number: only
counts/labels already present on the findings computed by data_audit.py.
"""
from app.schemas import AuditIssue


def generate_summary(row_count: int, column_count: int, issues: list[AuditIssue]) -> str:
    if not issues:
        return (
            f"No data-quality issues were found across {row_count:,} rows and {column_count} "
            f"columns -- this data looks ready to use."
        )

    critical = sum(1 for i in issues if i.severity == "critical")
    warning = sum(1 for i in issues if i.severity == "warning")
    info = sum(1 for i in issues if i.severity == "info")
    counts_text = ", ".join(
        f"{n} {label}" for n, label in ((critical, "critical"), (warning, "warning"), (info, "informational")) if n
    )

    if critical:
        verdict = "should not be used until the critical findings are resolved"
    elif warning:
        verdict = "is largely usable once the flagged findings are reviewed"
    else:
        verdict = "is clean and ready to use, with a few minor notes to review"

    return (
        f"This dataset has {len(issues)} finding(s) ({counts_text}) across {row_count:,} rows and "
        f"{column_count} columns; it {verdict}."
    )
