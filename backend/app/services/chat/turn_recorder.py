"""Records one chat turn: its row in the chat table (chat_store) and its events (chat_events).

`TurnRecorder.begin` is called when a PM message reaches the server, `complete` / `fail` when the answer is
ready or the turn broke, and `close` when the request is over. A request that carries no (valid) chat and turn
id gets an inactive recorder whose methods do nothing, so the chat works exactly as before without them.

While a recorder is open, request_context holds the chat and turn ids: every event and LLM call made while the
turn is answered is tagged with them (see audit_log.log_event).
"""
from __future__ import annotations

import contextlib
import contextvars
import functools
import logging
from typing import Any, Callable, Iterator

from app.services.chat import chat_events, chat_store
from app.services.common import request_context

log = logging.getLogger(__name__)

# The tool behind each kind of item the assistant can read (the kinds orchestrator.run_turn reports as `looked_at`).
_TOOL_OF_KIND = {"analysis": "get_analysis", "feature": "get_feature"}


def reads_of(tools_used: list[str], looked_at: list[tuple[str, str]]) -> list[dict]:
    """What the answer was based on: each analysis or calculation the assistant read (with its id), then the other
    tools it used."""
    reads = [{"tool": _TOOL_OF_KIND[kind], "id": item_id} for kind, item_id in dict.fromkeys(looked_at) if kind in _TOOL_OF_KIND]
    reads += [{"tool": tool} for tool in dict.fromkeys(tools_used) if tool not in _TOOL_OF_KIND.values()]
    return reads


def _action_row(action: dict, status: str) -> dict:
    """An action as the turn keeps it. A `set_brief` text is the PM's own message, which the turn already holds."""
    row = {key: value for key, value in action.items() if not (action.get("type") == "set_brief" and key == "text")}
    if action.get("type") == "set_brief":
        row["chars"] = len(str(action.get("text") or ""))
    return {**row, "source": "model", "status": status}


def _has_understanding(understanding: Any) -> bool:
    return isinstance(understanding, dict) and any(understanding.values())


def _never_raise(fn: Callable[..., None]) -> Callable[..., None]:
    """Recording a turn is never worth failing the PM's request."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> None:
        try:
            fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            log.warning("turn recorder: %s failed: %s", fn.__name__, exc)

    return wrapper


@contextlib.contextmanager
def bound(chat_id: str, turn_id: str) -> Iterator[None]:
    """Tag the events made inside the block with this turn."""
    tokens = (request_context.current_chat_id.set(chat_id), request_context.current_turn_id.set(turn_id))
    try:
        yield
    finally:
        request_context.current_chat_id.reset(tokens[0])
        request_context.current_turn_id.reset(tokens[1])


class TurnRecorder:
    def __init__(self, chat_id: str | None = None, turn_id: str | None = None, user_id: str | None = None):
        self.chat_id = chat_id
        self.turn_id = turn_id
        self.user_id = user_id
        self._tokens: tuple[contextvars.Token, contextvars.Token] | None = None

    @property
    def active(self) -> bool:
        return bool(self.chat_id and self.turn_id)

    @classmethod
    def begin(
        cls,
        *,
        chat_id: str | None,
        turn_id: str | None,
        user_text: str,
        handled_by: str = "chat_model",
        session_id: str | None = None,
        state: dict | None = None,
        hidden: bool = False,
    ) -> "TurnRecorder":
        """Store the PM's message and start tagging events with the turn. Inactive when the ids are missing or unusable."""
        if not (chat_store.is_safe_id(chat_id) and chat_store.is_safe_id(turn_id)):
            return cls()
        recorder = cls(chat_id, turn_id, request_context.user_id())
        recorder._tokens = (request_context.current_chat_id.set(chat_id), request_context.current_turn_id.set(turn_id))
        state = state or {}
        try:
            chat_store.start_turn(
                chat_id,
                turn_id,
                user_id=recorder.user_id,
                user_text=user_text,
                handled_by=handled_by,
                session_id=session_id,
                page=str(state.get("stage") or ""),
                phase=str(state.get("phase") or ""),
                hidden=hidden,
            )
            chat_events.message("user", len(user_text), handled_by=handled_by)
        except Exception as exc:  # noqa: BLE001
            log.warning("turn recorder: begin failed: %s", exc)
        return recorder

    @_never_raise
    def complete(
        self,
        response: dict,
        *,
        tools_used: list[str],
        looked_at: list[tuple[str, str]],
        refusals: dict[str, list[str]] | None = None,
        state: dict | None = None,
    ) -> None:
        """The assistant's answer is ready: keep it, with what it read, proposed and refused."""
        if not self.active:
            return
        state = state or {}
        refusals = refusals or {}
        proposed = [_action_row(a, "proposed") for a in response.get("actions", [])]
        refused = [
            {"type": kind, "source": "model", "status": status}
            for key, status in (("needs_audit", "refused_audit"), ("off_intent", "refused_intent"))
            for kind in refusals.get(key, [])
        ]
        understanding, assumptions = response.get("understanding"), response.get("assumptions")
        previous = state.get("understanding")
        chat_store.complete_turn(
            self.chat_id,
            self.turn_id,
            user_id=self.user_id,
            reply=response.get("reply", ""),
            intent=response.get("intent", ""),
            phase=response.get("phase", ""),
            reads=reads_of(tools_used, looked_at),
            actions=proposed + refused,
            next_questions=response.get("next_questions", []),
            # Kept only when this turn changed them: the rest of the time they are what the turn before left.
            understanding=understanding
            if (_has_understanding(understanding) or _has_understanding(previous)) and understanding != previous
            else None,
            assumptions=assumptions if assumptions != (state.get("assumptions") or []) else None,
        )
        for action in response.get("actions", []):
            chat_events.action(action, "proposed")
        for row in refused:
            chat_events.action(row, row["status"])
        chat_events.message("assistant", len(response.get("reply", "")), intent=response.get("intent"), tools=len(tools_used))

    @_never_raise
    def fail(self, error_code: str, http_status: int, detail: str) -> None:
        if not self.active:
            return
        chat_store.fail_turn(self.chat_id, self.turn_id, user_id=self.user_id, error_code=error_code)
        chat_events.error(error_code, http_status, detail)

    def close(self) -> None:
        """Stop tagging events with this turn (the request is over)."""
        if self._tokens is not None:
            request_context.current_chat_id.reset(self._tokens[0])
            request_context.current_turn_id.reset(self._tokens[1])
            self._tokens = None
