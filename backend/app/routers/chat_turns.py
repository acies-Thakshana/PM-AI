"""What the browser adds to the chat's turn record (services/chat/chat_store.py).

`POST /api/chat/turns` stores a turn the browser answered itself: a message that never goes to the model (a brief
typed on the Configure page, "suggest an analysis", "Add an analysis: ..."). The turns the model answers are stored
by `POST /api/chat/turn` itself.

`POST /api/chat/turns/{chat}/{turn}/finish` adds what happens after the reply: the app's own short notes, what
became of each action the assistant proposed, the actions and suggestions the browser made itself.

`POST /api/chat/turns/{chat}/{turn}/suggestions/{entry}` says whether the PM accepted or rejected a suggestion
the turn made.

Recording is best effort and never changes what the chat does: every call answers {"ok": true|false} and a
failure is only logged. Only the PM who made a turn may add to it.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, Field

from app.routers.deps import User, get_user, require_owned
from app.services.chat import chat_events, chat_store
from app.services.chat.turn_recorder import TurnRecorder, bound
from app.services.common import request_context

router = APIRouter(prefix="/api/chat/turns", tags=["chat"])

ActionStatus = Literal["applied", "failed", "blocked", "skipped"]
MAX_ITEMS = 30


class TurnStartIn(BaseModel):
    chat_id: str = Field(pattern=chat_store.ID_PATTERN)
    turn_id: str = Field(pattern=chat_store.ID_PATTERN)
    user_text: str
    handled_by: Literal["shortcut_suggest", "shortcut_own", "brief_local"]
    session_id: str | None = None
    page: str = Field(default="", max_length=30)
    phase: str = Field(default="", max_length=30)
    hidden: bool = False


class NoteIn(BaseModel):
    content: str = Field(max_length=2000)
    kind: Literal["notice", "error"] = "notice"


class OutcomeIn(BaseModel):
    """What became of the assistant's action number `index` (its position in the reply's actions)."""

    index: int = Field(ge=0, le=MAX_ITEMS)
    type: str = Field(max_length=30)
    status: ActionStatus
    entry_id: str | None = Field(default=None, max_length=128)


class AppActionIn(BaseModel):
    """Something the browser did on its own, with no model action behind it (opened a page, added an item)."""

    type: str = Field(max_length=30)
    status: ActionStatus
    page: str | None = Field(default=None, max_length=30)
    name: str | None = Field(default=None, max_length=200)
    entry_id: str | None = Field(default=None, max_length=128)


class SuggestionIn(BaseModel):
    kind: Literal["analysis", "feature"]
    entry_id: str = Field(max_length=128)
    name: str = Field(max_length=200)


class TurnFinishIn(BaseModel):
    status: Literal["completed", "failed"] | None = None
    error_code: str | None = Field(default=None, max_length=40)
    notes: list[NoteIn] = Field(default_factory=list, max_length=MAX_ITEMS)
    outcomes: list[OutcomeIn] = Field(default_factory=list, max_length=MAX_ITEMS)
    app_actions: list[AppActionIn] = Field(default_factory=list, max_length=MAX_ITEMS)
    suggestions: list[SuggestionIn] = Field(default_factory=list, max_length=MAX_ITEMS)


class DecisionIn(BaseModel):
    status: Literal["accepted", "rejected"]


def _id_path() -> object:
    """A path parameter that is a chat or turn id (a fresh one per parameter: FastAPI keeps state on it)."""
    return Path(pattern=chat_store.ID_PATTERN)


def _own_turn(chat_id: str, turn_id: str) -> dict | None:
    """The stored turn when it exists and belongs to the caller; the session of its events is set from it."""
    try:
        item = chat_store.get_turn(chat_id, turn_id)
    except Exception:  # noqa: BLE001 - recording is best effort
        return None
    if item is None or item.get("user_id") != request_context.user_id():
        return None
    request_context.current_session_id.set(item.get("session_id"))
    return item


@router.post("")
def start_turn(body: TurnStartIn, user: User = Depends(get_user)) -> dict:
    if body.session_id:
        require_owned(body.session_id, user)  # 404 for a session that is not the caller's
    recorder = TurnRecorder.begin(
        chat_id=body.chat_id, turn_id=body.turn_id, user_text=body.user_text, handled_by=body.handled_by,
        session_id=body.session_id, state={"stage": body.page, "phase": body.phase}, hidden=body.hidden,
    )
    recorder.close()
    return {"ok": recorder.active}


@router.post("/{chat_id}/{turn_id}/finish")
def finish_turn(body: TurnFinishIn, chat_id: str = _id_path(), turn_id: str = _id_path()) -> dict:
    if _own_turn(chat_id, turn_id) is None:
        return {"ok": False}
    with bound(chat_id, turn_id):
        for outcome in body.outcomes:
            chat_events.action({"type": outcome.type, "entry_id": outcome.entry_id}, outcome.status)
        for app_action in body.app_actions:
            chat_events.action(app_action.model_dump(exclude_none=True), app_action.status)
        if body.status == "failed":
            chat_events.error(body.error_code or "CHAT_ERROR", 0, "The browser reported the turn failed.")
    done = chat_store.finish_turn(
        chat_id, turn_id, user_id=request_context.user_id(),
        status=body.status, error_code=body.error_code,
        notes=[n.model_dump() for n in body.notes],
        outcomes=[o.model_dump(exclude={"type"}) for o in body.outcomes],
        app_actions=[a.model_dump(exclude_none=True) for a in body.app_actions],
        suggestions=[s.model_dump() for s in body.suggestions],
    )
    return {"ok": done}


@router.post("/{chat_id}/{turn_id}/suggestions/{entry_id}")
def decide_suggestion(
    body: DecisionIn, entry_id: str = Path(max_length=128), chat_id: str = _id_path(), turn_id: str = _id_path(),
) -> dict:
    if _own_turn(chat_id, turn_id) is None:
        return {"ok": False}
    done = chat_store.mark_suggestion(
        chat_id, turn_id, user_id=request_context.user_id(), entry_id=entry_id, status=body.status,
    )
    return {"ok": done}
