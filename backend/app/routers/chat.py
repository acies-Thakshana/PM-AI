"""The chat assistant: interviews the PM about the client brief, then refines the report by conversation.

`POST /api/chat/turn` is one stateless turn: the browser sends the transcript, the brief and the chat's
current state; the model answers with the next reply, the updated understanding, assumptions, quick
replies and a few actions the app carries out (open a page, add an analysis ...). The chat does not plan
the report: the Planner step does, from the brief and the interview.
Nothing here changes the data: the browser performs the actions through the normal endpoints.

`PUT /api/chat/interview/{session_id}` stores the interview (answers and assumptions) next to the
session's brief, so anyone can later see why things were built; the Planner reads it (see planner.py)
before it suggests features and analyses.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import model_for
from app.prompts import chat_agent as _prompts
from app.routers.job_route import JobRoute
from app.services.analysis import analysis_repository
from app.services.audit.audit_store import get_or_404
from app.services.chat import orchestrator
from app.services.chat import tools as chat_tools
from app.services.common import audit_log, column_meta, doc_store, llm
from app.services.features import feature_repository
from app.services.planner.planner import _build_columns_block

log = logging.getLogger(__name__)

router = APIRouter(route_class=JobRoute, prefix="/api/chat", tags=["chat"])

INTERVIEW_DOC = "INTERVIEW"

PHASES = ("interview", "readback", "ready", "build", "refine")
PAGES = ("upload", "planner", "audit", "features", "analysis", "report")
ACTION_TYPES = ("set_brief", "navigate", "add_analysis", "add_feature", "check_ready", "continue_build")
# Features and analyses are built on the audited data: these actions are only passed on once the data is loaded and
# every audit decision is made. (The browser applies the same rule; this keeps the model's reply truthful.)
ACTIONS_NEEDING_AUDITED_DATA = frozenset({"add_analysis", "add_feature"})

# What the PM's last message is. The model names it, and the intent decides which actions it may take: a question
# ("ask") can never change the report, whatever else the model wrote.
INTENTS = ("interview", "ask", "change", "generate", "other")
ACTIONS_BY_INTENT = {
    "interview": frozenset({"set_brief", "navigate"}),
    "ask": frozenset({"navigate", "check_ready"}),
    "change": frozenset({"add_analysis", "add_feature", "navigate"}),
    "generate": frozenset({"set_brief", "continue_build", "navigate", "check_ready"}),
    "other": frozenset({"navigate"}),
}
UNDERSTANDING_KEYS = ("goal", "scope", "period", "limits", "output", "kpis")
# A navigate action may open one item on its page: an analysis on "analysis", a calculation on "features".
OPENABLE_KIND = {"analysis": "analysis", "features": "feature"}

MAX_MESSAGES = 24
MAX_COLUMNS_IN_PROMPT = 60
MAX_ACTIONS = 6          # "add these four analyses" is one message
MAX_NEXT_QUESTIONS = 3


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatTurnRequest(BaseModel):
    session_id: str | None = None
    brief: str = ""
    messages: list[ChatMessage] = Field(default_factory=list)
    # The chat's own state (phase, understanding, assumptions, page, stage, build status ...).
    state: dict[str, Any] = Field(default_factory=dict)


def _data_block(session_id: str | None) -> str:
    """What the loaded data holds, for the model: columns (with their top values), and the analyses and
    features that already exist. Empty when no data is loaded."""
    if not session_id:
        return "No data is loaded yet."
    try:
        meta = column_meta.load(session_id)
        parts: list[str] = []
        if meta:
            cols = dict(list(meta.get("columns", {}).items())[:MAX_COLUMNS_IN_PROMPT])
            parts.append(
                f"{meta.get('row_count', '?')} rows. COLUMNS:\n" + _build_columns_block(cols, meta.get("row_count", 0))
            )
        analyses = [
            f'- {e["name"]} ({e["status"]}, run={e.get("run_status", "not_run")})'
            for e in chat_tools.analyses_of(session_id)
        ]
        feats = [f'- {e["name"]} ({e["status"]})' for e in feature_repository.get_repository(session_id)]
        parts.append("EXISTING ANALYSES:\n" + ("\n".join(analyses) or "(none)"))
        parts.append("EXISTING FEATURES:\n" + ("\n".join(feats) or "(none)"))
        return "\n\n".join(parts)
    except Exception as exc:  # noqa: BLE001 - the chat still works without the data block
        log.warning("chat: could not build the data block for %s: %s", session_id, exc)
        return "The data is loaded but could not be described."


def _clean_text(value: Any, limit: int = 600) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


@dataclass
class CleanedActions:
    actions: list[dict] = field(default_factory=list)
    #: Types dropped because the audited data is not ready.
    needs_audit: list[str] = field(default_factory=list)
    #: Types dropped because the PM's message was not a request for them (e.g. a question that "adds" something).
    off_intent: list[str] = field(default_factory=list)


def _clean_actions(
    actions: Any,
    audited: bool = True,
    intent: str | None = None,
    known_items: dict[str, str] | None = None,
) -> CleanedActions:
    """The model's actions, limited to the known types with clean fields.

    `audited`: whether features and analyses may be added yet. `intent`: when given, only the actions that intent
    allows are kept. `known_items` ({entry id: kind}): a navigate action may only open an item that exists."""
    out = CleanedActions()
    allowed = ACTIONS_BY_INTENT.get(intent) if intent else None
    for a in (actions or [])[:MAX_ACTIONS]:
        if not isinstance(a, dict) or a.get("type") not in ACTION_TYPES:
            continue
        kind = a["type"]
        if allowed is not None and kind not in allowed:
            out.off_intent.append(kind)
            continue
        if kind in ACTIONS_NEEDING_AUDITED_DATA and not audited:
            out.needs_audit.append(kind)
            continue
        if kind == "navigate":
            page = a.get("page")
            if page not in PAGES:
                continue
            action = {"type": kind, "page": page}
            target = a.get("open")
            if isinstance(target, str) and known_items and known_items.get(target) == OPENABLE_KIND.get(page):
                action["open"] = target
            out.actions.append(action)
        elif kind in ("add_analysis", "add_feature"):
            name, desc = _clean_text(a.get("name"), 120), _clean_text(a.get("description"))
            if name and desc:
                out.actions.append({"type": kind, "name": name, "description": desc})
        elif kind == "set_brief":
            text = _clean_text(a.get("text"), 8000)
            if text:
                out.actions.append({"type": kind, "text": text})
        else:
            out.actions.append({"type": kind})
    return out


def _refusal_note(refused: list[str], pending: int | None) -> str:
    """Said after the model's reply when it asked for something the audited data is not ready for."""
    what = "that" if len(refused) == 1 else "those"
    if pending is None:
        why = "load the data and finish the data audit first"
    elif pending > 0:
        why = f"finish the data audit first ({pending} decision{'s' if pending > 1 else ''} left)"
    else:
        why = "finish the data audit first"
    return f"I have not added {what} yet: {why}. Features and analyses are built on the audited data."


OFF_INTENT_NOTE = "I have not changed anything: tell me if you want that added."


def _unverified_note(figures: list[str]) -> str:
    return f"I could not check these figures against the data, so treat them with care: {', '.join(figures)}."


def _intent_of(raw: dict, phase: str) -> str:
    """The intent the model named; when it named none, the interview phases mean an interview answer."""
    if raw.get("intent") in INTENTS:
        return raw["intent"]
    return "interview" if phase in ("interview", "readback", "ready") else "other"


def _clean_questions(value: Any, asked: list[str]) -> list[str]:
    """Follow-up questions to offer: short, distinct, and not something the PM already asked."""
    seen = {q.strip().lower() for q in asked}
    out: list[str] = []
    for q in value if isinstance(value, list) else []:
        text = _clean_text(q, 90)
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(text)
    return out[:MAX_NEXT_QUESTIONS]


def _normalise(
    raw: dict,
    state: dict,
    audited: bool = True,
    pending: int | None = None,
    known_items: dict[str, str] | None = None,
    unverified: list[str] | None = None,
    asked: list[str] | None = None,
) -> dict:
    """Turn whatever the model returned into the response shape, falling back to the previous state.
    `audited` is whether features and analyses may be added yet (data loaded, audit decisions made)."""
    phase = raw.get("phase") if raw.get("phase") in PHASES else state.get("phase", "interview")
    intent = _intent_of(raw, phase)
    prev_u = state.get("understanding") if isinstance(state.get("understanding"), dict) else {}
    new_u = raw.get("understanding") if isinstance(raw.get("understanding"), dict) else {}
    understanding = {k: _clean_text(new_u.get(k, prev_u.get(k, "")), 400) for k in UNDERSTANDING_KEYS}

    assumptions = []
    seen: set[str] = set()
    for i, a in enumerate(raw.get("assumptions") or []):
        text = _clean_text(a.get("text") if isinstance(a, dict) else a, 300)
        if not text:
            continue
        aid = _clean_text(a.get("id"), 20) if isinstance(a, dict) else ""
        if not aid or aid in seen:
            aid = f"a{i + 1}"
        seen.add(aid)
        assumptions.append({"id": aid, "text": text})

    quick = [_clean_text(q, 80) for q in (raw.get("quick_replies") or []) if isinstance(q, str) and q.strip()][:4]
    cleaned = _clean_actions(raw.get("actions"), audited, intent, known_items)
    reply = _clean_text(raw.get("reply"), 3000) or "Sorry, I lost my train of thought. Could you say that again?"
    notes = []
    if cleaned.needs_audit:
        notes.append(_refusal_note(cleaned.needs_audit, pending))
    if cleaned.off_intent:
        notes.append(OFF_INTENT_NOTE)
    if unverified:
        notes.append(_unverified_note(unverified))
    if notes:
        reply = "\n\n".join([reply, *notes])
    return {
        "reply": reply,
        "intent": intent,
        "phase": phase,
        "understanding": understanding,
        "assumptions": assumptions,
        "quick_replies": quick,
        "next_questions": [] if intent == "interview" else _clean_questions(raw.get("next_questions"), asked or []),
        "actions": cleaned.actions,
    }


def _audit_status(req: ChatTurnRequest) -> tuple[bool, int | None]:
    """(audited, pending): whether features and analyses may be added now, and how many audit decisions are
    still open. The server counts the open decisions itself; the browser says whether the audit has run at all
    (a session with no issues looks reviewed before it is audited). Also checks the caller may use the session."""
    if not req.session_id:
        return False, None
    session = get_or_404(req.session_id)
    pending = sum(1 for i in session.issues if i.requires_decision and i.status == "pending")
    return bool(req.state.get("audit_reviewed")) and pending == 0, pending


def _user_prompt(req: ChatTurnRequest, audited: bool, pending: int | None) -> str:
    transcript = "\n".join(
        f'{"PM" if m.role == "user" else "ASSISTANT"}: {m.content.strip()}' for m in req.messages[-MAX_MESSAGES:]
    )
    state = dict(req.state)
    state["has_data"] = bool(req.session_id)
    state["audit_reviewed"] = audited
    state["pending_audit_decisions"] = pending
    return (
        f"CLIENT BRIEF (as the PM entered it):\n{req.brief.strip() or '(none yet)'}\n\n"
        f"STATE:\n{json.dumps(state, ensure_ascii=False, indent=1)}\n\n"
        f"DATA:\n{_data_block(req.session_id)}\n\n"
        f"CONVERSATION:\n{transcript or '(empty)'}\n\n"
        "---\nWrite the assistant's next turn now. Return exactly the JSON object described, no other text."
    )


def _ask_model(system_prompt: str, user_prompt: str) -> str:
    return llm.chat_json(
        system_prompt, user_prompt,
        model=model_for("chat_agent", llm.LLM_MODEL), temperature=0.4, call_name="chat_agent", max_tokens=2500,
    )


def _known_items(session_id: str | None) -> dict[str, str]:
    if not session_id:
        return {}
    try:
        return chat_tools.known_items(session_id)
    except Exception as exc:  # noqa: BLE001 - without it the reply simply cannot open a specific item
        log.warning("chat: could not list the items of %s: %s", session_id, exc)
        return {}


@router.post("/turn")
def turn(req: ChatTurnRequest):
    if not req.messages or req.messages[-1].role != "user":
        raise HTTPException(status_code=400, detail="The last message must be the PM's.")
    audited, pending = _audit_status(req)
    system = llm.system_prompt("chat_agent", _prompts.SYSTEM_PROMPT)
    if req.session_id:
        system += orchestrator.tools_prompt()  # tools only exist for a loaded session
    user = _user_prompt(req, audited, pending)
    ctx = chat_tools.ToolContext(req.session_id) if req.session_id else None
    try:
        result = orchestrator.run_turn(system, user, _ask_model, ctx)
        raw, unverified = orchestrator.ground(result, system, user, _ask_model)
    except (ValueError, llm.LLMError) as exc:
        log.warning("chat turn failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"The assistant could not answer: {exc}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Chat LLM error: {exc}") from exc
    asked = [m.content for m in req.messages if m.role == "user"]
    return _normalise(raw, req.state, audited, pending, _known_items(req.session_id), unverified, asked)


# --------------------------------------------------------------------------- interview record
class InterviewIn(BaseModel):
    brief: str = ""
    # Where `brief` came from: "chat" (the PM gave it in the chat: the Planner uses it) or "upload" (the Configure page).
    brief_source: str = ""
    understanding: dict[str, str] = Field(default_factory=dict)
    assumptions: list[dict[str, str]] = Field(default_factory=list)
    transcript: list[ChatMessage] = Field(default_factory=list)


@router.put("/interview/{session_id}")
def save_interview(session_id: str, body: InterviewIn):
    session = get_or_404(session_id)
    record = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "brief": body.brief,
        "brief_source": body.brief_source if body.brief_source in ("chat", "upload") else "",
        "understanding": {k: _clean_text(v, 400) for k, v in body.understanding.items() if k in UNDERSTANDING_KEYS},
        "assumptions": [{"id": a.get("id", ""), "text": _clean_text(a.get("text"), 300)} for a in body.assumptions],
        "transcript": [m.model_dump() for m in body.transcript[-60:]],
    }
    doc_store.put(session_id, INTERVIEW_DOC, record)
    audit_log.log_event(
        session_id, session.user_id, "interview_saved",
        {"assumptions": len(record["assumptions"])},
    )
    return {"session_id": session_id, "saved": True}


@router.get("/interview/{session_id}")
def get_interview(session_id: str):
    get_or_404(session_id)
    return doc_store.get(session_id, INTERVIEW_DOC) or {}
