"""Thin client for the SWP (SensiWatch) external API. All secrets come from app.config (env vars)."""
from __future__ import annotations

import logging
import threading
import time

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


class SwpError(Exception):
    """The SWP API is not configured, or it refused / failed a call."""


def missing_settings(program_id: str | None = None) -> list[str]:
    missing = [name for name in _REQUIRED if not getattr(config, name)]
    if not (program_id or config.SWP_PROGRAM_ID):
        missing.append("SWP_PROGRAM_ID")
    return missing


def _program(program_id: str | None) -> str:
    return (program_id or config.SWP_PROGRAM_ID).strip()


_lock = threading.Lock()          # one call at a time keeps us under the 20 calls/min limit
_RATE_LIMIT_RETRIES = 3


def _retry_after(response) -> float:
    """Seconds the API asks us to wait after a 429 (default 20)."""
    try:
        return min(max(float(response.headers.get("Retry-After", 20)), 1.0), 60.0)
    except (TypeError, ValueError):
        return 20.0

_token: dict = {"value": None, "expires": 0.0}


def _call(method: str, path: str, key: str, token: str | None = None, **kwargs) -> dict:
    missing = missing_settings()
    if missing:
        raise SwpError("The SWP API is not configured. Set in backend/.env: " + ", ".join(missing))
    headers = {"Ocp-Apim-Subscription-Key": key}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with _lock:
        for attempt in range(_RATE_LIMIT_RETRIES + 1):
            started = time.monotonic()
            try:
                r = requests.request(method, config.SWP_BASE_URL + path, headers=headers, timeout=60, **kwargs)
            except requests.RequestException as exc:
                raise SwpError(f"Could not reach the SWP API: {exc}") from exc
            log.info("SWP %s %s -> %s", method, path.split("?")[0], r.status_code)
            # The limit is calls per minute, so the gap runs from the START of one call to the start of the next:
            # the time the call itself took already counts toward it.
            pause = max(config.SWP_CALL_DELAY_SECONDS - (time.monotonic() - started), 0)
            if r.status_code == 429 and attempt < _RATE_LIMIT_RETRIES:
                # Too many calls: wait out the window (the API's own hint when it gives one) and ask again.
                pause = max(pause, _retry_after(r))
                log.warning("SWP rate limit hit; waiting %.0fs", pause)
                time.sleep(pause)
                continue
            progress.tick()
            time.sleep(pause)
            break
    if r.status_code != 200:
        raise SwpError(f"SWP API {method} {path.split('?')[0]} failed ({r.status_code}): {r.text[:300]}")
    return r.json()


def has_token() -> bool:
    return bool(_token["value"]) and time.time() < _token["expires"]


def get_token() -> str:
    """A bearer token, reused until shortly before it expires."""
    if _token["value"] and time.time() < _token["expires"]:
        return _token["value"]
    data = _call(
        "POST", "/api/security-external/external/auth/connect/token", config.SWP_SECURITY_KEY,
        data={"grant_type": "password", "client_id": config.SWP_CLIENT_ID,
              "client_secret": config.SWP_CLIENT_SECRET, "scope": "rtweb.api offline_access",
              "username": config.SWP_USER, "password": config.SWP_PASS},
    )
    _token["value"] = data["access_token"]
    _token["expires"] = time.time() + max(int(data.get("expires_in") or 3600) - 120, 60)
    return _token["value"]


def search_trips(token: str, keyword: str, program_id: str | None = None) -> list[dict]:
    """All trips matching a keyword (page through the results)."""
    trips: list[dict] = []
    page = 0
    while True:
        data = _call(
            "POST", f"/api/trip/external/ExternalTrip/tripsearch/programId/{_program(program_id)}",
            config.SWP_TRIP_KEY, token, json={"keyword": keyword, "from": page},
        )
        records = data.get("records") or []
        trips += records
        if page == 0 and records:
            # Now the number of pages is known (50 records a page): the calls still to come count toward the total.
            progress.add_total(max(-(-int(data.get("overallTotal") or 0) // 50) - 1, 0))
        if not records or len(trips) >= data.get("overallTotal", 0):
            return trips
        page += 1


def get_trip(token: str, trip_id: str, program_id: str | None = None) -> dict:
    return _call(
        "GET", f"/api/trip/external/ExternalTrip/programId/{_program(program_id)}/tripId/{trip_id}",
        config.SWP_TRIP_KEY, token,
    )


def get_trip_detail(token: str, trip_id: str, program_id: str | None = None) -> dict:
    return _call(
        "GET", f"/api/trip/external/ExternalTripDetail/programId/{_program(program_id)}/tripId/{trip_id}",
        config.SWP_TRIP_KEY, token,
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
    disk and reused until `refresh`; this process also remembers it for SWP_TRIPS_CACHE_SECONDS."""
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
        for keyword in ALL_STATUS_KEYWORDS:
            for t in search_trips(token, keyword, program):
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
# def update_trip(token: str, trip_id: str, changes: dict, program_id: str | None = None) -> dict:
#     current = get_trip(token, trip_id, program_id)            # keep what is not being changed
#     body = {**current, **changes}   # e.g. {"tripStatusGuid": STATUS_GUIDS["arrived"],
#                                     #       "tripActualArrivalTime": "2026-10-12T09:32:00Z"}
#     return _call("PUT", f"/api/trip-manage/external/ExternalTrip/programId/{_program(program_id)}",
#                  config.SWP_TRIP_MANAGE_KEY, token, json=body)   # URL and key name: confirm in the portal

