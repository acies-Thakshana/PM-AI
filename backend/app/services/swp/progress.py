"""How far a slow SWP operation has got, as "API calls done / expected", so the page can show 3/103.

The page makes up an id, sends it with the request (the request itself runs as a background job), and
asks `GET /api/swp/progress/<id>` every second or so while it waits. The client reports each finished
call here through a context variable, so the API code needs no extra arguments.
"""
from __future__ import annotations

import contextvars
import threading
import time
from dataclasses import dataclass, field

_MAX_AGE_SECONDS = 3600


@dataclass
class Progress:
    done: int = 0
    total: int = 0
    label: str = ""
    finished: bool = False
    touched: float = field(default_factory=time.time)

    def add_total(self, n: int) -> None:
        self.total += n
        self.touched = time.time()

    def tick(self, label: str | None = None) -> None:
        self.done += 1
        self.total = max(self.total, self.done)
        if label:
            self.label = label
        self.touched = time.time()


_lock = threading.Lock()
_registry: dict[str, Progress] = {}
current: contextvars.ContextVar[Progress | None] = contextvars.ContextVar("swp_progress", default=None)


def start(progress_id: str | None, total: int = 0, label: str = "") -> Progress | None:
    """Begin tracking under `progress_id` (None = not tracked) and make it the current operation."""
    if not progress_id:
        return None
    progress = Progress(total=total, label=label)
    with _lock:
        cutoff = time.time() - _MAX_AGE_SECONDS
        for key in [k for k, v in _registry.items() if v.touched < cutoff]:
            del _registry[key]
        _registry[progress_id[:64]] = progress
    current.set(progress)
    return progress


def get(progress_id: str) -> Progress | None:
    with _lock:
        return _registry.get(progress_id[:64])


def tick(label: str | None = None) -> None:
    progress = current.get()
    if progress is not None:
        progress.tick(label)


def add_total(n: int) -> None:
    progress = current.get()
    if progress is not None:
        progress.add_total(n)


def finish() -> None:
    progress = current.get()
    if progress is not None:
        progress.finished = True
        progress.touched = time.time()
