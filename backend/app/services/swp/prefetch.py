"""Fetch the trip details (call 4) in the background, so they are ready by the time they are needed.

The Configure page shows the trip list as soon as the search (call 2) is back. At the same moment the page asks for the
trips that will be analysed (the arrived ones) to be fetched here. Worker threads, one per subscription key, fetch their
detail one call at a time (the key pool in client.py keeps 3 s between calls on a key) and put each answer in the store
(cache.py). Loading the trips into the audit waits for any that are still outstanding, so everything is complete before
the Audit page.

A trip already in the store and still current is not fetched again (see preprocess.stored_payloads). Asking again for ids
already queued, running or done is harmless, which is what lets the page simply re-send its list to read the progress.
"""
from __future__ import annotations

import collections
import logging
import threading
import time

from app.services.swp import cache, client, preprocess

log = logging.getLogger(__name__)

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"


class _Program:
    def __init__(self):
        self.lock = threading.Lock()
        self.queue: collections.deque[str] = collections.deque()
        self.records: dict[str, dict] = {}
        self.state: dict[str, str] = {}
        self.stamp: dict[str, str | None] = {}     # lastUpdatedDate each done trip was fetched at
        self.errors: dict[str, str] = {}
        self.workers = 0


_programs: dict[str, _Program] = {}
_registry_lock = threading.Lock()


def _program(program: str) -> _Program:
    with _registry_lock:
        return _programs.setdefault(program, _Program())


def _worker(program: str, job: _Program) -> None:
    while True:
        with job.lock:
            if not job.queue:
                job.workers -= 1   # leaving is decided under the same lock that submit() uses to count workers
                return
            trip_id = job.queue.popleft()
            job.state[trip_id] = RUNNING
            record = job.records[trip_id]
        try:
            detail = client.get_trip_detail(client.get_token(), trip_id, program)
            cache.save_trip(program, trip_id, {"tripID": trip_id, "record": record, "basic": {}, "detail": detail})
            with job.lock:
                job.state[trip_id] = DONE
                job.stamp[trip_id] = record.get("lastUpdatedDate")
                job.errors.pop(trip_id, None)
        except Exception as exc:  # noqa: BLE001 - one trip failing must not stop the others
            log.warning("prefetch of trip %s failed: %s", trip_id, exc)
            with job.lock:
                job.state[trip_id] = FAILED
                job.errors[trip_id] = str(exc)[:300]


def _start_workers(program: str, job: _Program) -> None:
    with job.lock:
        wanted = min(client.key_count(), len(job.queue)) - job.workers
        job.workers += max(wanted, 0)
    for _ in range(max(wanted, 0)):
        threading.Thread(target=_worker, args=(program, job), daemon=True, name=f"swp-prefetch-{program}").start()


def submit(program: str, ids: list[str], records: dict[str, dict]) -> dict:
    """Queue the trips whose detail is not in the store yet (or has changed), start the workers, and return the status of `ids`."""
    job = _program(program)
    current = preprocess.stored_payloads(program, [i for i in ids if i in records], records)
    with job.lock:
        for trip_id in ids:
            record = records.get(trip_id)
            if record is None:
                continue
            job.records[trip_id] = record
            state = job.state.get(trip_id)
            if trip_id in current:
                job.state[trip_id], job.stamp[trip_id] = DONE, record.get("lastUpdatedDate")
            elif state in (QUEUED, RUNNING):
                continue
            elif state == DONE and job.stamp.get(trip_id) == record.get("lastUpdatedDate") and cache.load_trip(program, trip_id):
                continue
            else:  # new, failed before, or changed since it was fetched
                job.state[trip_id] = QUEUED
                job.queue.append(trip_id)
    _start_workers(program, job)
    return status(program, ids)


def status(program: str, ids: list[str]) -> dict:
    job = _program(program)
    with job.lock:
        states = [job.state.get(i) for i in ids]
        errors = [job.errors[i] for i in ids if i in job.errors]
    done = sum(1 for s in states if s == DONE)
    failed = sum(1 for s in states if s == FAILED)
    return {
        "total": len(ids), "done": done, "failed": failed,
        "running": any(s in (QUEUED, RUNNING) for s in states),
        "error": errors[0] if errors else None,
        "seconds_per_trip": client_gap(),
    }


def client_gap() -> float:
    """Roughly how many seconds each outstanding trip takes: the gap between calls divided over the keys."""
    from app import config

    return round(config.SWP_CALL_GAP_SECONDS / client.key_count(), 2)


def wait(program: str, ids: list[str], on_progress=None, timeout: float = 3600.0) -> None:
    """Block until every id is done; raise SwpError if some failed (even after the workers have tried)."""
    deadline = time.monotonic() + timeout
    while True:
        s = status(program, ids)
        if on_progress:
            on_progress(s["done"], s["total"])
        if not s["running"]:
            if s["failed"]:
                raise client.SwpError(f"{s['failed']} trip detail call(s) failed: {s['error']}")
            return
        if time.monotonic() > deadline:
            raise client.SwpError("Fetching the trip details took too long.")
        time.sleep(0.4)
