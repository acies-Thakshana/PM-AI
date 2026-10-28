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
import re
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
from app.services.chat.turn_recorder import TurnRecorder
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
    # Made by the browser: the conversation and this turn in it. Without them the turn is simply not recorded.
    chat_id: str | None = None
    turn_id: str | None = None
    # The last message is the app's own prompt (it starts the interview), not something the PM typed.
    hidden: bool = False


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
        # The id of each item is in square brackets: the model needs it to point the PM at the item (navigate "open").
        analyses = [
            f'- [{e["id"]}] {e["name"]} ({e["status"]}, run={e.get("run_status", "not_run")})'
            for e in chat_tools.analyses_of(session_id)
        ]
        feats = [f'- [{e["id"]}] {e["name"]} ({e["status"]})' for e in feature_repository.get_repository(session_id)]
        parts.append("EXISTING ANALYSES ([id] name):\n" + ("\n".join(analyses) or "(none)"))
        parts.append("EXISTING FEATURES ([id] name):\n" + ("\n".join(feats) or "(none)"))
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


PAGE_OF_KIND = {kind: page for page, kind in OPENABLE_KIND.items()}


def _open_what_was_read(actions: list[dict], looked_at: list[tuple[str, str]]) -> list[dict]:
    """The model is asked to point its navigate action at the item it explains, but it often leaves the id out (or
    writes a wrong one that gets dropped), and then only the page opens. The server knows which item it read: when
    exactly one item was read, that page's navigate action opens it (and one is added when the model sent none).
    When SEVERAL items were read (the PM asked about an analysis and a calculation together) there is no single item
    to show, so the answer stays text only: the navigate actions to the Analysis and Features pages are dropped."""
    items = set(looked_at)
    if len(items) > 1:
        return [a for a in actions if not (a.get("type") == "navigate" and a.get("page") in OPENABLE_KIND)]
    if len(items) != 1:
        return actions
    kind, item_id = next(iter(items))
    page = PAGE_OF_KIND[kind]
    if any(a.get("type") == "navigate" and a.get("page") not in OPENABLE_KIND for a in actions):
        return actions  # the model is taking the PM to another page (audit, report ...) on purpose
    if not any(a.get("type") == "navigate" for a in actions):
        actions = [*actions, {"type": "navigate", "page": page}]
    # A navigate to the wrong one of the two item pages (an analysis question sent to Features) points at the item's page.
    return [{**a, "page": page, "open": item_id} if a.get("type") == "navigate" and not a.get("open") else a for a in actions]


def _named_item(question: str, session_id: str | None) -> tuple[str, str, str] | None:
    """(tool, id, name) of the one analysis or calculation the PM's message names in full, or None."""
    if not session_id:
        return None
    try:
        items = [("get_analysis", e["id"], e["name"]) for e in chat_tools.analyses_of(session_id)]
        items += [("get_feature", e["id"], e["name"]) for e in chat_tools._features(session_id)]
    except Exception as exc:  # noqa: BLE001 - without the hint the model simply looks the item up itself
        log.warning("chat: could not list the items of %s: %s", session_id, exc)
        return None
    scored = sorted(((chat_tools.name_overlap(question, n), t, i, n) for t, i, n in items), reverse=True)
    if scored and scored[0][0] >= 0.99 and (len(scored) == 1 or scored[1][0] < scored[0][0]):
        return scored[0][1:]
    return None


def _open_what_was_named(actions: list[dict], question: str, session_id: str | None) -> list[dict]:
    """The model sometimes opens the Analysis or Features page without reading anything and without an item id, so the
    page opens but not the analysis the PM asked about. When the PM's message names exactly one item of that page
    ("explain the monthly compliance trend"), that item is the one to open."""
    if not session_id or not any(a.get("type") == "navigate" and not a.get("open") and a.get("page") in OPENABLE_KIND for a in actions):
        return actions
    try:
        names = {"analysis": [(e["id"], e["name"]) for e in chat_tools.analyses_of(session_id)],
                 "feature": [(e["id"], e["name"]) for e in chat_tools._features(session_id)]}
    except Exception as exc:  # noqa: BLE001 - the page still opens, just without the item
        log.warning("chat: could not list the items of %s: %s", session_id, exc)
        return actions
    out = []
    for a in actions:
        if a.get("type") == "navigate" and not a.get("open") and a.get("page") in OPENABLE_KIND:
            scored = sorted(((chat_tools.name_overlap(question, n), i) for i, n in names[OPENABLE_KIND[a["page"]]]), reverse=True)
            if scored and scored[0][0] >= 0.99 and (len(scored) == 1 or scored[1][0] < scored[0][0]):
                a = {**a, "open": scored[0][1]}
        out.append(a)
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

# ---- the parts of a reply the app writes itself, so the format and the "what next" line never depend on the model
UNDERSTANDING_LABELS = (("goal", "Goal"), ("scope", "Scope"), ("period", "Period"),
                        ("limits", "Limits"), ("output", "Output"), ("kpis", "Client KPIs"))
READBACK_REPLIES = ["Yes, that's right", "Not quite"]
READBACK_CLOSING = 'Reply "yes" to confirm, or tell me what to change.'
READY_CLOSING = 'Next step: accept or reject the Planner\'s suggestions, then press "Build the report".'


def _plain(text: str) -> str:
    """Plain text for the chat bubble, which shows what it is given: no **bold** marks, bullets as one bullet kind."""
    return re.sub(r"(?m)^[ \t]*[*\-][ \t]+", "• ", re.sub(r"\*\*|__", "", text))


def _readback_reply(understanding: dict[str, str], assumptions: list[dict]) -> str:
    """The read-back message: always the same six rows in the same order (a blank one says so), then what to do."""
    rows = [f"• {label}: {understanding.get(key) or 'Not specified'}" for key, label in UNDERSTANDING_LABELS]
    parts = ["Here is what I understood from the brief:\n" + "\n".join(rows)]
    if assumptions:
        n = len(assumptions)
        parts.append(f"I made {n} assumption{'s' if n > 1 else ''} where the brief was silent (listed above the chat; you can edit or remove them).")
    parts.append(READBACK_CLOSING)
    return "\n\n".join(parts)


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
    looked_at: list[tuple[str, str]] | None = None,
<<<<<<< HEAD
    refusals: dict[str, list[str]] | None = None,
=======
    has_data: bool = False,
>>>>>>> 32331cdd49732ec5483084630446f026cccb7219
) -> dict:
    """Turn whatever the model returned into the response shape, falling back to the previous state.
    `audited` is whether features and analyses may be added yet (data loaded, audit decisions made).
    When `refusals` is given it is filled with the action types that were dropped and why ("needs_audit",
    "off_intent"), for the record of the turn."""
    phase = raw.get("phase") if raw.get("phase") in PHASES else state.get("phase", "interview")
    intent = _intent_of(raw, phase)
    prev_u = state.get("understanding") if isinstance(state.get("understanding"), dict) else {}
    new_u = raw.get("understanding") if isinstance(raw.get("understanding"), dict) else {}
    understanding = {k: _plain(_clean_text(new_u.get(k, prev_u.get(k, "")), 400)) for k in UNDERSTANDING_KEYS}

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
    # Reading an item is only done to answer a question: a model that labelled the turn as an interview answer still opens it.
    if intent in ("ask", "other", "interview") and looked_at:
        cleaned.actions = _open_what_was_read(cleaned.actions, looked_at)
    reply = _plain(_clean_text(raw.get("reply"), 3000)) or "Sorry, I lost my train of thought. Could you say that again?"
    # The interview steps look the same every time: the read-back is written here from the structured answers, and
    # a confirmed interview always ends with what to do next (the model's own wording of these varied from turn to turn).
    if intent == "interview" and phase == "readback":
        reply = _readback_reply(understanding, assumptions)
        quick = list(READBACK_REPLIES)
    elif intent == "interview" and phase == "ready" and has_data and "Build the report" not in reply:
        reply = f"{reply}\n\n{READY_CLOSING}"
    notes = []
    if cleaned.needs_audit:
        notes.append(_refusal_note(cleaned.needs_audit, pending))
    if cleaned.off_intent:
        notes.append(OFF_INTENT_NOTE)
    if unverified:
        notes.append(_unverified_note(unverified))
    if notes:
        reply = "\n\n".join([reply, *notes])
    if refusals is not None:
        refusals["needs_audit"] = list(cleaned.needs_audit)
        refusals["off_intent"] = list(cleaned.off_intent)
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
    recorder = TurnRecorder.begin(
        chat_id=req.chat_id, turn_id=req.turn_id, user_text=req.messages[-1].content,
        session_id=req.session_id, state=req.state, hidden=req.hidden,
    )
    try:
        return _answer(req, audited, pending, recorder)
    finally:
        recorder.close()


def _answer(req: ChatTurnRequest, audited: bool, pending: int | None, recorder: TurnRecorder) -> dict:
    """The model's answer to the PM's last message, cleaned (see `turn`); the turn is recorded as it goes."""
    system = llm.system_prompt("chat_agent", _prompts.SYSTEM_PROMPT)
    if req.session_id:
        system += orchestrator.tools_prompt()  # tools only exist for a loaded session
    user = _user_prompt(req, audited, pending)
    named = _named_item(req.messages[-1].content, req.session_id)
    if named:
        # The model otherwise tends to say "I'll open the page" and leave the explaining for the next message.
        tool, item_id, name = named
        user += (
            f"\n\nNOTE: the PM's last message is about \"{name}\" (id {item_id}). If it asks about it, call {tool} with "
            f"id \"{item_id}\" first and explain it in this same answer, in the order given above."
        )
    ctx = chat_tools.ToolContext(req.session_id) if req.session_id else None
    try:
        result = orchestrator.run_turn(system, user, _ask_model, ctx)
        raw, unverified = orchestrator.ground(result, system, user, _ask_model)
    except (ValueError, llm.LLMError) as exc:
        log.warning("chat turn failed: %s", exc)
        recorder.fail("LLM_ERROR", 502, str(exc))
        raise HTTPException(status_code=502, detail=f"The assistant could not answer: {exc}") from exc
    except RuntimeError as exc:
        recorder.fail("UNAVAILABLE", 503, str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        recorder.fail("CHAT_ERROR", 502, str(exc))
        raise HTTPException(status_code=502, detail=f"Chat LLM error: {exc}") from exc
    asked = [m.content for m in req.messages if m.role == "user"]
<<<<<<< HEAD
    refusals: dict[str, list[str]] = {}
    response = _normalise(
        raw, req.state, audited, pending, _known_items(req.session_id), unverified, asked, result.looked_at, refusals,
    )
=======
    response = _normalise(raw, req.state, audited, pending, _known_items(req.session_id), unverified, asked, result.looked_at, bool(req.session_id))
>>>>>>> 32331cdd49732ec5483084630446f026cccb7219
    response["actions"] = _open_what_was_named(response["actions"], asked[-1] if asked else "", req.session_id)
    recorder.complete(
        response, tools_used=result.tools_used, looked_at=result.looked_at, refusals=refusals, state=req.state,
    )
    return response


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
