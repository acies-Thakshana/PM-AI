import io
import json

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pptx import Presentation

from app.schemas import (
    ApplyPivotsRequest,
    LanguageOption,
    OverallAnalysisReport,
    PivotDefinitionsSummary,
    PivotReport,
    ReportFilterScopeResponse,
    ReportFiltersResponse,
    ReportTemplateSummary,
    ReportTitlesResponse,
    SetReportFilterScopeRequest,
    SetReportFiltersRequest,
    SetReportTitleRequest,
    SupportedLanguagesResponse,
)
from app.services import overall_analysis, overall_narrative, pivot_engine, report_generator, translation_service
from app.services import pivot_definitions_store as pivot_defs_store
from app.services import report_template_store
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


@router.post("/{session_id}/pivots", response_model=PivotReport)
def apply_pivots(session_id: str, body: ApplyPivotsRequest | None = None) -> PivotReport:
    session = _get_session_or_404(session_id)
    if pivot_defs_store.store.definitions is None:
        raise HTTPException(
            status_code=422,
            detail="No Analysis Profile has been uploaded yet -- upload one (with your pivot table "
                   "definitions) before analysis can run. There is no default.",
        )
    # `extra_pivots` omitted (None) means "leave the custom pivots already
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


@router.get("/{session_id}/overall", response_model=OverallAnalysisReport)
def get_overall_analysis(session_id: str) -> OverallAnalysisReport:
    session = _get_session_or_404(session_id)
    highlights = overall_analysis.build_highlights(len(session.df), session.features, session.pivots)
    narrative = overall_narrative.generate_narrative(len(session.df), highlights)
    report = OverallAnalysisReport(session_id=session_id, row_count=len(session.df), highlights=highlights, narrative=narrative)
    session.overall_analysis = report
    return report


@router.get("/languages", response_model=SupportedLanguagesResponse)
def get_supported_languages() -> SupportedLanguagesResponse:
    """Languages the downloaded report can be translated into (see
    translation_service.py) -- "en" (no translation, the default) plus
    whatever DeepL target languages that module currently lists."""
    languages = [LanguageOption(code="en", name="English")] + [
        LanguageOption(code=code, name=name)
        for code, (name, _) in sorted(translation_service.SUPPORTED_LANGUAGES.items(), key=lambda kv: kv[1][0])
    ]
    return SupportedLanguagesResponse(languages=languages)


@router.get("/{session_id}/report")
def download_report(session_id: str, language: str = "en"):
    """Streams a .pptx built from every current pivot, each recomputed fresh
    from the raw data using the session's one shared report_filters (see
    /report-filters) -- a column with 2+ selected values there fans out into
    one slide per value, per pivot. Every chart is native, built fresh,
    never a picture.

    `language` (optional, default "en") translates the report's own fixed
    English phrases -- see report_generator.TRANSLATABLE_PHRASES -- into one
    of the codes /languages lists; the underlying data (pivot/column names,
    category values) is never translated. If the translation API isn't
    configured or fails, the report still downloads, just in English."""
    session = _get_session_or_404(session_id)
    if not session.pivots:
        raise HTTPException(
            status_code=422,
            detail="No pivot tables have been computed yet -- run the Analysis step before downloading a report.",
        )
    if language != "en" and language not in translation_service.SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"Unsupported language '{language}'.")

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
        language=language,
    )

    filename = f"{report_generator.REPORT_NAME}.pptx"
    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
