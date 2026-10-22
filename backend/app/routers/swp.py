"""Trip data from the SWP (SensiWatch) API. Two steps, so the page does not wait for the slow part:
  1. the trip list (call 2, the search) with each trip's numbers from SWP's own statistics: quick, shown at once;
  2. the trip details (call 4) of the trips to be analysed, fetched in the background (services/swp/prefetch.py) and
     stored; loading the arrived trips into an audit session waits for any still outstanding.
Also the per-trip numbers, raw sensor readings and GPS route the Data Audit shows.
Nothing is written back to SWP (see the commented-out update_trip in services/swp/client.py)."""
import contextvars
import io
import logging
import threading
import time
import uuid
from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import config
from app.routers.job_route import JobRoute
from app.services.audit.audit_store import get_or_404, store
from app.services.common import audit_log, column_meta, file_store, request_context
from app.services.swp import cache, client, prefetch, preprocess, progress
from app.services.swp.transform import TIMEZONE, build_tables

log = logging.getLogger(__name__)

router = APIRouter(route_class=JobRoute, prefix="/api/swp", tags=["swp"])

SENSORS_FILE = "swp_sensors.parquet"
ROUTE_FILE = "swp_route.parquet"
# The session's "file name": the Audit page shows it where an upload's file name used to be.
SOURCE_NAME = "SWP API trips"
MAX_MAP_POINTS = 600
# The session is created as soon as this many trips are stored, so the Planner can start; the rest follow in the background.
FIRST_TRIPS = 3


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
    trip_id: str                 # the SWP trip GUID
    number: str | None = None    # the numeric Trip ID of the export
    status: str
    departure: str | None = None  # UTC
    arrival: str | None = None
    created: str | None = None
    updated: str | None = None
    alarmed: bool | None = None
    template: str | None = None
    trailer_id: str | None = None
    product: str | None = None
    origin: str | None = None
    destination: str | None = None
    carrier: str | None = None
    mean_temp: float | None = None      # Celsius
    segment_days: float | None = None


class TripsResponse(BaseModel):
    program_id: str
    total: int
    status_counts: dict[str, int]
    max_trips: int
    trips: list[TripSummary]
    # The field names of a list record, so a missing field can be traced to the API's naming.
    sample_fields: list[str]
    # When the trip list was fetched from SWP, and whether this answer reused that earlier fetch.
    fetched_at: str
    from_cache: bool


@router.get("/trips", response_model=TripsResponse)
def list_all_trips(program_id: str = "", refresh: bool = False, progress_id: str = "") -> TripsResponse:
    """Step 1: EVERY trip of the program from the trip search (call 2), each with its numbers from the search record. No
    detail calls: this is quick. The list is kept in the store and reused unless `refresh`. The program id defaults to
    SWP_PROGRAM_ID."""
    program = program_id.strip() or config.SWP_PROGRAM_ID
    _guard(program)
    progress.start(progress_id, label="Fetching all trips")
    records_list, fetched_at, from_cache = _swp_call(client.all_trips_info, program, refresh)
    progress.finish()
    trips = []
    for r in records_list:
        k = preprocess.record_kpis(r)
        trips.append(TripSummary(
            trip_id=r["tripID"], number=k["number"], status=client.status_name(r), departure=k["departure"], arrival=k["arrival"],
            created=r.get("createDate"), updated=r.get("lastUpdatedDate"), alarmed=k["alarmed"], template=r.get("templateName"),
            trailer_id=r.get("trailerID"), product=k["product"], origin=k["origin"], destination=k["destination"],
            carrier=k["carrier"], mean_temp=k["mean_temp"], segment_days=k["segment_days"],
        ))
    trips.sort(key=lambda t: t.updated or "", reverse=True)
    counts: dict[str, int] = {}
    for t in trips:
        counts[t.status] = counts.get(t.status, 0) + 1
    return TripsResponse(
        program_id=program, total=len(trips), status_counts=counts, max_trips=config.SWP_MAX_TRIPS,
        trips=trips, sample_fields=client.record_fields(records_list[0]) if records_list else [],
        fetched_at=datetime.fromtimestamp(fetched_at, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), from_cache=from_cache,
    )


class PrefetchRequest(BaseModel):
    program_id: str | None = None
    trip_ids: list[str] = Field(default_factory=list)


class PrefetchStatus(BaseModel):
    total: int
    done: int
    failed: int
    running: bool
    error: str | None = None
    seconds_per_trip: float   # about how long each outstanding trip takes (the gap between calls divided over the keys)


@router.post("/prefetch", response_model=PrefetchStatus)
def prefetch_details(body: PrefetchRequest) -> PrefetchStatus:
    """Start fetching the details (call 4) of these trips in the background, and report how far they are. Asking again
    with the same ids only reports; ids already stored, queued or done are not fetched twice. The trip list must have been
    fetched first (it is read from the store, no API call)."""
    program = (body.program_id or "").strip() or config.SWP_PROGRAM_ID
    _guard(program)
    by_lower = {r["tripID"].lower(): r for r in _swp_call(client.all_trips, program, False)}
    records = {}
    for tid in body.trip_ids:
        match = by_lower.get(tid.strip().lower())
        if match:
            records[match["tripID"]] = match
    return PrefetchStatus(**prefetch.submit(program, list(records), records))


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
    complete: bool    # False: the session holds the trips fetched so far and is being completed in the background
    loaded: int
    total: int


def _valid_trip_id(value: str) -> str:
    try:
        return str(uuid.UUID(value.strip()))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"'{value}' is not a valid trip id (expected a GUID).") from exc


def _save_frame(session_id: str, name: str, df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    file_store.put(session_id, name, buf.getvalue())


def _edits_for(edits: dict, by_lower: dict[str, dict]) -> dict[str, dict]:
    """The app's changes by trip GUID, keeping only what was actually set."""
    out = {}
    for tid, edit in edits.items():
        match = by_lower.get(tid.lower())
        if match:
            out[match["tripID"]] = {k: v for k, v in edit.model_dump().items() if v}
    return out


# session id -> how far the background task that completes it has got
_finishers: dict[str, dict] = {}


def _replace_session_data(session_id: str, agg: pd.DataFrame) -> None:
    """Swap the session's data for the complete table (the Planner may be saving the session at the same time: retry)."""
    for attempt in range(6):
        session = store.get(session_id)
        if session is None:
            return
        session.df = agg
        session.raw_df = agg.copy()
        session.row_count, session.column_count = len(agg), len(agg.columns)
        session.issues, session.summary = [], ""
        session.mutation_stack, session.audit_baseline, session.audit_events = [], None, []
        try:
            store.save(session)
            break
        except Exception:  # noqa: BLE001 - another request saved the session first: reload and try again
            if attempt == 5:
                raise
            time.sleep(0.5)
    try:
        column_meta.save(session_id, agg)
    except Exception:  # noqa: BLE001 - best effort, like an upload
        pass


def _start_finisher(session_id: str, program: str, ids: list[str], records: dict[str, dict], sensors: list[str], edits: dict, have: int) -> None:
    """Complete a session in the background: wait for every trip's detail, build the full table and put it in the session."""
    state = {"complete": False, "loaded": have, "total": len(ids), "error": None}
    _finishers[session_id] = state

    def run() -> None:
        try:
            def tick(done: int, total: int) -> None:
                state["loaded"] = done

            payloads = preprocess.payloads_for(program, ids, records, tick)
            agg, sensor_rows, route = build_tables(payloads, sensors or None, edits, records)
            _save_frame(session_id, SENSORS_FILE, sensor_rows)
            _save_frame(session_id, ROUTE_FILE, route)
            _replace_session_data(session_id, agg)
            cache.write_bytes(cache.aggregate_path(program), preprocess.excel_bytes(agg))
            state["loaded"], state["complete"] = len(ids), True
        except Exception as exc:  # noqa: BLE001 - reported through the status endpoint
            log.exception("completing session %s failed", session_id)
            state["error"] = str(exc)

    threading.Thread(target=contextvars.copy_context().run, args=(run,), daemon=True, name=f"swp-complete-{session_id[:6]}").start()


@router.post("/load", response_model=LoadResponse)
def load_trips(body: LoadRequest) -> LoadResponse:
    """Step 2: take the detail of the chosen (arrived) trips from the store, waiting for any the background fetch has not
    finished, apply the edits made in the app, build the aggregate table and open an audit session on it. The raw sensor
    readings and GPS route are kept alongside."""
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
            detail=f"At most {config.SWP_MAX_TRIPS} trips can be loaded at once.",
        )

    # Only arrived trips are analysed: a trip still on its way keeps changing. Status changes made in the app count.
    records = {tid: by_lower[tid.lower()] for tid in ids}
    not_arrived = [
        tid for tid in ids
        if (body.edits.get(tid) and body.edits[tid].status or client.status_name(records[tid])) != "Arrived"
    ]
    if not_arrived:
        raise HTTPException(
            status_code=422,
            detail=f"Only arrived trips can be loaded. Not arrived: {', '.join(not_arrived[:3])}{' ...' if len(not_arrived) > 3 else ''}",
        )

    # Phase 1: a session from the details stored so far, so the Planner can start at once. The first few trips are waited for (the
    # background fetch takes them in this order); the others are completed in the background (_start_finisher) and the Audit waits.
    prefetch.submit(program, ids, records)
    first = min(len(ids), FIRST_TRIPS)
    tracker = progress.start(body.progress_id, total=first, label="Loading the first trips")
    _swp_call(prefetch.wait, program, ids[:first], (lambda done, total: tracker.set(done, total)) if tracker else None)
    stored = preprocess.stored_payloads(program, ids, records)
    ready_ids = [t for t in ids if t in stored]
    edits = _edits_for(body.edits, by_lower)
    agg, sensors, route = build_tables([stored[t] for t in ready_ids], body.sensors or None, edits, records)
    if agg.empty:
        raise HTTPException(status_code=404, detail="The API returned no usable trip data.")

    session = store.create(source="sensiwatch", filename=SOURCE_NAME, df=agg, user_id=request_context.user_id())
    try:
        column_meta.save(session.session_id, session.df)
    except Exception:  # noqa: BLE001 - best effort, like an upload
        pass
    _save_frame(session.session_id, SENSORS_FILE, sensors)
    _save_frame(session.session_id, ROUTE_FILE, route)
    complete = len(ready_ids) == len(ids)
    if complete:
        cache.write_bytes(cache.aggregate_path(program), preprocess.excel_bytes(agg))  # the aggregate of this load, in the store
    else:
        _start_finisher(session.session_id, program, ids, records, body.sensors, edits, len(ready_ids))
    audit_log.log_event(
        session.session_id, session.user_id, "swp_load",
        {"program": program, "trips": len(ids), "ready_at_start": len(ready_ids), "rows": len(agg),
         "sensor_readings": len(sensors), "edited_trips": len(edits)},
    )
    progress.finish()
    return LoadResponse(
        session_id=session.session_id, filename=SOURCE_NAME, row_count=len(agg),
        column_count=len(agg.columns), columns=[str(c) for c in agg.columns], trip_ids=ids,
        complete=complete, loaded=len(ready_ids), total=len(ids),
    )


class SessionStatus(BaseModel):
    complete: bool
    loaded: int
    total: int
    error: str | None = None


@router.get("/{session_id}/status", response_model=SessionStatus)
def session_status(session_id: str) -> SessionStatus:
    """Whether the session holds all its trips yet (the rest are fetched in the background after the load)."""
    get_or_404(session_id)
    state = _finishers.get(session_id)
    if state is None:
        return SessionStatus(complete=True, loaded=0, total=0)
    return SessionStatus(complete=state["complete"], loaded=state["loaded"], total=state["total"], error=state["error"])


class AggregateRequest(BaseModel):
    program_id: str | None = None
    trip_ids: list[str] = Field(default_factory=list)
    sensors: list[str] = Field(default_factory=list)
    edits: dict[str, TripEdit] = Field(default_factory=dict)


class AggregateResponse(BaseModel):
    columns: list[str]
    rows: list[dict]
    trips_ready: int     # trips whose detail is stored, so they are in the table
    trips_total: int
    saved_to: str | None = None   # the Excel file written when every trip is ready


def _cell(value):
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if hasattr(value, "item"):
        return value.item()
    return value


@router.post("/aggregate", response_model=AggregateResponse)
def aggregate_preview(body: AggregateRequest) -> AggregateResponse:
    """The aggregate table (the columns of the Excel file) for these trips, from the details stored so far. No API call: trips whose
    detail is not stored yet are simply not in it. When every trip is there the Excel file is also written to the store."""
    program = (body.program_id or "").strip() or config.SWP_PROGRAM_ID
    _guard(program)
    by_lower = {r["tripID"].lower(): r for r in _swp_call(client.all_trips, program, False)}
    records = {}
    for tid in body.trip_ids:
        match = by_lower.get(tid.strip().lower())
        if match:
            records[match["tripID"]] = match
    ids = list(records)
    stored = preprocess.stored_payloads(program, ids, records)
    table, _readings, _route = build_tables([stored[t] for t in ids if t in stored], body.sensors or None, _edits_for(body.edits, by_lower), records)
    saved_to = None
    if ids and len(stored) == len(ids) and not table.empty:
        path = cache.aggregate_path(program)
        cache.write_bytes(path, preprocess.excel_bytes(table))
        saved_to = str(path)
    shown = table.reindex(columns=preprocess.AGGREGATE_COLUMNS)
    rows = [{c: _cell(v) for c, v in row.items()} for row in shown.to_dict("records")]
    return AggregateResponse(columns=preprocess.AGGREGATE_COLUMNS, rows=rows, trips_ready=len(stored), trips_total=len(ids), saved_to=saved_to)


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
    trip_id: str          # the SWP trip GUID (what Inspect is keyed by)
    trip_number: str | None   # the numeric Trip ID of the export
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
    what raw data is available to inspect. Numbers come from the audited table, so trips the audit
    removed are gone from here too."""
    session = get_or_404(session_id)
    df = session.df
    if "SWP Trip Key" not in df.columns:
        raise HTTPException(status_code=404, detail="This session has no SWP trips.")
    sensors = _frame(session_id, SENSORS_FILE)
    route = _frame(session_id, ROUTE_FILE)
    by_trip = {str(t): g for t, g in sensors.groupby("tripID")}
    points = route.groupby("tripID").size().to_dict()

    def text(row, col):
        value = row.get(col)
        if value is None or pd.isna(value):
            return None
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)  # 4750576.0 -> "4750576"

    out = []
    for key, rows in df.groupby("SWP Trip Key", sort=False):
        tid = str(key)
        first = rows.iloc[0]
        temperature = rows[rows["Sensor Type"] == "Temperature"] if "Sensor Type" in rows.columns else rows
        g = by_trip.get(tid)
        out.append(SessionTrip(
            trip_id=tid, trip_number=text(first, "Trip ID"), status=text(first, "Trip Status"),
            departure=text(first, "Actual Departure Time CET"), arrival=text(first, "Actual Arrival Time CET"),
            mean_temp=_num(temperature["Mean Value"].iloc[0]) if len(temperature) else None,
            segment_days=_num(first.get("Segment Length (Days)")),
            sensors=sorted(g["sensor"].unique().tolist()) if g is not None else [],
            readings=0 if g is None else len(g), gps_points=int(points.get(tid, 0)),
            edited=bool(text(first, "editedInApp")),
        ))
    return out


class TimesBody(BaseModel):
    """New departure and / or arrival time as a CET wall-clock time ("2026-10-18T15:42"): the times in the
    audit table are CET."""
    departure: str | None = None
    arrival: str | None = None


class TimesResponse(BaseModel):
    departure: str | None
    arrival: str | None
    departure_utc: str | None   # the same instants in UTC, for the Trips page's edit list
    arrival_utc: str | None
    segment_days: float | None


def _localize(ts: pd.Timestamp) -> pd.Timestamp:
    return ts.tz_localize(TIMEZONE, ambiguous=True, nonexistent="shift_forward")


def _wall_clock(value: str | None, field: str) -> pd.Timestamp | None:
    if not value:
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        raise HTTPException(status_code=422, detail=f"'{value}' is not a valid {field} time.")
    return ts.tz_localize(None) if ts.tzinfo else ts


def _iso(ts: pd.Timestamp | None, utc: bool = False) -> str | None:
    if ts is None or pd.isna(ts):
        return None
    return _localize(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ") if utc else ts.strftime("%Y-%m-%dT%H:%M:%S")


@router.patch("/{session_id}/trips/{trip_key}/times", response_model=TimesResponse)
def edit_trip_times(session_id: str, trip_key: str, body: TimesBody) -> TimesResponse:
    """Change a trip's departure and / or arrival in this session's data (CET), and with them its segment
    length. Only the app's data changes: nothing is sent to SWP."""
    departure, arrival = _wall_clock(body.departure, "departure"), _wall_clock(body.arrival, "arrival")
    if departure is None and arrival is None:
        raise HTTPException(status_code=422, detail="Give a departure and / or an arrival time.")
    session = get_or_404(session_id)
    result = None
    for name in ("df", "audit_baseline"):   # the audited data, and the baseline a revert rebuilds it from
        frame = getattr(session, name)
        if frame is None or "SWP Trip Key" not in frame.columns:
            continue
        mask = frame["SWP Trip Key"].astype(str).str.lower() == trip_key.lower()
        if not mask.any():
            if name == "df":
                raise HTTPException(status_code=404, detail="This trip is not in the session's data.")
            continue
        frame = frame.copy()
        if "editedInApp" in frame.columns:
            frame["editedInApp"] = frame["editedInApp"].astype(object)  # an all-empty column is float until text is put in it
        if departure is not None:
            frame.loc[mask, ["Actual Departure Time CET", "Segment Start Date Time"]] = departure
        if arrival is not None:
            frame.loc[mask, ["Actual Arrival Time CET", "Segment End Date Time"]] = arrival
        start = pd.to_datetime(frame.loc[mask, "Actual Departure Time CET"].iloc[0], errors="coerce")
        end = pd.to_datetime(frame.loc[mask, "Actual Arrival Time CET"].iloc[0], errors="coerce")
        days = _num((_localize(end) - _localize(start)).total_seconds() / 86400) if pd.notna(start) and pd.notna(end) else None
        frame.loc[mask, "Segment Length (Days)"] = days
        changed = {w for w, v in (("departure", departure), ("arrival", arrival)) if v is not None}
        had = str(frame.loc[mask, "editedInApp"].iloc[0] or "") if "editedInApp" in frame.columns else ""
        frame.loc[mask, "editedInApp"] = ", ".join(sorted(changed | {p for p in had.split(", ") if p}))
        setattr(session, name, frame)
        if name == "df":
            result = TimesResponse(
                departure=_iso(start), arrival=_iso(end), departure_utc=_iso(start, utc=True),
                arrival_utc=_iso(end, utc=True), segment_days=days,
            )
    store.save(session)
    audit_log.log_event(
        session_id, session.user_id, "swp_times_edited",
        {"trip": trip_key, "departure": _iso(departure), "arrival": _iso(arrival)},
    )
    return result


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
    # The trip's ideal temperature range in degrees C (its product limits), when it has one.
    limit_low: float | None = None
    limit_high: float | None = None


def _point(row) -> MapPoint:
    return MapPoint(
        lat=float(row["lat"]), lng=float(row["long"]),
        time=None if pd.isna(row["createdOn"]) else row["createdOn"].strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def _limits(df: pd.DataFrame, trip_id: str) -> tuple[float | None, float | None]:
    """The trip's Limit Low / Limit High (the ideal temperature range) from the audited table."""
    if "SWP Trip Key" not in df.columns or "Limit Low" not in df.columns:
        return None, None
    rows = df[df["SWP Trip Key"].astype(str).str.lower() == trip_id.lower()]
    if "Sensor Type" in rows.columns and (rows["Sensor Type"] == "Temperature").any():
        rows = rows[rows["Sensor Type"] == "Temperature"]
    if rows.empty:
        return None, None
    return _num(rows["Limit Low"].iloc[0]), _num(rows["Limit High"].iloc[0])


@router.get("/{session_id}/trips/{trip_id}/raw", response_model=TripRaw)
def trip_raw(session_id: str, trip_id: str) -> TripRaw:
    """The raw sensor readings (one series per sensor and logger) and the GPS route of one trip."""
    sensors = _frame(session_id, SENSORS_FILE)
    route = _frame(session_id, ROUTE_FILE)
    limit_low, limit_high = _limits(get_or_404(session_id).df, trip_id)
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
        limit_low=limit_low, limit_high=limit_high,
    )
