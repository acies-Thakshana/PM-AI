"""The chat assistant: interviews the PM about the client brief, then refines the report by conversation.

`POST /api/chat/turn` is one stateless turn: the browser sends the transcript, the brief and the chat's
current state; the model answers with the next reply, the updated understanding, assumptions, quick
replies, an optional plan and a few actions the app carries out (open a page, add an analysis ...).
Nothing here changes the data: the browser performs the actions through the normal endpoints.

`PUT /api/chat/interview/{session_id}` stores the interview that led to the plan (answers, assumptions,
the approved plan) next to the session's brief, so anyone can later see why things were built; the
Planner reads it (see planner.py) so the approved plan is what gets planned.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import model_for
from app.prompts import chat_agent as _prompts
from app.routers.job_route import JobRoute
from app.services.analysis import analysis_repository
from app.services.audit.audit_store import get_or_404
from app.services.common import audit_log, column_meta, doc_store, llm
from app.services.features import feature_repository
from app.services.planner.planner import _build_columns_block

log = logging.getLogger(__name__)

router = APIRouter(route_class=JobRoute, prefix="/api/chat", tags=["chat"])

INTERVIEW_DOC = "INTERVIEW"

PHASES = ("interview", "readback", "plan", "build", "refine")
PAGES = ("upload", "audit", "features", "analysis", "report")
ACTION_TYPES = (
    "set_brief", "approve_plan", "navigate", "add_analysis", "add_feature", "explain", "check_ready", "continue_build",
)
UNDERSTANDING_KEYS = ("goal", "scope", "period", "limits", "output", "kpis")

MAX_MESSAGES = 24
MAX_COLUMNS_IN_PROMPT = 60


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatTurnRequest(BaseModel):
    session_id: str | None = None
    brief: str = ""
    messages: list[ChatMessage] = Field(default_factory=list)
    # The chat's own state (phase, understanding, assumptions, plan, page, build status ...).
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
            for e in analysis_repository.get_repository(session_id)
            if e.get("source") != "drilldown"
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


def _clean_plan(plan: Any) -> dict | None:
    if not isinstance(plan, dict):
        return None
    out: dict[str, list[dict[str, str]]] = {}
    for key in ("analyses", "features"):
        items = []
        for it in (plan.get(key) or [])[:6]:
            if isinstance(it, dict) and _clean_text(it.get("name"), 120):
                items.append({"name": _clean_text(it.get("name"), 120), "description": _clean_text(it.get("description"))})
        out[key] = items
    return out if out["analyses"] or out["features"] else None


def _clean_actions(actions: Any) -> list[dict]:
    cleaned: list[dict] = []
    for a in (actions or [])[:3]:
        if not isinstance(a, dict) or a.get("type") not in ACTION_TYPES:
            continue
        kind = a["type"]
        if kind == "navigate":
            if a.get("page") in PAGES:
                cleaned.append({"type": kind, "page": a["page"]})
        elif kind in ("add_analysis", "add_feature"):
            name, desc = _clean_text(a.get("name"), 120), _clean_text(a.get("description"))
            if name and desc:
                cleaned.append({"type": kind, "name": name, "description": desc})
        elif kind == "set_brief":
            text = _clean_text(a.get("text"), 8000)
            if text:
                cleaned.append({"type": kind, "text": text})
        elif kind == "explain":
            cleaned.append({"type": kind, "target": _clean_text(a.get("target"), 200)})
        else:
            cleaned.append({"type": kind})
    return cleaned


def _normalise(raw: dict, state: dict) -> dict:
    """Turn whatever the model returned into the response shape, falling back to the previous state."""
    phase = raw.get("phase") if raw.get("phase") in PHASES else state.get("phase", "interview")
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
    plan = _clean_plan(raw.get("plan"))
    if phase == "plan" and plan is None:
        plan = _clean_plan(state.get("plan"))
    return {
        "reply": _clean_text(raw.get("reply"), 3000) or "Sorry, I lost my train of thought. Could you say that again?",
        "phase": phase,
        "understanding": understanding,
        "assumptions": assumptions,
        "quick_replies": quick,
        "plan": plan,
        "actions": _clean_actions(raw.get("actions")),
    }


def _user_prompt(req: ChatTurnRequest) -> str:
    transcript = "\n".join(
        f'{"PM" if m.role == "user" else "ASSISTANT"}: {m.content.strip()}' for m in req.messages[-MAX_MESSAGES:]
    )
    state = dict(req.state)
    state["has_data"] = bool(req.session_id)
    return (
        f"CLIENT BRIEF (as the PM entered it):\n{req.brief.strip() or '(none yet)'}\n\n"
        f"STATE:\n{json.dumps(state, ensure_ascii=False, indent=1)}\n\n"
        f"DATA:\n{_data_block(req.session_id)}\n\n"
        f"CONVERSATION:\n{transcript or '(empty)'}\n\n"
        "---\nWrite the assistant's next turn now. Return exactly the JSON object described, no other text."
    )


@router.post("/turn")
def turn(req: ChatTurnRequest):
    if not req.messages or req.messages[-1].role != "user":
        raise HTTPException(status_code=400, detail="The last message must be the PM's.")
    if req.session_id:
        get_or_404(req.session_id)  # also checks the caller may use this session
    try:
        raw_text = llm.chat_json(
            llm.system_prompt("chat_agent", _prompts.SYSTEM_PROMPT), _user_prompt(req),
            model=model_for("chat_agent", llm.LLM_MODEL), temperature=0.4, call_name="chat_agent", max_tokens=2500,
        )
        raw = json.loads(raw_text)
        if not isinstance(raw, dict):
            raise ValueError("the model did not return an object")
    except (ValueError, llm.LLMError) as exc:
        log.warning("chat turn failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"The assistant could not answer: {exc}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Chat LLM error: {exc}") from exc
    return _normalise(raw, req.state)


# --------------------------------------------------------------------------- interview record
class InterviewIn(BaseModel):
    brief: str = ""
    understanding: dict[str, str] = Field(default_factory=dict)
    assumptions: list[dict[str, str]] = Field(default_factory=list)
    plan: dict[str, Any] | None = None
    transcript: list[ChatMessage] = Field(default_factory=list)


@router.put("/interview/{session_id}")
def save_interview(session_id: str, body: InterviewIn):
    session = get_or_404(session_id)
    record = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "brief": body.brief,
        "understanding": {k: _clean_text(v, 400) for k, v in body.understanding.items() if k in UNDERSTANDING_KEYS},
        "assumptions": [{"id": a.get("id", ""), "text": _clean_text(a.get("text"), 300)} for a in body.assumptions],
        "plan": _clean_plan(body.plan),
        "transcript": [m.model_dump() for m in body.transcript[-60:]],
    }
    doc_store.put(session_id, INTERVIEW_DOC, record)
    audit_log.log_event(
        session_id, session.user_id, "interview_saved",
        {"assumptions": len(record["assumptions"]), "plan": {k: len(v) for k, v in (record["plan"] or {}).items()}},
    )
    return {"session_id": session_id, "saved": True}


@router.get("/interview/{session_id}")
def get_interview(session_id: str):
    get_or_404(session_id)
    return doc_store.get(session_id, INTERVIEW_DOC) or {}
