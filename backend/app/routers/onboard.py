"""Onboarding runs as a background job: start it, then poll for the result."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, status

from app.errors import DataNotFoundError, ForbiddenError
from app.routers.deps import ContextDep, CurrentUser, SettingsDep, Steward, StewardDomain, authorize_domain
from app.schemas import JobResponse, OnboardRequest
from app.services.onboarding.service import run_onboarding

router = APIRouter(prefix="/api", tags=["onboarding"])


@router.post("/domains/{domain}/onboard", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def start_onboarding(domain: StewardDomain, body: OnboardRequest, user: Steward, ctx: ContextDep) -> JobResponse:
    """Learn the semantics of the domain's datasets. Returns at once; poll ``GET /api/jobs/{job_id}``."""
    if not ctx.source.list_tables(domain):
        raise DataNotFoundError(f"Domain {domain!r} has no datasets. Upload files for it first.")
    job = ctx.runner.submit(domain, user.id, lambda: run_onboarding(ctx, domain, force=body.force))
    return JobResponse(**asdict(job))


@router.get("/jobs/{job_id}", response_model=JobResponse)
def job_status(job_id: str, user: CurrentUser, ctx: ContextDep, settings: SettingsDep) -> JobResponse:
    """Status of a job. Only the user who started it, or a steward with access to its domain, can see it."""
    job = ctx.runner.get(job_id)
    if job is None:
        raise DataNotFoundError("No such job.")
    is_steward = settings.role_steward in user.roles
    if job.user_id != user.id and not is_steward:
        raise ForbiddenError("This job belongs to another user.")
    authorize_domain(user, job.domain, settings)
    return JobResponse(**asdict(job))
