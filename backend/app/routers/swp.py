"""Trip data from the SWP (SensiWatch) API: the list of all trips of a program, loading chosen trips into
an audit session, and the per-trip numbers, raw sensor readings and GPS route the Data Audit shows.
Nothing is written back to SWP (see the commented-out update_trip in services/swp/client.py)."""
import io
import uuid
from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import config
from app.routers.job_route import JobRoute
from app.services.audit.audit_store import get_or_404, store
from app.services.common import audit_log, column_meta, file_store, request_context
from app.services.swp import cache, client, progress
from app.services.swp.transform import build_tables

router = APIRouter(route_class=JobRoute, prefix="/api/swp", tags=["swp"])

SENSORS_FILE = "swp_sensors.parquet"
ROUTE_FILE = "swp_route.parquet"
# The session's "file name": the Audit page shows it where an upload's file name used to be.
SOURCE_NAME = "SWP API trips"
MAX_MAP_POINTS = 600


def _guard(program_id: str | None = None) -> None:
    missing = client.missing_settings(program_id)
    if missing:
        raise HTTPException(
            status_code=503, detail="The SWP API is not configured. Set in backend/.env: " + ", ".join(missing)
        )


def _swp_call(fn, *args):
    try:
        return fn(*args)
    except client.SwpError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class TripSummary(BaseModel):
    trip_id: str
    status: str
    departure: str | None = None
    arrival: str | None = None
    created: str | None = None
    updated: str | None = None
    alarmed: bool | None = None
    template: str | None = None
    trailer_id: str | None = None


class TripsResponse(BaseModel):
    program_id: str
    total: int
    status_counts: dict[str, int]
    max_trips: int
    trips: list[TripSummary]
    # The field names of a list record, so a missing departure date can be traced to the API's naming.
    sample_fields: list[str]
    # When the list was fetched from SWP, and whether this answer reused that earlier fetch.
    fetched_at: str
    from_cache: bool


@router.get("/trips", response_model=TripsResponse)
def list_all_trips(program_id: str = "", refresh: bool = False, progress_id: str = "") -> TripsResponse:
    """Step 1: every trip of the program. The list fetched earlier is reused (it is kept on disk) unless
    `refresh`. The program id defaults to SWP_PROGRAM_ID."""
    program = program_id.strip() or config.SWP_PROGRAM_ID
    _guard(program)
    progress.start(progress_id, label="Fetching the trip list")
    records, fetched_at, from_cache = _swp_call(client.all_trips_info, program, refresh)
    progress.finish()
    trips = [
        TripSummary(
            trip_id=r["tripID"], status=client.status_name(r), departure=client.departure_of(r),
            arrival=client.arrival_of(r), created=r.get("createDate"), updated=r.get("lastUpdatedDate"),
            alarmed=r.get("alarmed"), template=r.get("templateName"), trailer_id=r.get("trailerID"),
        )
        for r in records
    ]
    trips.sort(key=lambda t: t.updated or "", reverse=True)
    counts: dict[str, int] = {}
    for t in trips:
        counts[t.status] = counts.get(t.status, 0) + 1
    return TripsResponse(
        program_id=program, total=len(trips), status_counts=counts, max_trips=config.SWP_MAX_TRIPS,
        trips=trips, sample_fields=client.record_fields(records[0]) if records else [],
        fetched_at=datetime.fromtimestamp(fetched_at, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), from_cache=from_cache,
    )


class TripEdit(BaseModel):
    """A change made in the app (not in SWP): status label, and / or departure / arrival time (ISO)."""
    status: str | None = None
    departure: str | None = None
    arrival: str | None = None


class LoadRequest(BaseModel):
    program_id: str | None = None
    progress_id: str | None = None                             # to follow the load's API calls (GET /progress/<id>)
    trip_ids: list[str] = Field(min_length=1)
    sensors: list[str] = Field(default_factory=list)          # e.g. ["Temperature", "Light"]; empty = all
    edits: dict[str, TripEdit] = Field(default_factory=dict)  # by trip id


class LoadResponse(BaseModel):
    session_id: str
    filename: str
    row_count: int
    column_count: int
    columns: list[str]
    trip_ids: list[str]


def _valid_trip_id(value: str) -> str:
    try:
        return str(uuid.UUID(value.strip()))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"'{value}' is not a valid trip id (expected a GUID).") from exc


def _save_frame(session_id: str, name: str, df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    file_store.put(session_id, name, buf.getvalue())


@router.post("/load", response_model=LoadResponse)
def load_trips(body: LoadRequest) -> LoadResponse:
    """Step 2: fetch the detail of the chosen trips, apply the edits made in the app, build the aggregate
    table and open an audit session on it. The raw sensor readings and GPS route are kept alongside."""
    program = (body.program_id or "").strip() or config.SWP_PROGRAM_ID
    _guard(program)
    all_records = _swp_call(client.all_trips, program, False)
    by_lower = {r["tripID"].lower(): r for r in all_records}

    ids = list(dict.fromkeys(_valid_trip_id(t) for t in body.trip_ids))
    unknown = [t for t in ids if t.lower() not in by_lower]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Trip(s) not found in the program: {', '.join(unknown[:5])}")
    ids = [by_lower[t.lower()]["tripID"] for t in ids]
    if len(ids) > config.SWP_MAX_TRIPS:
        raise HTTPException(
            status_code=422,
            detail=f"At most {config.SWP_MAX_TRIPS} trips can be loaded at once (each takes an API call or two).",
        )

    # An arrived trip no longer changes, so one fetched before is read from the cache instead of the API.
    saved: dict[str, dict] = {}
    for tid in ids:
        if client.status_name(by_lower[tid.lower()]) == "Arrived":
            hit = cache.load_trip(program, tid)
            if hit and hit.get("detail"):
                saved[tid] = hit

    # Calls to come: the trip detail of every trip not cached (plus the single-trip call when the list record
    # lacks its basics), the product table, and a token if any call is needed at all.
    calls = sum(0 if t in saved else (1 if "serialNumbers" in by_lower[t.lower()] else 2) for t in ids)
    need_products = bool(config.SWP_ADMIN_KEY) and cache.load_products(program) is None
    expected = calls + (1 if need_products else 0)
    expected += 1 if expected and not client.has_token() else 0
    progress.start(body.progress_id, total=expected, label="Loading trip data")
    token = _swp_call(client.get_token) if expected else ""
    trips_data = []
    for tid in ids:
        if tid in saved:
            trips_data.append({"tripID": tid, "basic": saved[tid]["basic"], "detail": saved[tid]["detail"]})
            continue
        # The list record already carries the basic fields (serial numbers), which saves one
        # rate-limited API call per trip; only fall back to the single-trip call without them.
        basic = by_lower[tid.lower()]
        if "serialNumbers" not in basic:
            basic = _swp_call(client.get_trip, token, tid, program)
        detail = _swp_call(client.get_trip_detail, token, tid, program)
        if client.status_name(by_lower[tid.lower()]) == "Arrived":
            cache.save_trip(program, tid, basic, detail)
        trips_data.append({"tripID": tid, "basic": basic, "detail": detail})
    products = _swp_call(client.get_products, token, program) if config.SWP_ADMIN_KEY or cache.load_products(program) else {}

    edits = {}
    for tid, edit in body.edits.items():
        match = by_lower.get(tid.lower())
        if match:
            edits[match["tripID"]] = {k: v for k, v in edit.model_dump().items() if v}
    listed = {
        tid: {"departure": client.departure_of(by_lower[tid.lower()]), "arrival": client.arrival_of(by_lower[tid.lower()])}
        for tid in ids
    }
    agg, sensors, route = build_tables(trips_data, body.sensors or None, edits, listed, products)
    if agg.empty:
        raise HTTPException(status_code=404, detail="The API returned no usable trip data.")

    session = store.create(source="sensiwatch", filename=SOURCE_NAME, df=agg, user_id=request_context.user_id())
    try:
        column_meta.save(session.session_id, session.df)
    except Exception:  # noqa: BLE001 - best effort, like an upload
        pass
    _save_frame(session.session_id, SENSORS_FILE, sensors)
    _save_frame(session.session_id, ROUTE_FILE, route)
    audit_log.log_event(
        session.session_id, session.user_id, "swp_load",
        {"program": program, "trips": len(ids), "rows": len(agg), "sensor_readings": len(sensors),
         "edited_trips": len(edits)},
    )
    progress.finish()
    return LoadResponse(
        session_id=session.session_id, filename=SOURCE_NAME, row_count=len(agg),
        column_count=len(agg.columns), columns=[str(c) for c in agg.columns], trip_ids=ids,
    )


class ProgressResponse(BaseModel):
    done: int
    total: int
    label: str
    finished: bool


@router.get("/progress/{progress_id}", response_model=ProgressResponse)
def get_progress(progress_id: str) -> ProgressResponse:
    """API calls made so far / expected for the operation that was given this id (zeros until it starts)."""
    p = progress.get(progress_id)
    if p is None:
        return ProgressResponse(done=0, total=0, label="", finished=False)
    return ProgressResponse(done=p.done, total=p.total, label=p.label, finished=p.finished)


def _frame(session_id: str, name: str) -> pd.DataFrame:
    get_or_404(session_id)
    raw = file_store.get(session_id, name)
    if raw is None:
        raise HTTPException(status_code=404, detail="No raw trip data is stored for this session.")
    return pd.read_parquet(io.BytesIO(raw))


def _num(value) -> float | None:
    return None if value is None or pd.isna(value) else round(float(value), 2)


class SessionTrip(BaseModel):
    trip_id: str
    status: str | None
    departure: str | None
    arrival: str | None
    mean_temp: float | None
    segment_days: float | None
    sensors: list[str]
    readings: int
    gps_points: int
    edited: bool


@router.get("/{session_id}/trips", response_model=list[SessionTrip])
def session_trips(session_id: str) -> list[SessionTrip]:
    """One row per trip of this session for the Data Audit table: mean temperature, segment days and
    what raw data is available to inspect. Numbers come from the audited table, so rows the audit
    removed are gone from here too."""
    session = get_or_404(session_id)
    df = session.df
    if "tripID" not in df.columns:
        raise HTTPException(status_code=404, detail="This session has no SWP trips.")
    sensors = _frame(session_id, SENSORS_FILE)
    route = _frame(session_id, ROUTE_FILE)
    by_trip = {str(t): g for t, g in sensors.groupby("tripID")}
    points = route.groupby("tripID").size().to_dict()

    def text(row, col):
        value = row.get(col)
        return None if value is None or pd.isna(value) else str(value)

    out = []
    for _, row in df.iterrows():
        tid = str(row["tripID"])
        g = by_trip.get(tid)
        out.append(SessionTrip(
            trip_id=tid, status=text(row, "tripStatus"), departure=text(row, "actualDeparture (UTC)"),
            arrival=text(row, "actualArrival (UTC)"), mean_temp=_num(row.get("Mean Value_Temperature")),
            segment_days=_num(row.get("Segment Length (Days)")),
            sensors=sorted(g["sensor"].unique().tolist()) if g is not None else [],
            readings=0 if g is None else len(g), gps_points=int(points.get(tid, 0)),
            edited=bool(text(row, "editedInApp")),
        ))
    return out


class SensorSeries(BaseModel):
    sensor: str
    serial_number: str | None
    x: list[str]
    y: list[float]


class MapPoint(BaseModel):
    lat: float
    lng: float
    time: str | None = None


class TripRaw(BaseModel):
    trip_id: str
    series: list[SensorSeries]
    # The GPS route, thinned to at most MAX_MAP_POINTS points; start and end are always the real first
    # and last points.
    route: list[MapPoint]
    start: MapPoint | None
    end: MapPoint | None


def _point(row) -> MapPoint:
    return MapPoint(
        lat=float(row["lat"]), lng=float(row["long"]),
        time=None if pd.isna(row["createdOn"]) else row["createdOn"].strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


@router.get("/{session_id}/trips/{trip_id}/raw", response_model=TripRaw)
def trip_raw(session_id: str, trip_id: str) -> TripRaw:
    """The raw sensor readings (one series per sensor and logger) and the GPS route of one trip."""
    sensors = _frame(session_id, SENSORS_FILE)
    route = _frame(session_id, ROUTE_FILE)
    wanted = trip_id.lower()
    trip = sensors[sensors["tripID"].astype(str).str.lower() == wanted]
    path = route[route["tripID"].astype(str).str.lower() == wanted].reset_index(drop=True)
    if trip.empty and path.empty:
        raise HTTPException(status_code=404, detail="No sensor readings or GPS points for this trip.")
    series = []
    for (sensor, serial), g in trip.groupby(["sensor", "serialNumber"], sort=True, dropna=False):
        g = g.sort_values("dateTime")
        series.append(SensorSeries(
            sensor=str(sensor), serial_number=None if pd.isna(serial) else str(serial),
            x=g["dateTime"].dt.strftime("%Y-%m-%dT%H:%M:%SZ").tolist(), y=g["value"].astype(float).tolist(),
        ))
    thinned = path
    if len(path) > MAX_MAP_POINTS:
        keep = sorted({int(i * (len(path) - 1) / (MAX_MAP_POINTS - 1)) for i in range(MAX_MAP_POINTS)})
        thinned = path.iloc[keep]
    return TripRaw(
        trip_id=trip_id, series=series, route=[_point(r) for _, r in thinned.iterrows()],
        start=_point(path.iloc[0]) if len(path) else None, end=_point(path.iloc[-1]) if len(path) else None,
    )
