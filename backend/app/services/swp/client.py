"""Thin client for the SWP (SensiWatch) external API. All secrets come from app.config (env vars).

Pacing: the API allows 20 trip calls a minute PER SUBSCRIPTION KEY. Every trip call goes through a small pool of keys
(SWP_TRIP_KEY and, if set, SWP_TRIP_KEY_2); a call takes the key that is free soonest and calls on one key start at least
SWP_CALL_GAP_SECONDS (3 s) apart. With two keys two calls can be in flight at once, so the pace doubles. Threads may call
freely: the pool decides when each call may start.
"""
from __future__ import annotations

import contextvars
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from app import config
from app.services.swp import cache, progress

log = logging.getLogger(__name__)

STATUS_GUIDS = {
    "draft": "49D3D04D-7F14-47EA-B373-EC73C4ADE9E4",
    "notstarted": "72978F22-E368-4779-86B6-239EAD53BC2E",
    "intransit": "93D4E91C-703D-4C50-AFB3-39C1FA841EB0",
    "arrived": "6B611752-BDC9-4ECF-8F3B-EE2D55F4BA30",
    "disabled": "9E016692-F9BA-404A-9C3F-3309D9E48C0D",
    "started": "AFC537F9-D5F0-4470-9929-7BA87193D6A9",
}
GUID_NAMES = {v.upper(): k for k, v in STATUS_GUIDS.items()}
# Display names, in the order a trip moves through them.
STATUS_LABELS = {
    "draft": "Draft", "notstarted": "NotStarted", "started": "Started",
    "intransit": "InTransit", "arrived": "Arrived", "disabled": "Disabled",
}
# An empty search returns nothing, so "all trips" is the union of one search per status.
ALL_STATUS_KEYWORDS = ["NotStarted", "Started", "InTransit", "Arrived", "Draft", "Disabled"]

_REQUIRED = ("SWP_BASE_URL", "SWP_SECURITY_KEY", "SWP_TRIP_KEY", "SWP_USER", "SWP_PASS")
_RATE_LIMIT_WAIT_SECONDS = 65   # a key that got HTTP 429 / 403 rests this long (the window is 60 s)


class SwpError(Exception):
    """The SWP API is not configured, or it refused / failed a call."""


def missing_settings(program_id: str | None = None) -> list[str]:
    missing = [name for name in _REQUIRED if not getattr(config, name)]
    if not (program_id or config.SWP_PROGRAM_ID):
        missing.append("SWP_PROGRAM_ID")
    return missing


def _program(program_id: str | None) -> str:
    return (program_id or config.SWP_PROGRAM_ID).strip()


# ---- the pool of trip keys ----------------------------------------------------------------------------------------

class _Pacer:
    def __init__(self, key: str):
        self.key = key
        self.next_at = 0.0   # time.monotonic() before which this key may not start another call


_pool_lock = threading.Lock()
_pacers: list[_Pacer] = []


def trip_keys() -> list[str]:
    return [k for k in (config.SWP_TRIP_KEY, config.SWP_TRIP_KEY_2) if k]


def key_count() -> int:
    return max(len(trip_keys()), 1)


def _reserve() -> _Pacer:
    """The key that is free soonest. Its next free time moves one gap on, so calls on one key start >= the gap apart;
    the caller sleeps until its own slot."""
    with _pool_lock:
        keys = trip_keys()
        if [p.key for p in _pacers] != keys:
            _pacers[:] = [_Pacer(k) for k in keys]
        pacer = min(_pacers, key=lambda p: p.next_at)
        start = max(time.monotonic(), pacer.next_at)
        pacer.next_at = start + config.SWP_CALL_GAP_SECONDS
    wait = start - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    return pacer


def _rest(pacer: _Pacer) -> None:
    with _pool_lock:
        pacer.next_at = max(pacer.next_at, time.monotonic() + _RATE_LIMIT_WAIT_SECONDS)


def _send(method: str, path: str, key: str, token: str | None, **kwargs) -> requests.Response:
    headers = {"Ocp-Apim-Subscription-Key": key}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        return requests.request(method, config.SWP_BASE_URL + path, headers=headers, timeout=120, **kwargs)
    except requests.RequestException as exc:
        raise SwpError(f"Could not reach the SWP API: {exc}") from exc


def _checked(response: requests.Response, method: str, path: str) -> dict:
    if response.status_code != 200:
        raise SwpError(f"SWP API {method} {path.split('?')[0]} failed ({response.status_code}): {response.text[:300]}")
    return response.json()


def _trip_call(method: str, path: str, token: str, **kwargs) -> dict:
    """A trip call on whichever key is free; if a key is told to slow down it rests and the call goes to the next free one."""
    missing = missing_settings()
    if missing:
        raise SwpError("The SWP API is not configured. Set in backend/.env: " + ", ".join(missing))
    for attempt in range(4):
        pacer = _reserve()
        response = _send(method, path, pacer.key, token, **kwargs)
        log.info("SWP %s %s -> %s (key %d)", method, path.split("?")[0], response.status_code, trip_keys().index(pacer.key) + 1)
        progress.tick()
        if response.status_code in (429, 403) and attempt < 3:
            log.warning("SWP rate limit on a key; resting it for %s s", _RATE_LIMIT_WAIT_SECONDS)
            _rest(pacer)
            continue
        return _checked(response, method, path)
    raise SwpError("unreachable")


# ---- the login token ------------------------------------------------------------------------------------------------
_token: dict = {"value": None, "expires": 0.0}
_token_lock = threading.Lock()


def has_token() -> bool:
    return bool(_token["value"]) and time.time() < _token["expires"]


def get_token() -> str:
    """A bearer token, reused until shortly before it expires (shared by every thread)."""
    with _token_lock:
        if _token["value"] and time.time() < _token["expires"]:
            return _token["value"]
        missing = missing_settings()
        if missing:
            raise SwpError("The SWP API is not configured. Set in backend/.env: " + ", ".join(missing))
        path = "/api/security-external/external/auth/connect/token"
        response = _send(
            "POST", path, config.SWP_SECURITY_KEY, None,
            data={"grant_type": "password", "client_id": config.SWP_CLIENT_ID,
                  "client_secret": config.SWP_CLIENT_SECRET, "scope": "rtweb.api offline_access",
                  "username": config.SWP_USER, "password": config.SWP_PASS},
        )
        progress.tick()
        data = _checked(response, "POST", path)
        _token["value"] = data["access_token"]
        _token["expires"] = time.time() + max(int(data.get("expires_in") or 3600) - 120, 60)
        return _token["value"]


# ---- the calls -----------------------------------------------------------------------------------------------------

def search_trips(token: str, keyword: str, program_id: str | None = None) -> list[dict]:
    """Call 2: all trips matching a keyword (page through the results, 50 a page)."""
    trips: list[dict] = []
    page = 0
    while True:
        data = _trip_call(
            "POST", f"/api/trip/external/ExternalTrip/tripsearch/programId/{_program(program_id)}", token,
            json={"keyword": keyword, "from": page},
        )
        records = data.get("records") or []
        trips += records
        if page == 0 and records:
            # Now the number of pages is known (50 records a page): the calls still to come count toward the total.
            progress.add_total(max(-(-int(data.get("overallTotal") or 0) // 50) - 1, 0))
        if not records or len(trips) >= data.get("overallTotal", 0):
            return trips
        page += 1


def get_trip_detail(token: str, trip_id: str, program_id: str | None = None) -> dict:
    """Call 4: one trip in full, with its sensor readings and GPS route."""
    return _trip_call(
        "GET", f"/api/trip/external/ExternalTripDetail/programId/{_program(program_id)}/tripId/{trip_id}", token,
    )


# ---- the list of all trips, fetched once and reused ------------------------------------------
_trips_cache: dict[str, dict] = {}   # program id -> {"at": time, "trips": [...]}
_trips_lock = threading.Lock()


def status_name(record: dict) -> str:
    """The trip's status as text: the API's own text when it has one, else the GUID's name."""
    text = str(record.get("tripStatus") or "").replace(" ", "")
    if text:
        return STATUS_LABELS.get(text.lower(), text)
    key = GUID_NAMES.get(str(record.get("tripStatusGuid") or "").upper())
    return STATUS_LABELS.get(key, "Unknown") if key else "Unknown"


def all_trips(program_id: str | None = None, refresh: bool = False) -> list[dict]:
    """Every trip in the program (de-duplicated across the per-status searches)."""
    return all_trips_info(program_id, refresh)[0]


def all_trips_info(program_id: str | None = None, refresh: bool = False) -> tuple[list[dict], float, bool]:
    """(trips, when they were fetched as epoch seconds, whether that was an earlier fetch). The list is kept on
    disk and reused until `refresh`; this process also remembers it for SWP_TRIPS_CACHE_SECONDS. A fresh fetch
    searches the statuses on one thread per key, so two keys search at the same time."""
    program = _program(program_id)
    with _trips_lock:
        cached = _trips_cache.get(program)
        if cached and not refresh and time.time() - cached["at"] < config.SWP_TRIPS_CACHE_SECONDS:
            return cached["trips"], cached["at"], True
        stored = None if refresh else cache.load_trips(program)
        if stored and stored.get("trips"):
            _trips_cache[program] = {"at": stored["at"], "trips": stored["trips"]}
            return stored["trips"], stored["at"], True
        progress.add_total(len(ALL_STATUS_KEYWORDS) + (0 if has_token() else 1))  # one page per status to start with
        token = get_token()
        by_id: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=key_count()) as pool:
            # each task runs in its own copy of the context so the progress counter reaches the threads
            futures = [pool.submit(contextvars.copy_context().run, search_trips, token, kw, program) for kw in ALL_STATUS_KEYWORDS]
            for future in futures:
                for t in future.result():
                    by_id[t["tripID"]] = t
        trips = list(by_id.values())
        at = cache.save_trips(program, trips)
        _trips_cache[program] = {"at": at, "trips": trips}
        return trips, at, False


def _flat(obj, prefix: str = "") -> dict:
    out: dict = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flat(v, f"{prefix}{k}."))
    elif isinstance(obj, list):
        if obj:
            out.update(_flat(obj[0], prefix))
    else:
        out[prefix.rstrip(".")] = obj
    return out


def _find_time(record: dict, needle: str) -> str | None:
    """The first text value whose field name contains `needle` ("depart" / "arriv"), preferring
    actual times over estimated, planned or scheduled ones. The list record's exact field names are not
    documented, so this looks for them by name."""
    hits = [(k, v) for k, v in _flat(record).items() if needle in k.lower() and isinstance(v, str) and v[:2] == "20"]
    soft = ("estimat", "plan", "schedul", "eta", "expect")
    hits.sort(key=lambda kv: (any(s in kv[0].lower() for s in soft), "actual" not in kv[0].lower()))
    return hits[0][1] if hits else None


def departure_of(record: dict) -> str | None:
    return _find_time(record, "depart")


def arrival_of(record: dict) -> str | None:
    return _find_time(record, "arriv")


def record_fields(record: dict) -> list[str]:
    return sorted(_flat(record))


# ---- write-back (NOT ENABLED) ------------------------------------------------------------------
# Changing a trip's status or its departure / arrival time is done in the UI only for now. When it is
# time to send it to SWP, the guide ("Create / Update Trip", Trip Manage API for External) says: search
# for the trip first, then call UpdateTrip with the trip's TripID GUID and a body holding only the
# fields to change (the rest can stay as returned by the search). The exact URL, verb (PUT or PATCH)
# and body field names are in the developer portal under trip-api-external-manage > UpdateTrip -- they
# are NOT in the guide, so confirm them there before enabling this. Needs a Trip Manage subscription
# key and is limited to 20 calls a minute.
#
# def update_trip(token: str, record: dict, changes: dict, program_id: str | None = None) -> dict:
#     body = {**record, **changes}    # the search record, with only what changes replaced, e.g.
#                                     # {"tripStatusGuid": STATUS_GUIDS["arrived"], "tripActualArrivalTime": "2026-10-12T09:32:00Z"}
#     return _trip_call("PUT", f"/api/trip-manage/external/ExternalTrip/programId/{_program(program_id)}", token, json=body)
#     # URL, verb and the Trip Manage key (it is a different subscription than the trip key): confirm in the portal
