"""Persist extracted metadata as JSON under storage/metadata/<domain>/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai4bi.config.errors import DataNotFoundError


class MetadataStore:
    FILENAME = "dataset_catalog.json"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path(self, domain: str) -> Path:
        return self.root / domain / self.FILENAME

    def save(self, metadata: dict[str, Any]) -> Path:
        domain = str(metadata.get("domain") or "")
        if not domain:
            raise ValueError("metadata must include a domain")
        target = self.path(domain)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
        return target

    def load(self, domain: str) -> dict[str, Any]:
        target = self.path(domain)
        if not target.exists():
            raise DataNotFoundError(
                f"No metadata for {domain!r} at {target}. Run: python -m local refresh-metadata --domain {domain}"
            )
        return json.loads(target.read_text(encoding="utf-8"))

    def exists(self, domain: str) -> bool:
        return self.path(domain).exists()
