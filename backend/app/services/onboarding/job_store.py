"""Status of background onboarding jobs, so a client can poll ``GET /api/jobs/{id}``.

Locally one JSON file per job; on AWS one DynamoDB item per job (partition ``job_id``) that
expires after ``ttl_days``.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from app.services.common import dynamo

JobStatus = Literal["queued", "running", "succeeded", "failed"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Job:
    job_id: str
    domain: str
    user_id: str
    status: JobStatus = "queued"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        return cls(**{name: data[name] for name in cls.__dataclass_fields__ if name in data})


class JobStore(Protocol):
    def save(self, job: Job) -> None:
        """Create the job or replace its stored state."""
        ...

    def get(self, job_id: str) -> Job | None: ...


class LocalJobStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._lock = threading.Lock()

    def _path(self, job_id: str) -> Path:
        return self._root / f"{job_id}.json"

    def save(self, job: Job) -> None:
        job.updated_at = _now()
        with self._lock:
            self._root.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=str(self._root), suffix=".tmp")
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(asdict(job), stream, default=str)
            os.replace(temporary, self._path(job.job_id))

    def get(self, job_id: str) -> Job | None:
        path = self._path(job_id)
        with self._lock:
            if not path.exists():
                return None
            return Job.from_dict(json.loads(path.read_text(encoding="utf-8")))


class DynamoJobStore:
    def __init__(self, table: str, ttl_days: int) -> None:
        self._table = table
        self._ttl_days = ttl_days

    def save(self, job: Job) -> None:
        job.updated_at = _now()
        dynamo.put_item(
            self._table,
            {
                "job_id": job.job_id,
                "domain": job.domain,
                "user_id": job.user_id,
                "status": job.status,
                "created_at": job.created_at,
                "updated_at": job.updated_at,
                "error": job.error,
                "payload": json.dumps(job.result, default=str),
                "expires_at": dynamo.expiry(self._ttl_days),
            },
        )

    def get(self, job_id: str) -> Job | None:
        item = dynamo.get_item(self._table, {"job_id": job_id})
        if item is None:
            return None
        return Job.from_dict({**item, "result": json.loads(item.get("payload") or "{}")})
