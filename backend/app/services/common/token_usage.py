"""Tracks input/output token usage for every LLM call in the pipeline.

Each of the 8 LLM calls (Planner, Feature Agent think/write/validate,
Feature Suggester, Audit Agent, Pivot Suggester, Overall Analysis) calls
`record()` right after getting its Bedrock response, tagged with a
`call_name` identifying which of the 8 calls it was. Usage is kept in memory
for the life of the process and also appended to a JSONL file so it survives
restarts and can be reviewed later. The chat's calls (config.CHAT_CALLS) are also written to the
audit log as an `llm_call` event, attributed to the current user/session (see request_context).
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

from app.config import BACKEND_DIR, CHAT_CALLS
from app.services.common import audit_log, request_context

LOG_PATH = BACKEND_DIR / "data" / "token_usage.jsonl"

_lock = threading.Lock()
_records: list["TokenUsage"] = []


@dataclass
class TokenUsage:
    call_name: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    timestamp: float
    user_id: str | None = None


# Where the output of each kind of call is stored. `{e}` is the feature / analysis entry being
# computed (request_context.current_entry_id); a call with no stored output maps to None.
_OUTPUT_REFS: dict[str, str | None] = {
    "feature_agent_think": "FEATURES#{e}",
    "feature_agent_write_code": "FEATURES#{e}",
    "feature_agent_validate": "FEATURES#{e}",
    "analysis_agent_think": "ANALYSES#{e}",
    "analysis_agent_write_code": "ANALYSES#{e}",
    "analysis_agent_chart_suggestion": "ANALYSES#{e}",
    "analysis_designer_template_match": "ANALYSES#{e}",
    "analysis_designer_chart": "ANALYSES#{e}",
    "analysis_agent_interpret": "RESULT#{e}",
    "analysis_agent_drilldown": "RESULT#{e}",
    "drilldown_agent": "RESULT#{e}",
    "drilldown_agent_more": "RESULT#{e}",
    "drilldown_path": "DRILL#{e}",
    "planner_agent": "PLAN",
    "feature_suggester": "FEATURES",
    "analysis_suggester": "ANALYSES",
    "overall_analysis_agent": "OVERALL",
    "audit_agent": "SESSIONS",
    "report_final_summary_agent": None,
}


def output_ref(call_name: str) -> str | None:
    """Name of the stored document this call's output lands in (not the output itself)."""
    template = _OUTPUT_REFS.get(call_name)
    if template is None:
        return None
    entry_id = request_context.current_entry_id.get()
    if "{e}" in template:
        return template.format(e=entry_id) if entry_id else None
    return template


def record(call_name: str, model: str, usage: dict[str, Any] | None) -> TokenUsage | None:
    """Store the usage block of a Bedrock Converse response (`inputTokens`, `outputTokens`,
    `totalTokens`). Returns None if there is no usage block -- callers must not fail on that."""
    if not usage:
        return None
    input_tokens = int(usage.get("inputTokens", 0) or 0)
    output_tokens = int(usage.get("outputTokens", 0) or 0)
    total_tokens = int(usage.get("totalTokens", 0) or 0) or (input_tokens + output_tokens)
    user_id = request_context.current_user_id.get()
    entry = TokenUsage(
        call_name=call_name,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        timestamp=time.time(),
    )

    with _lock:
        _records.append(entry)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry)) + "\n")

    if call_name in CHAT_CALLS:
        # Only the chat's calls reach the audit log for now, so a chat turn shows what it cost (never raises).
        audit_log.log_event(
            request_context.current_session_id.get(),
            user_id,
            "llm_call",
            {"call_name": call_name, "model": model, "input_tokens": input_tokens,
             "output_tokens": output_tokens, "total_tokens": total_tokens},
        )

    return entry


def get_records(user_id: str | None = None) -> list[TokenUsage]:
    with _lock:
        records = list(_records)
    if user_id is not None:
        records = [r for r in records if r.user_id == user_id]
    return records


def summary_by_call(user_id: str | None = None) -> dict[str, dict[str, int]]:
    """Aggregate call count and token totals per call_name, across the
    life of this process (optionally only for one user)."""
    totals: dict[str, dict[str, int]] = {}
    for r in get_records(user_id):
        bucket = totals.setdefault(
            r.call_name,
            {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        bucket["calls"] += 1
        bucket["input_tokens"] += r.input_tokens
        bucket["output_tokens"] += r.output_tokens
        bucket["total_tokens"] += r.total_tokens
    return totals
