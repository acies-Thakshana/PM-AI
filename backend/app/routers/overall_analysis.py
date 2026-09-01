from fastapi import APIRouter, HTTPException

from app.schemas import OverallAnalysisReport
from app.services import overall_analysis, overall_analysis_agent
from app.routers._common import get_session_or_404 as _get_session_or_404

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


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
