"""One JSON document per session holding every feature (`FEATURES`) or every analysis (`ANALYSES`).

  {"feature_count": 9, "by_source": {"predefined": 3, "planner": 1, "custom": 1, "ai_suggested": 4},
   "updated_at": "...", "features": [ {entry}, {entry}, ... ]}

Each entry is the feature/analysis as the app knows it (id, name, formula, status ...) plus:

  source     where it came from -- the "column" that tells them apart:
               predefined    the uploaded KPI / Analysis profile
               planner       a Planner recommendation the PM accepted
               custom        defined by the user (typed in, or a drill-down the PM started)
               ai_suggested  proposed by the AI suggestion agent
             `status` marks what happened to it: pending / approved / rejected, so the accepted
             AI suggestions are the `ai_suggested` entries whose status is `approved`.
  cache      the final working code (and plan / chart / template) once it has been computed
  persisted  true for what only this document knows (custom, ai_suggested, drilldown);
             false for a snapshot of a predefined / planner entry, which the app re-derives from
             the profile / the PLAN# documents on every read. The snapshots are refreshed whenever
             the document is written, so the JSON shows the whole set at that moment.
  created_at keeps the creation order of the persisted entries.

Every change is an atomic read-modify-write of the one document (doc_store.update), so two
requests changing different entries never overwrite each other.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from app.services.common import doc_store

INTERNAL_KEYS = ("cache", "persisted", "created_at", "snapshot_at")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def public(entry: dict) -> dict:
    """The entry as the rest of the app knows it (without this module's bookkeeping keys)."""
    return {k: v for k, v in entry.items() if k not in INTERNAL_KEYS}


def _merge_derived(items: list[dict], derived: list[dict]) -> list[dict]:
    """Replace the snapshots of predefined / planner entries with the current ones, keeping the
    code already cached for entries that still exist."""
    old = {e["id"]: e for e in items if not e.get("persisted")}
    now = _now()
    fresh = []
    for d in derived:
        before = old.get(d["id"], {})
        snap = {**d, "persisted": False, "created_at": before.get("created_at") or now, "snapshot_at": now}
        if before.get("cache"):
            snap["cache"] = before["cache"]
        fresh.append(snap)
    return fresh + [e for e in items if e.get("persisted")]


def _update(session_id: str, doc: str, key: str, count_key: str, fn: Callable[[list[dict]], None], derived: list[dict] | None) -> dict:
    def wrapper(current: Any) -> dict:
        data = current if isinstance(current, dict) else {}
        items = list(data.get(key) or [])
        fn(items)
        if derived is not None:
            items = _merge_derived(items, derived)
        by_source: dict[str, int] = {}
        for e in items:
            by_source[e.get("source", "other")] = by_source.get(e.get("source", "other"), 0) + 1
        return {count_key: len(items), "by_source": by_source, "updated_at": _now(), key: items}

    return doc_store.update(session_id, doc, wrapper)


class EntryDoc:
    """Reads and writes one kind of entry document (features or analyses)."""

    def __init__(self, doc: str, key: str, count_key: str, persisted_sources: set[str]):
        self.doc = doc
        self.key = key
        self.count_key = count_key
        self.persisted_sources = persisted_sources

    # ---- reads --------------------------------------------------------------------------------
    def _items(self, session_id: str) -> list[dict]:
        data = doc_store.get(session_id, self.doc)
        return list(data.get(self.key) or []) if isinstance(data, dict) else []

    def load_persisted(self, session_id: str) -> list[dict]:
        """The entries only this document knows (custom / ai_suggested / drilldown), oldest first."""
        rows = [e for e in self._items(session_id) if e.get("persisted") and e.get("source") in self.persisted_sources]
        rows.sort(key=lambda e: (e.get("created_at", ""), e.get("id", "")))
        return [public(e) for e in rows]

    def get_cache(self, session_id: str, entry_id: str) -> dict | None:
        found = next((e for e in self._items(session_id) if e.get("id") == entry_id), None)
        return (found or {}).get("cache") or None

    # ---- writes -------------------------------------------------------------------------------
    def add(self, session_id: str, entries: list[dict], derived: list[dict] | None = None) -> None:
        """Append new persisted entries (and refresh the predefined / planner snapshots)."""
        now = _now()

        def fn(items: list[dict]) -> None:
            for n, entry in enumerate(entries):
                items[:] = [e for e in items if e.get("id") != entry["id"]]
                # "#nnn" keeps the order of entries added in one call (they share the timestamp)
                items.append({**entry, "persisted": True, "created_at": f"{now}#{n:03d}"})

        _update(session_id, self.doc, self.key, self.count_key, fn, derived)

    def update_persisted(self, session_id: str, entry_id: str, fields: dict, derived: list[dict] | None = None) -> dict | None:
        """Merge `fields` into one persisted entry; None if there is no such entry."""
        found: dict = {}

        def fn(items: list[dict]) -> None:
            found.clear()
            for e in items:
                if e.get("id") == entry_id and e.get("persisted"):
                    e.update(fields)
                    found.update(public(e))

        _update(session_id, self.doc, self.key, self.count_key, fn, derived)
        return dict(found) or None

    def sync(self, session_id: str, derived: list[dict]) -> None:
        """Refresh the predefined / planner snapshots (e.g. after the PM saved planner decisions)."""
        _update(session_id, self.doc, self.key, self.count_key, lambda items: None, derived)

    def set_cache(self, session_id: str, entry: dict, cache: dict) -> None:
        """Store the final code of one entry inside its own record. An entry the document does not
        hold yet (a predefined / planner one computed before any snapshot) gets a snapshot."""

        def fn(items: list[dict]) -> None:
            for e in items:
                if e.get("id") == entry["id"]:
                    e["cache"] = cache
                    return
            items.append({**public(entry), "persisted": False, "created_at": _now(), "snapshot_at": _now(), "cache": cache})

        _update(session_id, self.doc, self.key, self.count_key, fn, None)

    def drop_cache(self, session_id: str, entry_id: str) -> None:
        """Forget the cached code of one entry. A snapshot with no code has no purpose, so it goes too."""
        if not any(e.get("id") == entry_id for e in self._items(session_id)):
            return

        def fn(items: list[dict]) -> None:
            for e in list(items):
                if e.get("id") == entry_id:
                    e.pop("cache", None)
                    if not e.get("persisted"):
                        items.remove(e)

        _update(session_id, self.doc, self.key, self.count_key, fn, None)


FEATURES = EntryDoc("FEATURES", "features", "feature_count", {"custom", "ai_suggested"})
ANALYSES = EntryDoc("ANALYSES", "analyses", "analysis_count", {"custom", "ai_suggested", "drilldown"})
