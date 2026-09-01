import io

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pptx import Presentation

from app.schemas import (
    ReportFilterScopeResponse,
    ReportFiltersResponse,
    ReportTemplateSummary,
    ReportTitlesResponse,
    SetReportFilterScopeRequest,
    SetReportFiltersRequest,
    SetReportTitleRequest,
)
from app.services import report_generator
from app.services import pivot_definitions_store as pivot_defs_store
from app.services import report_template_store
from app.routers._common import get_session_or_404 as _get_session_or_404

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.post("/report-template", response_model=ReportTemplateSummary)
async def upload_report_template(file: UploadFile = File(...)) -> ReportTemplateSummary:
    """Optional -- a .pptx to use as the base for every downloaded report
    instead of the built-in layout (see report_generator.build_report). Not
    validated beyond "is it a real pptx" here; report_template_builder falls
    back to the first available layout for anything it can't name-match, so
    an unfamiliar template still produces a deck."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")
    try:
        Presentation(io.BytesIO(raw))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Not a valid .pptx file: {exc}") from exc

    filename = file.filename or "report_template.pptx"
    report_template_store.store.set(filename, raw)
    return ReportTemplateSummary(filename=filename)


@router.get("/report-template", response_model=ReportTemplateSummary)
def get_report_template() -> ReportTemplateSummary:
    return ReportTemplateSummary(filename=report_template_store.store.filename)


@router.delete("/report-template", response_model=ReportTemplateSummary)
def clear_report_template() -> ReportTemplateSummary:
    report_template_store.store.clear()
    return ReportTemplateSummary(filename=None)


@router.get("/{session_id}/report-filters", response_model=ReportFiltersResponse)
def get_report_filters(session_id: str) -> ReportFiltersResponse:
    session = _get_session_or_404(session_id)
    return ReportFiltersResponse(session_id=session.session_id, filters=session.report_filters)


@router.post("/{session_id}/report-filters", response_model=ReportFiltersResponse)
def set_report_filters(session_id: str, body: SetReportFiltersRequest) -> ReportFiltersResponse:
    """The ONE shared filter set for the whole downloaded report -- replaces
    it wholesale (there's only one, unlike the per-pivot pivot_filters map).
    Report-time only -- never touches session.pivots. Selecting 2+ values
    for a column here means the report gets one slide per value for every
    pivot, instead of one slide combining them (see report_generator)."""
    session = _get_session_or_404(session_id)
    session.report_filters = body.filters
    return ReportFiltersResponse(session_id=session.session_id, filters=session.report_filters)


@router.get("/{session_id}/report-filter-scope", response_model=ReportFilterScopeResponse)
def get_report_filter_scope(session_id: str) -> ReportFilterScopeResponse:
    """Merges any explicit per-pivot overrides with report_generator's
    default scope exclusions (see DEFAULT_SCOPE_EXCLUSIONS) so the Report
    page's filter-scope chips reflect the same defaults the downloaded .pptx
    actually uses, without requiring the user to have touched a chip first."""
    session = _get_session_or_404(session_id)
    active_columns = [f.column for f in session.report_filters]
    scope = dict(session.pivot_filter_scope)
    for pivot in session.pivots:
        if pivot.id in scope:
            continue
        default = report_generator.resolve_default_scope(pivot.name, active_columns)
        if default is not None:
            scope[pivot.id] = default
    return ReportFilterScopeResponse(session_id=session.session_id, scope=scope)


@router.post("/{session_id}/report-filter-scope", response_model=ReportFilterScopeResponse)
def set_report_filter_scope(session_id: str, body: SetReportFilterScopeRequest) -> ReportFilterScopeResponse:
    """Which of the shared report_filters columns actually apply to ONE
    pivot -- e.g. pivot_1 scoped to just ["Country of Origin"] ignores
    Origin/Carrier/Product/departure-range even though they're set overall.
    `columns=None` clears the override (back to "every active column
    applies", the default). Only touches this one pivot id."""
    session = _get_session_or_404(session_id)
    if body.columns is None:
        session.pivot_filter_scope.pop(body.pivot_id, None)
    else:
        session.pivot_filter_scope[body.pivot_id] = body.columns
    return ReportFilterScopeResponse(session_id=session.session_id, scope=session.pivot_filter_scope)


@router.get("/{session_id}/report-titles", response_model=ReportTitlesResponse)
def get_report_titles(session_id: str) -> ReportTitlesResponse:
    session = _get_session_or_404(session_id)
    return ReportTitlesResponse(session_id=session.session_id, titles=session.report_titles)


@router.post("/{session_id}/report-titles", response_model=ReportTitlesResponse)
def set_report_title(session_id: str, body: SetReportTitleRequest) -> ReportTitlesResponse:
    """Purely cosmetic -- renames a pivot's slide heading in the downloaded
    report (and the prefix of any of its multiplied variants). `title=None`
    clears the override, back to the pivot's own name."""
    session = _get_session_or_404(session_id)
    if body.title is None or not body.title.strip():
        session.report_titles.pop(body.pivot_id, None)
    else:
        session.report_titles[body.pivot_id] = body.title.strip()
    return ReportTitlesResponse(session_id=session.session_id, titles=session.report_titles)


@router.get("/{session_id}/report")
def download_report(session_id: str):
    """Streams a .pptx built from every current pivot, each recomputed fresh
    from the raw data using the session's one shared report_filters (see
    /report-filters) -- a column with 2+ selected values there fans out into
    one slide per value, per pivot. Every chart is native, built fresh,
    never a picture."""
    session = _get_session_or_404(session_id)
    if not session.pivots:
        raise HTTPException(
            status_code=422,
            detail="No pivot tables have been computed yet -- run the Analysis step before downloading a report.",
        )

    combined_defs = list(pivot_defs_store.store.definitions or []) + session.extra_pivot_defs
    pptx_bytes = report_generator.build_report(
        source_label=report_generator.REPORT_NAME,
        df=session.df,
        pivots=session.pivots,
        definitions=combined_defs,
        report_filters=[f.model_dump() for f in session.report_filters],
        pivot_filter_scope=session.pivot_filter_scope,
        report_titles=session.report_titles,
        overall=session.overall_analysis,
        template_bytes=report_template_store.store.content,
    )

    filename = f"{report_generator.REPORT_NAME}.pptx"
    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
