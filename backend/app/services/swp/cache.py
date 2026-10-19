"""A small on-disk cache of what the SWP API returned, so the same program's data is not fetched again.

  * the list of all trips of a program (one file per program), reused until someone asks to refresh it;
  * the basic + detail JSON of an ARRIVED trip (one file per trip) -- an arrived trip no longer changes, so it
    is never fetched twice. Trips in any other status always come from the API;
  * the program's product table (names and temperature limits).

Edits made in the app are never stored here: they are laid over the raw API data on every load.
Files live under data/swp_cache/ (gitignored) as JSON; a file that cannot be read is treated as missing.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path

from app import config

log = logging.getLogger(__name__)

_DIR = config.DATA_DIR / "swp_cache"
_lock = threading.Lock()
_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def _path(program_id: str, *parts: str) -> Path:
    return _DIR.joinpath(_SAFE.sub("_", program_id or "default"), *(_SAFE.sub("_", p) for p in parts))


def _read(path: Path):
    try:
        with _lock:
            return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except Exception as exc:  # noqa: BLE001 - a bad cache file is just a miss
        log.warning("could not read cache file %s: %s", path, exc)
        return None


def _write(path: Path, data) -> None:
    try:
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - caching must never fail a request
        log.warning("could not write cache file %s: %s", path, exc)


def enabled() -> bool:
    return config.SWP_CACHE


def load_trips(program_id: str) -> dict | None:
    """{"at": epoch seconds, "trips": [...]} or None."""
    return _read(_path(program_id, "trips.json")) if enabled() else None


def save_trips(program_id: str, trips: list[dict]) -> float:
    at = time.time()
    if enabled():
        _write(_path(program_id, "trips.json"), {"at": at, "trips": trips})
    return at


def load_trip(program_id: str, trip_id: str) -> dict | None:
    """{"basic": ..., "detail": ...} of an arrived trip, or None."""
    return _read(_path(program_id, "trips", f"{trip_id}.json")) if enabled() else None


def save_trip(program_id: str, trip_id: str, basic: dict, detail: dict) -> None:
    if enabled():
        _write(_path(program_id, "trips", f"{trip_id}.json"), {"basic": basic, "detail": detail})


def load_products(program_id: str) -> dict | None:
    return _read(_path(program_id, "products.json")) if enabled() else None


def save_products(program_id: str, products: dict) -> None:
    if enabled():
        _write(_path(program_id, "products.json"), products)
