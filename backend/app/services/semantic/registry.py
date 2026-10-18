"""Versioned semantic artifacts, independent of where they are stored.

The registry is append-only. Every change (onboarding, a steward's approval) adds a new version
of an artifact and the latest version wins at runtime, so history is never lost and two writers
cannot overwrite each other.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from app.services.semantic.models import (
    BusinessRule,
    DictionaryKpi,
    DomainPackage,
    EntityRegistration,
    GlossaryTerm,
    MetricVersion,
    QueryExample,
    RegisteredJoin,
    ValidatedSql,
)

ArtifactType = Literal[
    "entity", "join", "metric", "glossary", "rule", "dictionary_kpi", "validated_sql", "query_example"
]
ArtifactStatus = Literal["active", "draft", "deprecated"]
ArtifactSource = Literal["heuristic", "llm", "manual"]

_MODELS: dict[str, Any] = {
    "entity": EntityRegistration,
    "join": RegisteredJoin,
    "metric": MetricVersion,
    "glossary": GlossaryTerm,
    "rule": BusinessRule,
    "dictionary_kpi": DictionaryKpi,
    "validated_sql": ValidatedSql,
    "query_example": QueryExample,
}
_IDENTITY = {
    "entity": lambda value: value.physical_dataset,
    "join": lambda value: value.id,
    "metric": lambda value: value.id,
    "glossary": lambda value: value.term.lower(),
    "rule": lambda value: value.id,
    "dictionary_kpi": lambda value: value.family,
    "validated_sql": lambda value: value.id,
    "query_example": lambda value: value.question.lower(),
}


def utc_now() -> str:
    # Microseconds keep two changes made in the same second in a well-defined order.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def schema_fingerprint(frames: dict[str, pd.DataFrame]) -> str:
    """Identity of the connected datasets' structure: table names, column names and types.

    Row counts are left out on purpose. New rows in the same tables do not change what the
    semantic layer describes, so they must not trigger a new onboarding run.
    """
    shape = [
        {
            "dataset": name,
            "columns": [{"name": str(c), "dtype": str(frame[c].dtype)} for c in frame.columns],
        }
        for name, frame in sorted(frames.items())
    ]
    raw = json.dumps(shape, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class SemanticArtifact(BaseModel):
    domain: str
    semantic_version: str
    artifact_type: ArtifactType
    artifact_id: str
    status: ArtifactStatus
    source: ArtifactSource = "llm"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    payload: dict[str, Any]
    created_at: str = Field(default_factory=utc_now)
    input_fingerprint: str
    validation_message: str = ""

    def to_record(self) -> dict[str, Any]:
        record = self.model_dump(exclude={"payload"})
        record["payload"] = json.dumps(self.payload, default=str, sort_keys=True)
        return record

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> SemanticArtifact:
        payload = record.get("payload")
        if isinstance(payload, str):
            payload = json.loads(payload)
        return cls.model_validate({**record, "payload": payload or {}})


class SemanticRegistry:
    """The artifacts of one domain. The latest version of an artifact controls runtime use.

    ``append`` remembers what was added since the registry was loaded; a store persists exactly
    those artifacts via ``drain_pending``.
    """

    def __init__(self, artifacts: Iterable[SemanticArtifact] | None = None) -> None:
        self.artifacts = list(artifacts or [])
        self._pending: list[SemanticArtifact] = []

    @classmethod
    def from_records(cls, records: Iterable[dict[str, Any]]) -> SemanticRegistry:
        artifacts: list[SemanticArtifact] = []
        for row in records:
            try:
                artifacts.append(SemanticArtifact.from_record(row))
            except ValueError:  # a malformed row must not hide the valid ones
                continue
        return cls(artifacts)

    def append(self, artifact: SemanticArtifact) -> None:
        self.artifacts.append(artifact)
        self._pending.append(artifact)

    def drain_pending(self) -> list[SemanticArtifact]:
        """Artifacts appended since the last drain (or load). Clears the list."""
        pending, self._pending = self._pending, []
        return pending

    def history(self, domain: str, artifact_type: str, artifact_id: str) -> list[SemanticArtifact]:
        """Every version of one artifact, newest first."""
        versions = [
            a
            for a in self.artifacts
            if a.domain == domain and a.artifact_type == artifact_type and a.artifact_id == artifact_id
        ]
        return sorted(versions, key=lambda a: (a.created_at, a.semantic_version), reverse=True)

    def current(self, domain: str) -> list[SemanticArtifact]:
        """The newest version of every artifact, whatever its status. This is what a steward reviews."""
        newest: dict[tuple[str, str], SemanticArtifact] = {}
        for artifact in sorted(self.artifacts, key=lambda a: (a.created_at, a.semantic_version)):
            if artifact.domain == domain:
                newest[(artifact.artifact_type, artifact.artifact_id)] = artifact
        return list(newest.values())

    def latest(self, domain: str, *, include_drafts: bool = False) -> list[SemanticArtifact]:
        """The version of each artifact that runtime should use.

        An artifact whose newest version is deprecated is dropped. Otherwise the newest active
        version is used, or the newest of any status when ``include_drafts`` is set.
        """
        grouped: dict[tuple[str, str], list[SemanticArtifact]] = {}
        for artifact in self.artifacts:
            if artifact.domain == domain:
                grouped.setdefault((artifact.artifact_type, artifact.artifact_id), []).append(artifact)
        chosen: list[SemanticArtifact] = []
        for versions in grouped.values():
            ordered = sorted(versions, key=lambda a: (a.created_at, a.semantic_version), reverse=True)
            if ordered[0].status == "deprecated":
                continue
            if include_drafts:
                chosen.append(ordered[0])
                continue
            active = next((artifact for artifact in ordered if artifact.status == "active"), None)
            if active is not None:
                chosen.append(active)
        return chosen

    def has_fingerprint(self, domain: str, fingerprint: str) -> bool:
        return any(a.domain == domain and a.input_fingerprint == fingerprint for a in self.artifacts)

    def overlay(self, package: DomainPackage, *, include_drafts: bool = False) -> DomainPackage:
        """Overlay registry semantics onto a package without mutating the package."""
        out = package.model_copy(deep=True)
        collections: dict[str, list[Any]] = {
            "entity": out.entities,
            "join": out.joins,
            "metric": out.metrics,
            "glossary": out.glossary,
            "rule": out.rules,
            "dictionary_kpi": out.dictionary.kpis,
            "validated_sql": out.validated_sql,
            "query_example": out.query_examples,
        }
        for artifact in self.latest(out.domain, include_drafts=include_drafts):
            value = _MODELS[artifact.artifact_type].model_validate(artifact.payload)
            identity = _IDENTITY[artifact.artifact_type]
            target = collections[artifact.artifact_type]
            target[:] = [current for current in target if identity(current) != identity(value)]
            target.append(value)
        return out
