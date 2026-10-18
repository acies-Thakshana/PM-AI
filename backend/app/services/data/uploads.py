"""Getting a user's dataset files into the system.

Two ways in, both ending in the same place (``datasets/<domain>/<table>.<ext>``):

* **Presigned POST** (AWS). The API hands the browser a short-lived S3 form target with a size
  limit baked in; the file goes straight to S3 and never passes through the API. The client then
  calls ``complete`` so the file is checked.
* **Direct upload** (local, or small files). The file is sent to the API, which checks and stores it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

# AWS-DISABLED: from botocore.exceptions import ClientError

from app.config import UPLOAD_EXTENSIONS
from app.errors import DataNotFoundError, InvalidInputError
# AWS-DISABLED: from app.services.common import aws_clients
from app.services.common.naming import table_name_from_filename, validate_domain
from app.services.data.cache import DataCache
# AWS-DISABLED: from app.services.data.s3_source import dataset_key
from app.services.data.source import DatasetSource
from app.services.data.tabular import read_table_bytes

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class UploadTarget:
    """Where and how a client should send one file."""

    mode: Literal["presigned", "direct"]  # presigned: POST ``fields`` and the file to ``url``; direct: send to the API
    table: str
    filename: str
    url: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    max_bytes: int = 0


class DatasetStorage(Protocol):
    def presign(self, domain: str, filename: str) -> UploadTarget | None:
        """A direct-to-storage upload target, or ``None`` when files must go through the API."""
        ...

    def save(self, domain: str, filename: str, data: bytes) -> None: ...

    def size(self, domain: str, filename: str) -> int | None:
        """Size in bytes of a stored file, or ``None`` if it does not exist."""
        ...

    def read(self, domain: str, filename: str) -> bytes: ...

    def delete(self, domain: str, filename: str) -> None: ...


class LocalDatasetStorage:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def _path(self, domain: str, filename: str) -> Path:
        return self._root / validate_domain(domain) / filename

    def presign(self, domain: str, filename: str) -> UploadTarget | None:
        return None

    def save(self, domain: str, filename: str, data: bytes) -> None:
        path = self._path(domain, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".part")
        temporary.write_bytes(data)
        temporary.replace(path)

    def size(self, domain: str, filename: str) -> int | None:
        path = self._path(domain, filename)
        return path.stat().st_size if path.is_file() else None

    def read(self, domain: str, filename: str) -> bytes:
        return self._path(domain, filename).read_bytes()

    def delete(self, domain: str, filename: str) -> None:
        self._path(domain, filename).unlink(missing_ok=True)


# AWS-DISABLED: class S3DatasetStorage:
# AWS-DISABLED:     def __init__(self, bucket: str, *, expiry_seconds: int, max_bytes: int) -> None:
# AWS-DISABLED:         self._bucket = bucket
# AWS-DISABLED:         self._expiry = expiry_seconds
# AWS-DISABLED:         self._max_bytes = max_bytes

# AWS-DISABLED:     def presign(self, domain: str, filename: str) -> UploadTarget | None:
# AWS-DISABLED:         key = dataset_key(validate_domain(domain), filename)
# AWS-DISABLED:         post = aws_clients.s3().generate_presigned_post(
# AWS-DISABLED:             Bucket=self._bucket,
# AWS-DISABLED:             Key=key,
# AWS-DISABLED:             Conditions=[["content-length-range", 1, self._max_bytes]],
# AWS-DISABLED:             ExpiresIn=self._expiry,
# AWS-DISABLED:         )
# AWS-DISABLED:         return UploadTarget(
# AWS-DISABLED:             mode="presigned",
# AWS-DISABLED:             table=table_name_from_filename(filename),
# AWS-DISABLED:             filename=filename,
# AWS-DISABLED:             url=post["url"],
# AWS-DISABLED:             fields=post["fields"],
# AWS-DISABLED:             max_bytes=self._max_bytes,
# AWS-DISABLED:         )

# AWS-DISABLED:     def save(self, domain: str, filename: str, data: bytes) -> None:
# AWS-DISABLED:         aws_clients.s3().put_object(Bucket=self._bucket, Key=dataset_key(domain, filename), Body=data)

# AWS-DISABLED:     def size(self, domain: str, filename: str) -> int | None:
# AWS-DISABLED:         try:
# AWS-DISABLED:             head = aws_clients.s3().head_object(Bucket=self._bucket, Key=dataset_key(domain, filename))
# AWS-DISABLED:         except ClientError as exc:
# AWS-DISABLED:             if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
# AWS-DISABLED:                 return None
# AWS-DISABLED:             raise
# AWS-DISABLED:         return int(head["ContentLength"])

# AWS-DISABLED:     def read(self, domain: str, filename: str) -> bytes:
# AWS-DISABLED:         response = aws_clients.s3().get_object(Bucket=self._bucket, Key=dataset_key(domain, filename))
# AWS-DISABLED:         return response["Body"].read()

# AWS-DISABLED:     def delete(self, domain: str, filename: str) -> None:
# AWS-DISABLED:         aws_clients.s3().delete_object(Bucket=self._bucket, Key=dataset_key(domain, filename))


def _check_filename(filename: str) -> str:
    """The stored file name (``<table>.<lowercase ext>``) for an upload, or an error.

    Normalising here means ``Cases.CSV`` and ``cases.csv`` are the same table, and no caller
    can smuggle a directory part into a path or S3 key.
    """
    name = Path(str(filename or "").replace("\\", "/")).name
    if not name or name.startswith("."):
        raise InvalidInputError("A file name is required.")
    suffix = Path(name).suffix.lower()
    if suffix not in UPLOAD_EXTENSIONS:
        raise InvalidInputError(f"Unsupported file type. Use one of: {', '.join(UPLOAD_EXTENSIONS)}.")
    return f"{table_name_from_filename(name)}{suffix}"


class UploadService:
    def __init__(self, storage: DatasetStorage, source: DatasetSource, cache: DataCache, *, max_bytes: int) -> None:
        self._storage = storage
        self._source = source
        self._cache = cache
        self._max_bytes = max_bytes

    def create(self, domain: str, filename: str) -> UploadTarget:
        """Where to send the file. Falls back to ``direct`` when storage cannot take uploads itself."""
        validate_domain(domain)
        name = _check_filename(filename)
        target = self._storage.presign(domain, name)
        return target or UploadTarget(
            mode="direct", table=table_name_from_filename(name), filename=name, max_bytes=self._max_bytes
        )

    def save_direct(self, domain: str, filename: str, data: bytes) -> dict[str, Any]:
        """Check a file sent through the API, store it, and report what it contains."""
        validate_domain(domain)
        name = _check_filename(filename)
        if not data:
            raise InvalidInputError("The file is empty.")
        if len(data) > self._max_bytes:
            raise InvalidInputError(f"The file is larger than the {self._max_bytes // (1024 * 1024)} MB limit.")
        summary = self._describe(name, data)
        self._storage.save(domain, name, data)
        self._cache.invalidate(domain)
        return summary

    def complete(self, domain: str, filename: str) -> dict[str, Any]:
        """Check a file that was sent straight to storage. An unreadable file is removed."""
        validate_domain(domain)
        name = _check_filename(filename)
        size = self._storage.size(domain, name)
        if size is None:
            raise DataNotFoundError(f"{name} has not been uploaded for domain {domain!r}.")
        if size > self._max_bytes:
            self._storage.delete(domain, name)
            raise InvalidInputError(f"The file is larger than the {self._max_bytes // (1024 * 1024)} MB limit.")
        try:
            summary = self._describe(name, self._storage.read(domain, name))
        except InvalidInputError:
            self._storage.delete(domain, name)
            raise
        self._cache.invalidate(domain)
        return summary

    def tables(self, domain: str) -> list[str]:
        return self._source.list_tables(validate_domain(domain))

    @staticmethod
    def _describe(filename: str, data: bytes) -> dict[str, Any]:
        frame = read_table_bytes(filename, data)
        if frame.empty or not len(frame.columns):
            raise InvalidInputError(f"{filename} has no rows to analyse.")
        return {
            "table": table_name_from_filename(filename),
            "filename": filename,
            "rows": int(len(frame)),
            "columns": [str(column) for column in frame.columns],
        }
