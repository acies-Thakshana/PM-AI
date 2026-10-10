from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.analysis import analysis_repository
from app.services.audit.audit_store import get_or_404
from app.services.common import audit_log
from app.services.features import feature_repository
from app.services.planner import planner as planner_service, planner_store

router = APIRouter(prefix="/api/planner", tags=["planner"])


class SuggestRequest(BaseModel):
    session_id: str
    additional_context: str = ""


class PmDecision(BaseModel):
    recommendation_index: int
    pm_decision: str  # "accepted" | "rejected" | "pending"
    pm_notes: str = ""


class SaveRequest(BaseModel):
    session_id: str
    decisions: list[PmDecision]


class SaveResponse(BaseModel):
    session_id: str
    saved: bool


@router.post("/suggest")
def suggest(req: SuggestRequest):
    session = get_or_404(req.session_id)
    try:
        result = planner_service.suggest(req.session_id, req.additional_context)
        recs = result.get("recommendations", [])
        by_type: dict[str, int] = {}
        for rec in recs:
            by_type[rec.get("type", "other")] = by_type.get(rec.get("type", "other"), 0) + 1
        audit_log.log_event(
            req.session_id, session.user_id, "planner_suggest",
            {
                # a request typed into the "more suggestions" box appends to the list
                "more": bool(req.additional_context.strip()),
                "request": req.additional_context.strip()[:500],
                "count": len(recs),
                "by_type": by_type,
                "names": [r.get("name") for r in recs],
            },
        )
        return result
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Planner LLM error: {exc}") from exc


@router.post("/save", response_model=SaveResponse)
def save_decisions(req: SaveRequest):
    session = get_or_404(req.session_id)
    if not planner_store.load(req.session_id):
        raise HTTPException(
            status_code=404,
            detail="No planner suggestions found for this session. Call /suggest first.",
        )

    # The decision lands on the recommendation's own PLAN#<n> document.
    planner_store.apply_decisions(
        req.session_id, {d.recommendation_index: (d.pm_decision, d.pm_notes) for d in req.decisions}
    )
    try:  # keep the FEATURES / ANALYSES documents' planner snapshots current (not critical)
        feature_repository.sync(req.session_id)
        analysis_repository.sync(req.session_id)
    except Exception as exc:  # noqa: BLE001
        audit_log.log.warning("could not refresh planner snapshots: %s", exc)
    audit_log.log_event(
        req.session_id, session.user_id, "planner_save",
        {"decisions": [d.model_dump() for d in req.decisions]},
    )

    return SaveResponse(session_id=req.session_id, saved=True)
