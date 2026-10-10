"""Tracks input/output token usage for every LLM call in the pipeline.

Each of the 8 LLM calls (Planner, Feature Agent think/write/validate,
Feature Suggester, Audit Agent, Pivot Suggester, Overall Analysis) calls
`record()` right after getting its OpenRouter response, tagged with a
`call_name` identifying which of the 8 calls it was. Usage is kept in memory
for the life of the process and also appended to a JSONL file so it survives
restarts and can be reviewed later. Each call is also written to the audit log as an
`llm_call` event, attributed to the current user/session (see request_context).
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass

from app.config import BACKEND_DIR
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


def record(call_name: str, model: str, response) -> TokenUsage | None:
    """Extract usage from an OpenAI-compatible chat completion response and
    store it. Returns None if the response carries no usage block (some
    OpenRouter models omit it) -- callers should not fail on that."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None

    user_id = request_context.current_user_id.get()
    entry = TokenUsage(
        call_name=call_name,
        model=model,
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        total_tokens=getattr(usage, "total_tokens", 0) or 0,
        timestamp=time.time(),
    )

    with _lock:
        _records.append(entry)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry)) + "\n")

    return entry


def get_records() -> list[TokenUsage]:
    with _lock:
        return list(_records)


def summary_by_call() -> dict[str, dict[str, int]]:
    """Aggregate call count and token totals per call_name, across the
    life of this process."""
    totals: dict[str, dict[str, int]] = {}
    for r in get_records():
        bucket = totals.setdefault(
            r.call_name,
            {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        bucket["calls"] += 1
        bucket["input_tokens"] += r.input_tokens
        bucket["output_tokens"] += r.output_tokens
        bucket["total_tokens"] += r.total_tokens
    return totals
