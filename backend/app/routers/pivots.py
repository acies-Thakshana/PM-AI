import json

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.schemas import (
    ApplyPivotsRequest,
    PivotDefinitionsSummary,
    PivotReport,
    SuggestPivotsRequest,
    SuggestPivotsResponse,
)
from app.services import pivot_engine, pivot_suggester
from app.services import pivot_definitions_store as pivot_defs_store
from app.services.audit_store import AuditSession
from app.routers._common import get_session_or_404 as _get_session_or_404

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def _to_pivot_report(session: AuditSession) -> PivotReport:
    return PivotReport(
        session_id=session.session_id,
        row_count=len(session.df),
        column_count=len(session.df.columns),
        columns=[str(c) for c in session.df.columns],
        pivots=session.pivots,
        skipped_notes=session.pivot_skipped_notes,
        pivot_filters=session.pivot_filter_state,
    )


@router.post("/definitions", response_model=PivotDefinitionsSummary)
async def upload_pivot_definitions(file: UploadFile = File(...)) -> PivotDefinitionsSummary:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Not valid JSON: {exc}") from exc

    try:
        pivots = pivot_defs_store.validate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    filename = file.filename or "analysis_profile.json"
    pivot_defs_store.store.set(filename, pivots)

    return PivotDefinitionsSummary(
        filename=filename,
        pivot_count=len(pivots),
        pivot_names=[p["name"] for p in pivots],
    )


@router.get("/definitions", response_model=PivotDefinitionsSummary)
def get_pivot_definitions() -> PivotDefinitionsSummary:
    if pivot_defs_store.store.definitions is None:
        raise HTTPException(status_code=404, detail="No Analysis Profile has been uploaded yet.")
    return PivotDefinitionsSummary(
        filename=pivot_defs_store.store.filename,
        pivot_count=len(pivot_defs_store.store.definitions),
        pivot_names=[p["name"] for p in pivot_defs_store.store.definitions],
    )


@router.post("/suggest", response_model=SuggestPivotsResponse)
def suggest_pivots(body: SuggestPivotsRequest) -> SuggestPivotsResponse:
    session = _get_session_or_404(body.session_id)
    try:
        suggestions = pivot_suggester.suggest_pivots(session.df)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Pivot suggestion agent (Groq) is unavailable: {exc}") from exc
    return SuggestPivotsResponse(session_id=body.session_id, suggestions=suggestions)


@router.post("/{session_id}/pivots", response_model=PivotReport)
def apply_pivots(session_id: str, body: ApplyPivotsRequest | None = None) -> PivotReport:
    session = _get_session_or_404(session_id)
    if pivot_defs_store.store.definitions is None:
        raise HTTPException(
            status_code=422,
            detail="No Analysis Profile has been uploaded yet -- upload one (with your pivot table "
                   "definitions) before analysis can run. There is no default.",
        )
    # `extra_pivots` omitted (None) means "leave the AI/custom pivots already
    # applied for this session alone" -- a caller that only wants to change
    # slicer filters (e.g. the Report page) doesn't have to resend the
    # Analysis page's full accepted list to avoid dropping them.
    if body is not None and body.extra_pivots is not None:
        session.extra_pivot_defs = body.extra_pivots
    extra_pivots = session.extra_pivot_defs

    # `pivot_filters` is merged per-pivot-id, not replaced wholesale -- a
    # caller touching one pivot's filters (or adding a shared filter across
    # several) shouldn't blow away filters already saved for pivots it
    # didn't mention. Callers that DO want to clear a pivot's filters must
    # send it explicitly with an empty list, not omit the key.
    if body is not None and body.pivot_filters:
        session.pivot_filter_state = {**session.pivot_filter_state, **body.pivot_filters}
    pivot_filters = session.pivot_filter_state

    combined_defs = list(pivot_defs_store.store.definitions) + extra_pivots

    results, skipped_notes = pivot_engine.apply_pivots(session.df, combined_defs, pivot_filters=pivot_filters)
    session.pivots = results
    session.pivot_skipped_notes = skipped_notes
    return _to_pivot_report(session)


@router.get("/{session_id}/pivots", response_model=PivotReport)
def get_pivots(session_id: str) -> PivotReport:
    return _to_pivot_report(_get_session_or_404(session_id))
