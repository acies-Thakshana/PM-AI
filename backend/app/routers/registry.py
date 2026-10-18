"""Stewardship: review what onboarding learned and curate the semantic layer. Stewards only."""

from __future__ import annotations

from fastapi import APIRouter

from app.routers.deps import ContextDep, Steward, StewardDomain
from app.schemas import ArtifactRef, RegistryArtifact
from app.services.onboarding import stewardship
from app.services.semantic.models import GlossaryTerm, RegisteredJoin, ValidatedSql
from app.services.semantic.registry import SemanticArtifact

router = APIRouter(prefix="/api/domains/{domain}/registry", tags=["stewardship"])


def _view(artifact: SemanticArtifact) -> RegistryArtifact:
    return RegistryArtifact(**artifact.model_dump(exclude={"domain", "input_fingerprint"}))


@router.get("", response_model=list[RegistryArtifact])
def list_artifacts(domain: StewardDomain, ctx: ContextDep) -> list[RegistryArtifact]:
    """The newest version of every artifact, drafts and deprecated ones included."""
    return [_view(artifact) for artifact in stewardship.list_artifacts(ctx, domain)]


@router.post("/approve", response_model=RegistryArtifact)
def approve(domain: StewardDomain, body: ArtifactRef, user: Steward, ctx: ContextDep) -> RegistryArtifact:
    return _view(stewardship.approve(ctx, domain, body.artifact_type, body.artifact_id, user.id))


@router.post("/deprecate", response_model=RegistryArtifact)
def deprecate(domain: StewardDomain, body: ArtifactRef, user: Steward, ctx: ContextDep) -> RegistryArtifact:
    return _view(stewardship.deprecate(ctx, domain, body.artifact_type, body.artifact_id, user.id))


@router.post("/glossary", response_model=RegistryArtifact, status_code=201)
def add_glossary_term(domain: StewardDomain, body: GlossaryTerm, user: Steward, ctx: ContextDep) -> RegistryArtifact:
    return _view(stewardship.add_glossary_term(ctx, domain, body, user.id))


@router.post("/validated-sql", response_model=RegistryArtifact, status_code=201)
def add_validated_sql(domain: StewardDomain, body: ValidatedSql, user: Steward, ctx: ContextDep) -> RegistryArtifact:
    """The query must validate and run against the domain's data before it is stored."""
    return _view(stewardship.add_validated_sql(ctx, domain, body, user.id))


@router.post("/joins", response_model=RegistryArtifact, status_code=201)
def add_join(domain: StewardDomain, body: RegisteredJoin, user: Steward, ctx: ContextDep) -> RegistryArtifact:
    return _view(stewardship.add_join(ctx, domain, body, user.id))
