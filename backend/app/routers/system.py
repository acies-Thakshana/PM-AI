"""Liveness and deployment information."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.routers.deps import CurrentUser, SettingsDep
from app.schemas import HealthResponse, InfoResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe for the load balancer. Public, and deliberately checks nothing else."""
    return HealthResponse()


@router.get("/api/info", response_model=InfoResponse)
def info(user: CurrentUser, settings: SettingsDep) -> InfoResponse:
    return InfoResponse(
        version=__version__,
        storage_backend=settings.storage_backend,
        llm_mode=settings.llm_mode,
        auth_enabled=settings.auth_enabled,
        default_domain=settings.default_domain,
        user=user.id,
        roles=sorted(user.roles),
    )
