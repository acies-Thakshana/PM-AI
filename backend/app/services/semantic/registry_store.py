"""Where the semantic registry lives: JSON files locally, a DynamoDB table on AWS.

Both stores are append-only. ``save`` persists only the artifacts added since the registry was
loaded, so concurrent writers add rows side by side instead of overwriting each other.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Protocol

from app.services.common import dynamo
from app.services.semantic.registry import SemanticArtifact, SemanticRegistry


class RegistryStore(Protocol):
    def load(self, domain: str) -> SemanticRegistry:
        """Every stored version of every artifact of the domain."""
        ...

    def save(self, domain: str, registry: SemanticRegistry) -> int:
        """Persist what was appended to ``registry`` since it was loaded. Returns the count."""
        ...


class LocalRegistryStore:
    """``<root>/<domain>.json``, rewritten atomically under a process-wide lock."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._lock = threading.Lock()

    def _path(self, domain: str) -> Path:
        return self._root / f"{domain}.json"

    def _read(self, domain: str) -> list[dict[str, Any]]:
        path = self._path(domain)
        if not path.exists():
            return []
        return list(json.loads(path.read_text(encoding="utf-8")).get("artifacts") or [])

    def load(self, domain: str) -> SemanticRegistry:
        with self._lock:
            return SemanticRegistry.from_records(self._read(domain))

    def save(self, domain: str, registry: SemanticRegistry) -> int:
        pending = registry.drain_pending()
        if not pending:
            return 0
        with self._lock:
            records = self._read(domain) + [artifact.to_record() for artifact in pending]
            self._root.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=str(self._root), suffix=".tmp")
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"domain": domain, "artifacts": records}, stream, indent=2, default=str)
            os.replace(temporary, self._path(domain))
        return len(pending)


class DynamoRegistryStore:
    """Partition ``domain``, sort ``<type>#<id>#<created_at>#<version>``, JSON ``payload``.

    Every version is its own item, so a write never touches another version's item.
    """

    def __init__(self, table: str) -> None:
        self._table = table

    @staticmethod
    def _sort_key(artifact: SemanticArtifact) -> str:
        return f"{artifact.artifact_type}#{artifact.artifact_id}#{artifact.created_at}#{artifact.semantic_version}"

    def load(self, domain: str) -> SemanticRegistry:
        items = dynamo.query(self._table, ("domain", domain))
        return SemanticRegistry.from_records(json.loads(item["artifact"]) for item in items)

    def save(self, domain: str, registry: SemanticRegistry) -> int:
        pending = registry.drain_pending()
        dynamo.batch_put(
            self._table,
            (
                {
                    "domain": domain,
                    "sort_key": self._sort_key(artifact),
                    "artifact": json.dumps(artifact.to_record(), default=str),
                }
                for artifact in pending
            ),
        )
        return len(pending)
