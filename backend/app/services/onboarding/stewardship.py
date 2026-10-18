"""What a data steward can do with the semantic registry.

Every action appends a new version (``source="manual"``) and never edits or deletes an old one,
so the full history stays available and concurrent stewards cannot overwrite each other.
Saved changes take effect on the next question; nothing is cached across requests.
"""

from __future__ import annotations

from typing import Any

from app.errors import ConflictError, DataNotFoundError, InvalidInputError
from app.services.ask.checks import run_validated_sql
from app.services.ask.domain_view import DomainView, resolve_domain
from app.services.common import audit_log
from app.services.context import AppContext
from app.services.semantic.models import GlossaryTerm, RegisteredJoin, ValidatedSql
from app.services.semantic.registry import ArtifactStatus, ArtifactType, SemanticArtifact, SemanticRegistry, utc_now


def list_artifacts(ctx: AppContext, domain: str) -> list[SemanticArtifact]:
    """The newest version of every learned or curated artifact, drafts and deprecated ones included."""
    artifacts = ctx.registry.load(domain).current(domain)
    return sorted(artifacts, key=lambda a: (a.artifact_type, a.artifact_id))


def _append(ctx: AppContext, domain: str, registry: SemanticRegistry, artifact: SemanticArtifact) -> SemanticArtifact:
    registry.append(artifact)
    ctx.registry.save(domain, registry)
    return artifact


def _manual_version(previous: SemanticArtifact, status: ArtifactStatus, payload: dict[str, Any]) -> SemanticArtifact:
    return previous.model_copy(
        update={
            "status": status,
            "source": "manual",
            "confidence": 1.0,
            "payload": payload,
            "created_at": utc_now(),
            "validation_message": f"set to {status} by a steward",
        }
    )


def _newest(registry: SemanticRegistry, domain: str, artifact_type: str, artifact_id: str) -> SemanticArtifact:
    versions = registry.history(domain, artifact_type, artifact_id)
    if not versions:
        raise DataNotFoundError(f"No {artifact_type} named {artifact_id!r} in domain {domain!r}.")
    return versions[0]


def approve(ctx: AppContext, domain: str, artifact_type: str, artifact_id: str, user_id: str) -> SemanticArtifact:
    """Make a draft artifact active. Metrics become certified and joins become usable in questions."""
    registry = ctx.registry.load(domain)
    current = _newest(registry, domain, artifact_type, artifact_id)
    payload = dict(current.payload)
    if artifact_type == "metric":
        payload["status"] = "certified"
    elif artifact_type == "join":
        payload.update(allowed_for_nlq=True, approved_by=user_id)
    saved = _append(ctx, domain, registry, _manual_version(current, "active", payload))
    audit_log.record("steward_approve", artifact_type=artifact_type, artifact_id=artifact_id)
    return saved


def deprecate(ctx: AppContext, domain: str, artifact_type: str, artifact_id: str, user_id: str) -> SemanticArtifact:
    """Stop using an artifact. Its history stays; approving it again brings it back."""
    registry = ctx.registry.load(domain)
    current = _newest(registry, domain, artifact_type, artifact_id)
    payload = dict(current.payload)
    if artifact_type == "metric":
        payload["status"] = "deprecated"
    elif artifact_type == "join":
        payload["allowed_for_nlq"] = False
    saved = _append(ctx, domain, registry, _manual_version(current, "deprecated", payload))
    audit_log.record("steward_deprecate", artifact_type=artifact_type, artifact_id=artifact_id, by=user_id)
    return saved


def _new_artifact(
    domain: str, artifact_type: ArtifactType, artifact_id: str, payload: dict[str, Any]
) -> SemanticArtifact:
    return SemanticArtifact(
        domain=domain,
        semantic_version="manual",
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        status="active",
        source="manual",
        confidence=1.0,
        payload=payload,
        input_fingerprint="manual",
        validation_message="added by a steward",
    )


def add_glossary_term(ctx: AppContext, domain: str, term: GlossaryTerm, user_id: str) -> SemanticArtifact:
    view = resolve_domain(ctx, domain)
    if any(known.term.lower() == term.term.lower() for known in view.pkg.glossary):
        raise ConflictError(f"The glossary of {domain!r} already defines {term.term!r}.")
    registry = ctx.registry.load(domain)
    saved = _append(ctx, domain, registry, _new_artifact(domain, "glossary", term.term.lower(), term.model_dump()))
    audit_log.record("steward_add_glossary_term", term=term.term, by=user_id)
    return saved


def add_validated_sql(ctx: AppContext, domain: str, entry: ValidatedSql, user_id: str) -> SemanticArtifact:
    """Store a query as a trusted example, but only after it validates and runs against the data."""
    view = resolve_domain(ctx, domain)
    if any(known.id == entry.id for known in view.pkg.validated_sql):
        raise ConflictError(f"Domain {domain!r} already has a validated query with id {entry.id!r}.")
    executor = ctx.new_executor()
    try:
        check = run_validated_sql(ctx, executor, entry, view.pkg, view.tables)
    finally:
        executor.close()
    if not check.ok:
        raise InvalidInputError(f"The query is not valid for this domain: {check.detail}")
    stored = entry.model_copy(update={"validated_by": user_id, "validated_at": utc_now()})
    registry = ctx.registry.load(domain)
    saved = _append(ctx, domain, registry, _new_artifact(domain, "validated_sql", stored.id, stored.model_dump()))
    audit_log.record("steward_add_validated_sql", query_id=stored.id)
    return saved


def _check_join_columns(view: DomainView, join: RegisteredJoin) -> None:
    entities = {entity.logical_entity: entity for entity in view.pkg.entities}
    for key in join.keys:
        for side, column in ((key.left_entity, key.left_column), (key.right_entity, key.right_column)):
            entity = entities.get(side)
            if entity is None:
                raise InvalidInputError(f"Join {join.id!r} refers to unknown entity {side!r}.")
            frame = view.raw.get(entity.physical_dataset)
            if frame is None or column not in frame.columns:
                raise InvalidInputError(f"Join {join.id!r}: column {column!r} not found in {side!r}.")


def add_join(ctx: AppContext, domain: str, join: RegisteredJoin, user_id: str) -> SemanticArtifact:
    """Register a relationship between two datasets. Joins are never inferred at question time."""
    view = resolve_domain(ctx, domain)
    _check_join_columns(view, join)
    stored = join.model_copy(update={"allowed_for_nlq": True, "approved_by": user_id, "inferred": False})
    registry = ctx.registry.load(domain)
    saved = _append(ctx, domain, registry, _new_artifact(domain, "join", stored.id, stored.model_dump()))
    audit_log.record("steward_add_join", join_id=stored.id)
    return saved
