"""Run long operations (onboarding makes several model calls) off the request thread.

The HTTP request returns a job id immediately and the client polls ``GET /api/jobs/{id}``, so a
slow onboarding never runs into a gateway timeout. The work runs on a small thread pool inside
the API process; if that process is stopped mid-job the job stays ``running`` until it expires,
and the client should simply start it again (onboarding is idempotent).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.errors import AI4BIError
from app.services.common import request_context
from app.services.onboarding.job_store import Job, JobStore

LOGGER = logging.getLogger(__name__)


class JobRunner:
    def __init__(self, store: JobStore, *, workers: int) -> None:
        self._store = store
        self._pool = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="ai4bi-job")

    def submit(self, domain: str, user_id: str, work: Callable[[], dict[str, Any]]) -> Job:
        """Queue ``work`` and return the new job. ``work`` returns the job's JSON-serialisable result."""
        job = Job(job_id=uuid.uuid4().hex, domain=domain, user_id=user_id)
        self._store.save(job)
        self._pool.submit(request_context.wrap(self._run), job, work)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._store.get(job_id)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _run(self, job: Job, work: Callable[[], dict[str, Any]]) -> None:
        job.status = "running"
        self._store.save(job)
        try:
            job.result = work()
            job.status = "succeeded"
        except AI4BIError as exc:
            LOGGER.warning("Job %s failed: %s", job.job_id, exc)
            job.status, job.error = "failed", str(exc)
        except Exception:  # noqa: BLE001 - a worker thread must record every failure, not die with it
            LOGGER.exception("Job %s crashed", job.job_id)
            job.status, job.error = "failed", "The job failed because of an internal error."
        self._store.save(job)
