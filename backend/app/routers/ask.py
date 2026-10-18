"""Ask a question in plain language."""

from __future__ import annotations

from fastapi import APIRouter

from app.routers.deps import ContextDep, CurrentUser, SettingsDep, authorize_domain
from app.schemas import AskRequest, AskResponse
from app.services.ask.pipeline import ask

router = APIRouter(prefix="/api", tags=["ask"])


@router.post("/ask", response_model=AskResponse)
def ask_question(body: AskRequest, user: CurrentUser, ctx: ContextDep, settings: SettingsDep) -> dict:
    domain = authorize_domain(user, body.domain or settings.default_domain, settings)
    # Sessions are private to the user who started them: a guessed session id reveals nothing.
    session_id = f"{user.id}:{body.session_id}" if body.session_id else None
    return ask(body.question, context=ctx, domain=domain, session_id=session_id)
