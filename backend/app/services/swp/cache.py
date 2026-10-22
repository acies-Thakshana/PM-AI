"""The SWP data store: what the API returned, kept on disk per program (data/swp_cache/<program>/, gitignored).

  * trips.json              the list of all trips of the program, reused until someone asks to refresh it;
  * trips/<trip guid>.json  the RAW payload of each trip -- {tripID, record, basic, detail}, exactly as the API
                            returned it (the detail carries the sensor readings and the GPS route). This is the source
                            of truth: the aggregate is rebuilt from these files, the API is not asked again;
  * Tabular Shipment Data.xlsx   the aggregate of all stored trips, in the SensiWatch export's columns, written
                            whenever the program is synced.

A stored trip is reused while it is still current: an arrived trip never changes, any other trip is current while its
`lastUpdatedDate` in the trip list is the one stored. Edits made in the app are never stored here.
A file that cannot be read is treated as missing; SWP_CACHE=0 turns the store off.
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
_memory: dict[tuple[str, str], dict] = {}   # payloads, when the on-disk store is switched off (SWP_CACHE=0)
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
    """The raw payload {tripID, record, basic, detail} stored for a trip, or None."""
    if not enabled():
        return _memory.get((program_id, trip_id))
    return _read(_path(program_id, "trips", f"{trip_id}.json"))


def save_trip(program_id: str, trip_id: str, payload: dict) -> None:
    if enabled():
        _write(_path(program_id, "trips", f"{trip_id}.json"), payload)
    else:
        _memory[(program_id, trip_id)] = payload


def aggregate_path(program_id: str) -> Path:
    return _path(program_id).with_name(_SAFE.sub("_", program_id or "default")) / "Tabular Shipment Data.xlsx"


def write_bytes(path: Path, data: bytes) -> None:
    """Write a derived file (the aggregate Excel); like everything here, a failure is logged, not raised."""
    if not enabled():
        return
    try:
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    except Exception as exc:  # noqa: BLE001
        log.warning("could not write %s: %s", path, exc)
