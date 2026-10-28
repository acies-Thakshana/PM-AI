"""The chat's events in the audit log: the one place that names them and shapes their payloads.

The session, the user and (through request_context) the turn come from the request, so a caller says only what
happened. The turn row in the chat table (chat_store.py) keeps the conversation; these events keep how the
answer was made: which tools ran, which actions were proposed and what became of them, what went wrong.
Logging never raises (see audit_log.log_event).

The LLM calls of a turn are logged as `llm_call` by token_usage.record, with the same chat_id / turn_id.
"""
from __future__ import annotations

import json
from typing import Any

from app.services.common import audit_log, request_context

MAX_ERROR_CHARS = 200

# The record an item belongs to, written as the docs table names it ("ANALYSES#<id>"), so that "everything that
# happened to this analysis" (audit_log.events_for_target) also finds the chat turns that read or opened it.
_TOOL_TARGET = {"get_analysis": "ANALYSES", "get_feature": "FEATURES"}
_PAGE_TARGET = {"analysis": "ANALYSES", "features": "FEATURES"}
_ACTION_TARGET = {"add_analysis": "ANALYSES", "add_feature": "FEATURES"}


def _log(event_type: str, payload: dict[str, Any], *, target: str | None = None, result: str | None = None) -> None:
    audit_log.log_event(
        request_context.current_session_id.get(),
        request_context.user_id(),
        event_type,
        payload,
        target=target,
        result=result,
    )


def message(role: str, chars: int, **details: Any) -> None:
    """A message of the turn was stored (the PM's, or the assistant's reply)."""
    _log("chat_message", {"role": role, "chars": chars, **details})


def tool_call(tool: str, args: dict, result: dict, milliseconds: int) -> None:
    """One tool the assistant used. A tool never raises: a failure is an {"error": ...} result."""
    error = result.get("error")
    payload: dict[str, Any] = {
        "tool": tool,
        "args": args,
        "ok": not error,
        "ms": milliseconds,
        "result_chars": len(json.dumps(result, default=str)),
    }
    if error:
        payload["error"] = str(error)[:MAX_ERROR_CHARS]
    item_id = args.get("id")
    prefix = _TOOL_TARGET.get(tool)
    target = f"{prefix}#{item_id}" if prefix and isinstance(item_id, str) and item_id else None
    _log("chat_tool_call", payload, target=target, result="failed" if error else "ok")


def action(proposed: dict, status: str) -> None:
    """An action the assistant proposed ("proposed"), one the app refused ("refused_audit", "refused_intent"), or
    what became of it in the browser ("applied", "failed", "blocked", "skipped")."""
    kind = str(proposed.get("type") or "")
    payload: dict[str, Any] = {"action": kind, "status": status}
    for name in ("page", "open", "name", "entry_id"):
        if proposed.get(name):
            payload[name] = proposed[name]
    item_id = proposed.get("open") or proposed.get("entry_id")
    prefix = _ACTION_TARGET.get(kind) or _PAGE_TARGET.get(str(proposed.get("page") or ""))
    target = f"{prefix}#{item_id}" if prefix and item_id else None
    _log("chat_action", payload, target=target, result="failed" if status == "failed" else "ok")


def grounding_review(before: list[str], after: list[str]) -> None:
    """The reply quoted figures nobody had shown the assistant, so it was asked again: which, and which remain."""
    _log("chat_grounding_review", {"unverified_before": before, "unverified_after": after})


def error(error_code: str, http_status: int, detail: str) -> None:
    """The turn failed."""
    _log(
        "chat_error",
        {"error_code": error_code, "http": http_status, "error": detail[:MAX_ERROR_CHARS]},
        result="failed",
    )
