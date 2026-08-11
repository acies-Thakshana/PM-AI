import json
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.schemas import (
    ApplyPivotsRequest,
    CreateReportSlideRequest,
    OverallAnalysisReport,
    PivotDefinitionsSummary,
    PivotReport,
    ReportSlide,
    ReportSlidesResponse,
    SuggestPivotsRequest,
    SuggestPivotsResponse,
    UpdateReportSlideRequest,
)
from app.services import overall_analysis, overall_analysis_agent, pivot_engine, pivot_suggester, report_generator, report_slides
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
        pivot_filters=session.pivot_filter_state,
    )


def _get_slide_or_404(session: AuditSession, slide_id: str) -> ReportSlide:
    slide = next((s for s in session.report_slides if s.id == slide_id), None)
    if not slide:
        raise HTTPException(status_code=404, detail="Report slide not found.")
    return slide


def _synced_slides_response(session: AuditSession) -> ReportSlidesResponse:
    session.report_slides = report_slides.sync_slides(session.pivots, session.report_slides, session.pivot_filter_state)
    return ReportSlidesResponse(session_id=session.session_id, slides=session.report_slides)


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


@router.get("/{session_id}/slides", response_model=ReportSlidesResponse)
def list_report_slides(session_id: str) -> ReportSlidesResponse:
    """Report-time only -- auto-seeds one slide per current pivot the first
    time this is called for a session, and never touches session.pivots."""
    return _synced_slides_response(_get_session_or_404(session_id))


@router.post("/{session_id}/slides", response_model=ReportSlidesResponse)
def create_report_slide(session_id: str, body: CreateReportSlideRequest) -> ReportSlidesResponse:
    """Adds a slide -- used for the "+" duplicate-with-a-different-filter
    action. `parent_id` should be the TOP-LEVEL slide id for this pivot (the
    frontend resolves that before calling), keeping the hierarchy exactly two
    levels deep."""
    session = _get_session_or_404(session_id)
    if not any(p.id == body.pivot_id for p in session.pivots):
        raise HTTPException(status_code=404, detail=f"No pivot '{body.pivot_id}' in this session's analysis.")
    session.report_slides.append(
        ReportSlide(
            id=f"slide_{body.pivot_id}_{len(session.report_slides)}_{uuid.uuid4().hex[:8]}",
            title=body.title,
            pivot_id=body.pivot_id,
            filters=body.filters,
            parent_id=body.parent_id,
        )
    )
    return _synced_slides_response(session)


@router.patch("/{session_id}/slides/{slide_id}", response_model=ReportSlidesResponse)
def update_report_slide(session_id: str, slide_id: str, body: UpdateReportSlideRequest) -> ReportSlidesResponse:
    session = _get_session_or_404(session_id)
    slide = _get_slide_or_404(session, slide_id)
    updates = {}
    if body.title is not None:
        updates["title"] = body.title
    if body.filters is not None:
        updates["filters"] = body.filters
    if updates:
        session.report_slides = [s.model_copy(update=updates) if s.id == slide_id else s for s in session.report_slides]
    else:
        _ = slide  # nothing to change
    return _synced_slides_response(session)


@router.delete("/{session_id}/slides/{slide_id}", response_model=ReportSlidesResponse)
def delete_report_slide(session_id: str, slide_id: str) -> ReportSlidesResponse:
    session = _get_session_or_404(session_id)
    slide = _get_slide_or_404(session, slide_id)
    if slide.parent_id is None:
        raise HTTPException(status_code=400, detail="Can't delete a pivot's base slide -- only a duplicated one.")
    session.report_slides = [s for s in session.report_slides if s.id != slide_id]
    return _synced_slides_response(session)


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
    """Streams a .pptx built from the session's explicit slide list (see
    /slides) -- each slide is recomputed fresh from the raw data using its
    OWN filters and its own title, independent of whatever's currently shown
    on the Analysis page. Every chart is native, built fresh, never a
    picture."""
    session = _get_session_or_404(session_id)
    if not session.pivots:
        raise HTTPException(
            status_code=422,
            detail="No pivot tables have been computed yet -- run the Analysis step before downloading a report.",
        )

    combined_defs = list(pivot_defs_store.store.definitions or []) + session.extra_pivot_defs
    slides = report_slides.sync_slides(session.pivots, session.report_slides, session.pivot_filter_state)
    session.report_slides = slides
    pptx_bytes = report_generator.build_report(
        source_label=session.filename,
        df=session.df,
        slides=slides,
        definitions=combined_defs,
        overall=session.overall_analysis,
    )

    stem = session.filename.rsplit(".", 1)[0] if "." in session.filename else session.filename
    filename = f"{stem}_report.pptx"
    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
