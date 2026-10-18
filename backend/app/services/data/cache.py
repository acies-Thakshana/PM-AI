"""Versioned in-process cache of loaded and prepared datasets.

Reading, coercing and profiling a large table on every question would dominate the response time.
Each cached entry remembers the data version token it was built from. An entry is trusted for
``ttl_seconds`` without asking the source anything; after that one cheap ``version`` call decides
whether it is still current. Cached frames are shared by all requests and must be treated as
read-only. At most ``max_entries`` datasets are kept, least recently used first out.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

import pandas as pd

from app.services.data.preprocessing import drop_restricted, prepare_frames
from app.services.data.source import DatasetSource
from app.services.sql.grounding import ColumnProfile, profile_frame


@dataclass(frozen=True)
class PreparedData:
    """What the question pipeline runs on: SQL-ready tables without restricted columns."""

    tables: dict[str, pd.DataFrame]
    profiles: dict[str, list[ColumnProfile]]


@dataclass
class _Entry:
    version: str
    checked_at: float
    raw: dict[str, pd.DataFrame]
    prepared: dict[frozenset[str], PreparedData] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


class DataCache:
    def __init__(self, source: DatasetSource, *, ttl_seconds: int, max_entries: int) -> None:
        self._source = source
        self._ttl = ttl_seconds
        self._max_entries = max(1, max_entries)
        self._entries: OrderedDict[tuple[str, tuple[str, ...]], _Entry] = OrderedDict()
        self._lock = threading.Lock()
        self._load_locks: dict[tuple[str, tuple[str, ...]], threading.Lock] = {}

    def raw(self, domain: str, table_names: list[str]) -> dict[str, pd.DataFrame]:
        """The tables exactly as stored."""
        return self._entry(domain, table_names).raw

    def prepared(self, domain: str, table_names: list[str], restricted: set[str]) -> PreparedData:
        """SQL-ready tables with the restricted columns removed, plus their column profiles."""
        entry = self._entry(domain, table_names)
        key = frozenset(name.lower() for name in restricted)
        with entry.lock:
            data = entry.prepared.get(key)
            if data is None:
                tables = drop_restricted(prepare_frames(entry.raw), restricted)
                data = PreparedData(tables, {name: profile_frame(frame) for name, frame in tables.items()})
                entry.prepared[key] = data
            return data

    def invalidate(self, domain: str) -> None:
        """Forget everything cached for a domain, for example right after an upload."""
        with self._lock:
            for key in [k for k in self._entries if k[0] == domain]:
                del self._entries[key]

    def _entry(self, domain: str, table_names: list[str]) -> _Entry:
        key = (domain, tuple(sorted(table_names)))
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and now - entry.checked_at < self._ttl:
                self._entries.move_to_end(key)
                return entry
            load_lock = self._load_locks.setdefault(key, threading.Lock())

        with load_lock:  # one loader per dataset; late arrivals reuse its result
            version = self._source.version(domain)
            with self._lock:
                entry = self._entries.get(key)
                if entry is not None and entry.version == version:
                    entry.checked_at = time.monotonic()
                    self._entries.move_to_end(key)
                    return entry
            raw = self._source.load(domain, list(key[1]))
            entry = _Entry(version=version, checked_at=time.monotonic(), raw=raw)
            with self._lock:
                self._entries[key] = entry
                self._entries.move_to_end(key)
                while len(self._entries) > self._max_entries:
                    evicted, _ = self._entries.popitem(last=False)
                    self._load_locks.pop(evicted, None)
            return entry
