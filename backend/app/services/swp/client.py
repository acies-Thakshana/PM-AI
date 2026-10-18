"""Thin client for the SWP (SensiWatch) external API. All secrets come from app.config (env vars)."""
from __future__ import annotations

import logging
import threading
import time

import requests

from app import config

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

_REQUIRED = ("SWP_BASE_URL", "SWP_PROGRAM_ID", "SWP_SECURITY_KEY", "SWP_TRIP_KEY", "SWP_USER", "SWP_PASS")


class SwpError(Exception):
    """The SWP API is not configured, or it refused / failed a call."""


def missing_settings() -> list[str]:
    return [name for name in _REQUIRED if not getattr(config, name)]


_lock = threading.Lock()          # one call at a time keeps us under the 20 calls/min limit
_token: dict = {"value": None, "expires": 0.0}


def _call(method: str, path: str, key: str, token: str | None = None, **kwargs) -> dict:
    missing = missing_settings()
    if missing:
        raise SwpError("The SWP API is not configured. Set in backend/.env: " + ", ".join(missing))
    headers = {"Ocp-Apim-Subscription-Key": key}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with _lock:
        try:
            r = requests.request(method, config.SWP_BASE_URL + path, headers=headers, timeout=60, **kwargs)
        except requests.RequestException as exc:
            raise SwpError(f"Could not reach the SWP API: {exc}") from exc
        log.info("SWP %s %s -> %s", method, path.split("?")[0], r.status_code)
        time.sleep(config.SWP_CALL_DELAY_SECONDS)
    if r.status_code != 200:
        raise SwpError(f"SWP API {method} {path.split('?')[0]} failed ({r.status_code}): {r.text[:300]}")
    return r.json()


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


def search_trips(token: str, keyword: str) -> list[dict]:
    """All trips matching a keyword (page through the results)."""
    trips: list[dict] = []
    page = 0
    while True:
        data = _call(
            "POST", f"/api/trip/external/ExternalTrip/tripsearch/programId/{config.SWP_PROGRAM_ID}",
            config.SWP_TRIP_KEY, token, json={"keyword": keyword, "from": page},
        )
        records = data.get("records") or []
        trips += records
        if not records or len(trips) >= data.get("overallTotal", 0):
            return trips
        page += 1


def get_trip(token: str, trip_id: str) -> dict:
    return _call(
        "GET", f"/api/trip/external/ExternalTrip/programId/{config.SWP_PROGRAM_ID}/tripId/{trip_id}",
        config.SWP_TRIP_KEY, token,
    )


def get_trip_detail(token: str, trip_id: str) -> dict:
    return _call(
        "GET", f"/api/trip/external/ExternalTripDetail/programId/{config.SWP_PROGRAM_ID}/tripId/{trip_id}",
        config.SWP_TRIP_KEY, token,
    )


# ---- the list of all trips, fetched once and reused ------------------------------------------
_trips_cache: dict = {"at": 0.0, "trips": None}
_trips_lock = threading.Lock()


def status_name(record: dict) -> str:
    """The trip's status as text: the API's own text when it has one, else the GUID's name."""
    text = str(record.get("tripStatus") or "").replace(" ", "")
    if text:
        return STATUS_LABELS.get(text.lower(), text)
    key = GUID_NAMES.get(str(record.get("tripStatusGuid") or "").upper())
    return STATUS_LABELS.get(key, "Unknown") if key else "Unknown"


def all_trips(refresh: bool = False) -> list[dict]:
    """Every trip in the program (de-duplicated across the per-status searches)."""
    with _trips_lock:
        fresh = time.time() - _trips_cache["at"] < config.SWP_TRIPS_CACHE_SECONDS
        if _trips_cache["trips"] is not None and fresh and not refresh:
            return _trips_cache["trips"]
        token = get_token()
        by_id: dict[str, dict] = {}
        for keyword in ALL_STATUS_KEYWORDS:
            for t in search_trips(token, keyword):
                by_id[t["tripID"]] = t
        _trips_cache.update(at=time.time(), trips=list(by_id.values()))
        return _trips_cache["trips"]
