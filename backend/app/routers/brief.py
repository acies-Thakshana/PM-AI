from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.audit.audit_store import get_or_404
from app.services.common import audit_log, doc_store

router = APIRouter(prefix="/api/brief", tags=["brief"])


class FileMetadataIn(BaseModel):
    slot: str
    filename: str
    size: int
    mime_type: str


class FinalizeRequest(BaseModel):
    audit_session_ids: list[str]
    raw_brief: str
    final_brief: str
    original_language: str | None = None
    original_language_name: str | None = None
    translated_text: str | None = None
    files: list[FileMetadataIn]


class FinalizeResponse(BaseModel):
    session_id: str


@router.post("/finalize", response_model=FinalizeResponse)
def finalize(req: FinalizeRequest):
    """Merge brief + all uploaded datasets into one BRIEF document.

    Uses the first audit session as the canonical session, so there is exactly one
    BRIEF document per run.
    """
    if not req.audit_session_ids:
        raise HTTPException(status_code=400, detail="At least one audit_session_id is required.")
    sessions = [get_or_404(sid) for sid in req.audit_session_ids]

    primary_sid = req.audit_session_ids[0]

    # Two texts are kept: what the client wrote, and the text the Planner reads (the English
    # translation when the brief was translated, else the text as the PM confirmed it). The
    # language fields the page sends are accepted but not stored.
    metadata = {
        "session_id": primary_sid,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "client_brief": {
            "raw_text": req.raw_brief,
            "understanding_text": (req.translated_text or req.final_brief or req.raw_brief or "").strip(),
        },
        "files": [f.model_dump() for f in req.files],
    }

    doc_store.put(primary_sid, "BRIEF", metadata)
    audit_log.log_event(
        primary_sid, sessions[0].user_id, "brief_finalize",
        {"audit_session_ids": req.audit_session_ids, "files": [f.filename for f in req.files]},
    )

    return FinalizeResponse(session_id=primary_sid)
