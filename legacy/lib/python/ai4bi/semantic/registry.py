"""Versioned semantic artifacts independent of their persistence platform."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

import pandas as pd
from pydantic import BaseModel, Field

from ai4bi.semantic.models import (
    BusinessRule,
    DictionaryKpi,
    DomainPackage,
    EntityRegistration,
    GlossaryTerm,
    MetricVersion,
    RegisteredJoin,
)

ArtifactType = Literal["entity", "join", "metric", "glossary", "rule", "dictionary_kpi"]
ArtifactStatus = Literal["active", "draft", "deprecated"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def schema_fingerprint(frames: dict[str, pd.DataFrame]) -> str:
    """Stable identity for the connected datasets and their current schema."""
    shape = [
        {
            "dataset": name,
            "rows": int(len(frame)),
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
    source: Literal["heuristic", "llm", "yaml", "manual"] = "llm"
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
    def from_record(cls, record: dict[str, Any]) -> "SemanticArtifact":
        payload = record.get("payload")
        if isinstance(payload, str):
            payload = json.loads(payload)
        return cls.model_validate({**record, "payload": payload or {}})


class SemanticRegistry:
    """Append-only registry. Latest version of an artifact controls runtime use."""

    def __init__(self, artifacts: Iterable[SemanticArtifact] | None = None) -> None:
        self.artifacts = list(artifacts or [])

    @classmethod
    def from_records(cls, records: Iterable[dict[str, Any]]) -> "SemanticRegistry":
        artifacts: list[SemanticArtifact] = []
        for row in records:
            try:
                artifacts.append(SemanticArtifact.from_record(row))
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
        return cls(artifacts)

    def to_records(self) -> list[dict[str, Any]]:
        return [artifact.to_record() for artifact in self.artifacts]

    def append(self, artifact: SemanticArtifact) -> None:
        self.artifacts.append(artifact)

    def latest(self, domain: str, *, include_drafts: bool = False) -> list[SemanticArtifact]:
        grouped: dict[tuple[str, str], list[SemanticArtifact]] = {}
        for artifact in self.artifacts:
            if artifact.domain != domain:
                continue
            key = (artifact.artifact_type, artifact.artifact_id)
            grouped.setdefault(key, []).append(artifact)
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
        """Overlay registry semantics without mutating the base/YAML package."""
        out = package.model_copy(deep=True)
        models: dict[str, Any] = {
            "entity": EntityRegistration,
            "join": RegisteredJoin,
            "metric": MetricVersion,
            "glossary": GlossaryTerm,
            "rule": BusinessRule,
            "dictionary_kpi": DictionaryKpi,
        }
        collections: dict[str, list[Any]] = {
            "entity": out.entities,
            "join": out.joins,
            "metric": out.metrics,
            "glossary": out.glossary,
            "rule": out.rules,
            "dictionary_kpi": out.dictionary.kpis,
        }
        keys = {
            "entity": lambda value: value.physical_dataset,
            "join": lambda value: value.id,
            "metric": lambda value: value.id,
            "glossary": lambda value: value.term.lower(),
            "rule": lambda value: value.id,
            "dictionary_kpi": lambda value: value.family,
        }
        for artifact in self.latest(out.domain, include_drafts=include_drafts):
            model = models[artifact.artifact_type]
            value = model.model_validate(artifact.payload)
            target = collections[artifact.artifact_type]
            identity = keys[artifact.artifact_type](value)
            target[:] = [current for current in target if keys[artifact.artifact_type](current) != identity]
            target.append(value)
        return out


class JsonSemanticRegistryStore:
    """Local persistence equivalent of the Dataiku semantic_registry dataset."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path(self, domain: str) -> Path:
        return self.root / f"{domain}.json"

    def load(self, domain: str) -> SemanticRegistry:
        path = self.path(domain)
        if not path.exists():
            return SemanticRegistry()
        payload = json.loads(path.read_text(encoding="utf-8"))
        return SemanticRegistry.from_records(payload.get("artifacts") or [])

    def save(self, domain: str, registry: SemanticRegistry) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path(domain)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"domain": domain, "artifacts": registry.to_records()}, indent=2, default=str),
            encoding="utf-8",
        )
        temporary.replace(path)
        return path
