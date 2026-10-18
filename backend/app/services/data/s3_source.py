"""Datasets stored in S3: ``datasets/<domain>/<table>.<ext>`` in the configured bucket."""

from __future__ import annotations

import hashlib
import logging
from pathlib import PurePosixPath

import pandas as pd

from app.errors import DataNotFoundError
from app.services.common import aws_clients
from app.services.common.naming import validate_domain
from app.services.data.source import select_tables
from app.services.data.tabular import SUFFIXES, read_table_bytes

LOGGER = logging.getLogger(__name__)

DATASET_PREFIX = "datasets/"


def dataset_key(domain: str, filename: str) -> str:
    return f"{DATASET_PREFIX}{domain}/{filename}"


class S3Source:
    def __init__(self, bucket: str) -> None:
        self._bucket = bucket

    def _objects(self, domain: str) -> dict[str, dict]:
        """Table name to S3 object summary. When a table exists in two formats the earlier suffix wins."""
        prefix = dataset_key(validate_domain(domain), "")
        found: dict[str, dict] = {}
        paginator = aws_clients.s3().get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                path = PurePosixPath(obj["Key"][len(prefix) :])
                if len(path.parts) != 1 or path.name.startswith(".") or path.suffix.lower() not in SUFFIXES:
                    continue
                current = found.get(path.stem)
                if current is None or SUFFIXES.index(path.suffix.lower()) < SUFFIXES.index(
                    PurePosixPath(current["Key"]).suffix.lower()
                ):
                    found[path.stem] = obj
        return found

    def list_domains(self) -> list[str]:
        domains: list[str] = []
        paginator = aws_clients.s3().get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=DATASET_PREFIX, Delimiter="/"):
            for common in page.get("CommonPrefixes", []):
                name = common["Prefix"][len(DATASET_PREFIX) :].rstrip("/")
                if name and self._objects(name):
                    domains.append(name)
        return sorted(domains)

    def list_tables(self, domain: str) -> list[str]:
        return sorted(self._objects(domain))

    def version(self, domain: str) -> str:
        digest = hashlib.sha1(usedforsecurity=False)
        for name, obj in sorted(self._objects(domain).items()):
            digest.update(f"{name}:{obj['Key']}:{obj.get('ETag', '')}:{obj['Size']};".encode())
        return digest.hexdigest()

    def load(self, domain: str, table_names: list[str] | None = None) -> dict[str, pd.DataFrame]:
        objects = self._objects(domain)
        names = select_tables(domain, sorted(objects), table_names)
        client = aws_clients.s3()
        frames: dict[str, pd.DataFrame] = {}
        for name in names:
            key = objects[name]["Key"]
            body = client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
            frames[name] = read_table_bytes(PurePosixPath(key).name, body)
        if not frames:
            raise DataNotFoundError(f"No datasets for domain {domain!r}. Upload files for it first.")
        LOGGER.info("Loaded %s for domain %s from s3://%s", sorted(frames), domain, self._bucket)
        return frames
