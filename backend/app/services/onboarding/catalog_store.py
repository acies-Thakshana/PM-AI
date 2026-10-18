"""The dataset catalog (table and column metadata) produced by onboarding.

Locally ``<root>/<domain>/dataset_catalog.json``; on AWS ``catalog/<domain>/dataset_catalog.json``
in the S3 bucket. The catalog holds only safe metadata (restricted columns carry no sample values).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Protocol

from botocore.exceptions import ClientError

from app.errors import DataNotFoundError
from app.services.common import aws_clients


class CatalogStore(Protocol):
    def save(self, domain: str, catalog: dict[str, Any]) -> None: ...

    def load(self, domain: str) -> dict[str, Any]:
        """The saved catalog. Raises ``DataNotFoundError`` when onboarding has not run."""
        ...


def _missing(domain: str) -> DataNotFoundError:
    return DataNotFoundError(f"No dataset catalog for domain {domain!r}. Onboard the domain first.")


class LocalCatalogStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def _path(self, domain: str) -> Path:
        return self._root / domain / "dataset_catalog.json"

    def save(self, domain: str, catalog: dict[str, Any]) -> None:
        path = self._path(domain)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(catalog, stream, indent=2, default=str)
        os.replace(temporary, path)

    def load(self, domain: str) -> dict[str, Any]:
        path = self._path(domain)
        if not path.exists():
            raise _missing(domain)
        return json.loads(path.read_text(encoding="utf-8"))


class S3CatalogStore:
    def __init__(self, bucket: str) -> None:
        self._bucket = bucket

    @staticmethod
    def _key(domain: str) -> str:
        return f"catalog/{domain}/dataset_catalog.json"

    def save(self, domain: str, catalog: dict[str, Any]) -> None:
        aws_clients.s3().put_object(
            Bucket=self._bucket,
            Key=self._key(domain),
            Body=json.dumps(catalog, default=str).encode("utf-8"),
            ContentType="application/json",
        )

    def load(self, domain: str) -> dict[str, Any]:
        try:
            body = aws_clients.s3().get_object(Bucket=self._bucket, Key=self._key(domain))["Body"].read()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                raise _missing(domain) from exc
            raise
        return json.loads(body)
