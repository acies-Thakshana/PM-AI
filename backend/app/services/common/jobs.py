"""Background jobs, so that a slow AI step never has to fit inside one HTTP request.

An API Gateway / load balancer gives up on a request after ~30 seconds, but the AI steps (planning,
computing features, running an analysis, building a report) can take longer. With the header
`X-Run-As-Job: 1` an endpoint (see routers/job_route.py) starts its normal work in a thread of this
pool and answers at once with 202 and a job id. The page then asks `GET /api/jobs/<id>` until the job
is done and reads the endpoint's real response -- same status, headers and body it would have sent --
from `GET /api/jobs/<id>/result`.

Jobs live in this process's memory (like the DataFrames they work on): a restart loses a running job and
the status call then says so. A finished job is kept for KEEP_SECONDS, at most MAX_JOBS of them.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

MAX_WORKERS = 8
KEEP_SECONDS = 30 * 60
MAX_JOBS = 200

_pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="job")
_lock = threading.Lock()


@dataclass
class StoredResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


@dataclass
class Job:
    id: str
    path: str
    created: float = field(default_factory=time.time)
    finished: float | None = None
    owner: str | None = None  # the user whose request it was (known once sign-in has run)
    result: StoredResponse | None = None

    @property
    def status(self) -> str:
        return "done" if self.result is not None else "running"


_jobs: dict[str, Job] = {}


def _cleanup(now: float) -> None:
    for job_id in [j.id for j in _jobs.values() if j.finished and now - j.finished > KEEP_SECONDS]:
        del _jobs[job_id]
    while len(_jobs) > MAX_JOBS:  # oldest first (dict order = creation order)
        del _jobs[next(iter(_jobs))]


def start(path: str, work: Callable[[], Awaitable[tuple[StoredResponse, str | None]]]) -> Job:
    """Run `work` (a coroutine function returning (response, owner)) in the pool; returns the job at once."""
    job = Job(id=uuid.uuid4().hex, path=path)
    with _lock:
        _cleanup(time.time())
        _jobs[job.id] = job

    def run() -> None:
        owner = None
        try:
            response, owner = asyncio.run(work())
        except BaseException:  # noqa: BLE001 - a job must always end in an answer
            log.exception("job %s (%s) crashed", job.id, path)
            response = StoredResponse(
                500, {"content-type": "application/json"}, b'{"detail":"Internal Server Error"}'
            )
        job.owner = owner
        job.finished = time.time()
        job.result = response  # last: this is what flips the status to "done"

    _pool.submit(run)
    return job


def get(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)
