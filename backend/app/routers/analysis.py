import json

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.schemas import (
    ApplyPivotsRequest,
    OverallAnalysisReport,
    PivotDefinitionsSummary,
    PivotReport,
    SuggestPivotsRequest,
    SuggestPivotsResponse,
)
from app.services import overall_analysis, overall_analysis_agent, pivot_engine, pivot_suggester, report_generator
from app.services import pivot_definitions_store as pivot_defs_store
from app.services.audit_store import AuditSession, store

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def _get_session_or_404(session_id: str) -> AuditSession:
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")
    return session


def _to_pivot_report(session: AuditSession) -> PivotReport:
    return PivotReport(
        session_id=session.session_id,
        row_count=len(session.df),
        column_count=len(session.df.columns),
        columns=[str(c) for c in session.df.columns],
        pivots=session.pivots,
        skipped_notes=session.pivot_skipped_notes,
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
    extra_pivots = body.extra_pivots if body else []
    pivot_filters = body.pivot_filters if body else {}
    combined_defs = list(pivot_defs_store.store.definitions) + extra_pivots

    results, skipped_notes = pivot_engine.apply_pivots(session.df, combined_defs, pivot_filters=pivot_filters)
    session.pivots = results
    session.pivot_skipped_notes = skipped_notes
    return _to_pivot_report(session)


@router.get("/{session_id}/pivots", response_model=PivotReport)
def get_pivots(session_id: str) -> PivotReport:
    return _to_pivot_report(_get_session_or_404(session_id))


@router.get("/{session_id}/overall", response_model=OverallAnalysisReport)
def get_overall_analysis(session_id: str) -> OverallAnalysisReport:
    session = _get_session_or_404(session_id)
    highlights = overall_analysis.build_highlights(len(session.df), session.features, session.pivots)
    try:
        narrative = overall_analysis_agent.generate_narrative(len(session.df), highlights)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Overall analysis narrative agent (Groq) is unavailable: {exc}"
        ) from exc
    report = OverallAnalysisReport(
        session_id=session_id, row_count=len(session.df), highlights=highlights, narrative=narrative
    )
    session.overall_analysis = report
    return report


@router.get("/{session_id}/report")
def download_report(session_id: str):
    """Streams a .pptx built from whatever pivots are CURRENTLY computed for
    this session (with whatever slicer filters are active) and the
    last-generated overall analysis -- every chart is native, built fresh
    from that data, never a picture."""
    session = _get_session_or_404(session_id)
    if not session.pivots:
        raise HTTPException(
            status_code=422,
            detail="No pivot tables have been computed yet -- run the Analysis step before downloading a report.",
        )

    pptx_bytes = report_generator.build_report(
        source_label=session.filename, df=session.df, pivots=session.pivots, overall=session.overall_analysis
    )

    stem = session.filename.rsplit(".", 1)[0] if "." in session.filename else session.filename
    filename = f"{stem}_report.pptx"
    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
