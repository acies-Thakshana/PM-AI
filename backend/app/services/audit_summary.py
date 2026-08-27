"""Headline sentence for an audit report -- a plain-English read on how
clean the data is overall. Tries an LLM-written summary first (via Groq --
see groq_client.py), since a genuinely interpretive verdict ("is this fit to
use") reads more naturally than a fixed template can produce; falls back to
a deterministic, rule-based sentence -- built only from counts/labels
already present on the findings computed by data_audit.py -- if Groq isn't
configured or the call fails, so an audit upload never blocks on an
unavailable/rate-limited LLM.

The AI never decides what the findings ARE or fixes anything itself (that's
still 100% data_audit.py) -- it only narrates findings already computed, and
is told not to invent a number, name, or count that isn't in the list given.
"""
from app.schemas import AuditIssue
from app.services import groq_client

SYSTEM_PROMPT = """You are a meticulous data analyst reviewing an operational \
cold-chain shipment export before it gets used for reporting. You've been \
given a list of deterministic data-quality findings (already computed -- do \
not invent new ones, contradict the numbers given, or invent column/row \
counts). Write exactly 1-2 plain-English sentences giving an overall read on \
how clean the data is and whether it's fit to use once the flagged findings \
are resolved. Do NOT list, restate, or summarize each finding individually --\
headline verdict only. Plain prose, no markdown, no bullet lists, no \
restating these instructions."""


def _findings_block(row_count: int, column_count: int, issues: list[AuditIssue]) -> str:
    lines = [f"Rows: {row_count}", f"Columns: {column_count}", f"Findings: {len(issues)}"]
    if not issues:
        lines.append("No data-quality issues were detected.")
    for issue in issues:
        base_category = issue.category.split("::")[0]
        if row_count:
            pct = issue.affected_row_count / row_count * 100
            scope_note = f"{issue.affected_row_count} of {row_count} rows/columns ({pct:.1f}%)"
        else:
            scope_note = f"{issue.affected_row_count} rows/columns"
        lines.append(f"- category={base_category} [{issue.severity}] {issue.title}, affected: {scope_note}: {issue.description}")
    return "\n".join(lines)


def _generate_ai_summary(row_count: int, column_count: int, issues: list[AuditIssue]) -> str:
    user_prompt = f"{_findings_block(row_count, column_count, issues)}\n\nWrite the summary now."
    return groq_client.chat_text(SYSTEM_PROMPT, user_prompt).strip()


def _generate_deterministic_summary(row_count: int, column_count: int, issues: list[AuditIssue]) -> str:
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


def generate_summary(row_count: int, column_count: int, issues: list[AuditIssue]) -> str:
    try:
        summary = _generate_ai_summary(row_count, column_count, issues)
        if summary:
            return summary
    except Exception:
        pass
    return _generate_deterministic_summary(row_count, column_count, issues)
