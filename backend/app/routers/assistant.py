"""The chat assistant at the bottom of every stage.

It answers questions about the program in front of the PM (the client brief, the audit findings, the plan the
PM accepted). It only talks: it never changes data. Buttons in the stage do the work.
"""
import json
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.routers.job_route import JobRoute
from app.services.audit.audit_store import get_or_404
from app.services.common import audit_log, doc_store, llm
from app.services.planner import planner_store

log = logging.getLogger(__name__)

router = APIRouter(route_class=JobRoute, prefix="/api/assistant", tags=["assistant"])

Stage = Literal["audit", "features", "analysis", "report"]

_MAX_HISTORY = 8
_MAX_ITEMS = 25

_SYSTEM = """You are the assistant inside Program Manager AI, a tool a program manager uses to turn cold-chain \
shipment data into audited data, features, analyses and a report.

Answer the program manager's question using ONLY the program context below. Rules:
- If the context does not contain the answer, say so plainly and say where in the app they can look. Do not guess \
at causes: explain only what the context shows.
- "Flagged trips" are the ones listed in the OUTLIER CHECK section (segment days compared with the trip's lane, and \
mean temperature compared with the product's other trips). The AUDIT section lists the standard checks, which may \
not have run yet.
- Never invent numbers, trips, lanes or findings.
- You cannot change anything. When something needs doing, name the button or step in the app that does it.
- Be brief: two to five short sentences, plain text, no markdown headings.
- Use plain language a program manager would use. Never quote section names (such as OUTLIER CHECK) or field names (such as too_warm); say "too warm for its product" instead.
- The current stage tells you what they are looking at: {stage_hint}"""

_STAGE_HINTS = {
    "audit": "the data audit. They are reviewing flagged trips, empty columns and outliers and deciding what to do with each.",
    "features": "feature building. They are computing columns (such as time above a limit) from the audited data.",
    "analysis": "the analyses. They are running the planned analyses, filtering results and drilling down.",
    "report": "the report. They are choosing what goes into the PowerPoint and editing the key messages.",
}


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=4000)


class AskRequest(BaseModel):
    session_id: str
    stage: Stage
    message: str = Field(min_length=1, max_length=2000)
    history: list[Turn] = Field(default_factory=list)


class AskResponse(BaseModel):
    reply: str


def _brief_text(session_id: str) -> str:
    doc = doc_store.get(session_id, "BRIEF") or {}
    block = doc.get("client_brief", {})
    return (
        block.get("understanding_text") or block.get("translated_text") or block.get("final_text") or block.get("raw_text") or ""
    ).strip()


def _audit_block(session) -> str:
    lines = [f"Data: {len(session.df)} rows, {len(session.df.columns)} columns. Source: {session.source}."]
    if not session.issues:
        lines.append("The standard audit checks have not produced any issues yet (they may not have been run).")
    if session.summary:
        lines.append(f"Audit summary: {session.summary}")
    for issue in session.issues[:_MAX_ITEMS]:
        state = "resolved" + (f" ({issue.resolution})" if issue.resolution else "") if issue.status == "resolved" else "pending"
        advice = f" Suggested: {issue.recommendation or issue.recommended_action}." if (issue.recommendation or issue.recommended_action) else ""
        lines.append(
            f"- [{issue.severity}] {issue.title}: {issue.description} Affects {issue.affected_row_count} rows. Status: {state}.{advice}"
        )
    return "\n".join(lines)


def _outlier_block(session) -> str:
    """The outlier check (the first step of the audit), as short text."""
    try:
        from app.services.audit.outlier_detectors import detect_segment_outliers, detect_temperature_outliers

        segment = detect_segment_outliers(session.df)
        temperature = detect_temperature_outliers(session.df)
    except Exception as exc:  # noqa: BLE001 - the assistant still answers without it
        log.warning("assistant: outlier check unavailable: %s", exc)
        return "Not available."
    rows = segment.get("outlier_rows") or []
    trimmed = {
        "segment_days": {
            "trips_checked": segment.get("total_trips"),
            "flagged_trips": segment.get("flagged_trips"),
            "flagged_rows": rows[:8],
        },
        "temperature": {
            "trips_checked": temperature.get("total_trips"),
            "too_warm": temperature.get("too_warm_count"),
            "too_cold": temperature.get("too_cold_count"),
            "by_product": (temperature.get("by_product") or [])[:6],
        },
    }
    return json.dumps(trimmed, default=str)[:3500]


def _plan_block(session_id: str) -> str:
    recs = planner_store.load(session_id)
    if not recs:
        return "No plan yet."
    lines = []
    for rec in recs[:_MAX_ITEMS]:
        decision = rec.get("pm_decision") or "pending"
        lines.append(f"- {rec.get('type', '?')}: {rec.get('name', '?')} ({decision}). {rec.get('reason') or rec.get('description') or ''}".strip())
    return "\n".join(lines)


@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    session = get_or_404(req.session_id)
    context = (
        f"CLIENT BRIEF:\n{_brief_text(req.session_id) or 'None given.'}\n\n"
        f"OUTLIER CHECK:\n{_outlier_block(session)}\n\n"
        f"AUDIT:\n{_audit_block(session)}\n\n"
        f"PLAN (the PM's accept / reject decisions):\n{_plan_block(req.session_id)}"
    )
    history = "\n".join(
        f"{'PM' if t.role == 'user' else 'Assistant'}: {t.text}" for t in req.history[-_MAX_HISTORY:]
    )
    prompt = f"PROGRAM CONTEXT:\n{context}\n\n" + (f"CONVERSATION SO FAR:\n{history}\n\n" if history else "") + f"PM: {req.message}"
    try:
        reply = llm.chat_text(
            _SYSTEM.format(stage_hint=_STAGE_HINTS[req.stage]), prompt, temperature=0.2, call_name="stage_assistant", max_tokens=700
        )
    except Exception as exc:  # noqa: BLE001 - the LLM client raises its own error types
        raise HTTPException(status_code=502, detail=f"The assistant could not answer: {exc}") from exc
    audit_log.log_event(req.session_id, session.user_id, "assistant_ask", {"stage": req.stage, "question": req.message[:500]})
    return AskResponse(reply=(reply or "").strip() or "I could not find an answer in this program's data.")
