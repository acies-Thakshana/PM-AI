"""Trip data from the SWP (SensiWatch) API: the list of all trips, loading a chosen set of them
into an audit session, and the raw sensor readings of one trip for the Data Audit graph.
No data is written back to SWP."""
import io
import uuid

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import config
from app.routers.job_route import JobRoute
from app.services.audit.audit_store import get_or_404, store
from app.services.common import audit_log, column_meta, file_store, request_context
from app.services.swp import client
from app.services.swp.transform import build_tables

router = APIRouter(route_class=JobRoute, prefix="/api/swp", tags=["swp"])

SENSORS_FILE = "swp_sensors.parquet"
# The session's "file name": the Audit page shows it where an upload's file name used to be.
SOURCE_NAME = "SWP API trips"


def _guard() -> None:
    missing = client.missing_settings()
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
    created: str | None = None
    updated: str | None = None
    alarmed: bool | None = None
    template: str | None = None
    trailer_id: str | None = None


class TripsResponse(BaseModel):
    total: int
    status_counts: dict[str, int]
    max_trips: int
    trips: list[TripSummary]


@router.get("/trips", response_model=TripsResponse)
def list_all_trips(refresh: bool = False) -> TripsResponse:
    """Step 1: every trip in the program (reused for a few minutes unless `refresh`)."""
    _guard()
    records = _swp_call(client.all_trips, refresh)
    trips = [
        TripSummary(
            trip_id=r["tripID"], status=client.status_name(r), created=r.get("createDate"),
            updated=r.get("lastUpdatedDate"), alarmed=r.get("alarmed"),
            template=r.get("templateName"), trailer_id=r.get("trailerID"),
        )
        for r in records
    ]
    trips.sort(key=lambda t: t.updated or "", reverse=True)
    counts: dict[str, int] = {}
    for t in trips:
        counts[t.status] = counts.get(t.status, 0) + 1
    return TripsResponse(total=len(trips), status_counts=counts, max_trips=config.SWP_MAX_TRIPS, trips=trips)


class LoadRequest(BaseModel):
    status: str | None = None                          # e.g. "InTransit"; None = every status
    n_trips: int = Field(default=1, ge=1)
    trip_ids: list[str] = Field(default_factory=list)  # specific trips; override status / n_trips


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


@router.post("/load", response_model=LoadResponse)
def load_trips(body: LoadRequest) -> LoadResponse:
    """Step 2: fetch the detail of the chosen trips, build the aggregate table and open an audit
    session on it. The raw sensor readings are kept alongside for the Data Audit graph."""
    _guard()
    all_records = _swp_call(client.all_trips, False)
    status = (body.status or "").strip()
    if status.lower() in ("", "none", "all"):
        status = ""

    if body.trip_ids:
        ids = list(dict.fromkeys(_valid_trip_id(t) for t in body.trip_ids))
        by_lower = {r["tripID"].lower(): r["tripID"] for r in all_records}
        unknown = [t for t in ids if t.lower() not in by_lower]
        if unknown:
            raise HTTPException(status_code=404, detail=f"Trip(s) not found in the program: {', '.join(unknown[:5])}")
        ids = [by_lower[t.lower()] for t in ids]
    else:
        want = status.replace(" ", "").lower()
        candidates = [r for r in all_records if not want or client.status_name(r).lower() == want]
        candidates.sort(key=lambda r: r.get("lastUpdatedDate") or "", reverse=True)
        ids = [r["tripID"] for r in candidates[: body.n_trips]]
    if not ids:
        raise HTTPException(status_code=404, detail=f"No trips found with status '{status or 'any'}'.")
    if len(ids) > config.SWP_MAX_TRIPS:
        raise HTTPException(
            status_code=422,
            detail=f"At most {config.SWP_MAX_TRIPS} trips can be loaded at once (each takes two API calls).",
        )

    token = _swp_call(client.get_token)
    trips_data = []
    for tid in ids:
        trips_data.append({
            "tripID": tid,
            "basic": _swp_call(client.get_trip, token, tid),
            "detail": _swp_call(client.get_trip_detail, token, tid),
        })
    agg, sensors = build_tables(trips_data)
    if agg.empty:
        raise HTTPException(status_code=404, detail="The API returned no usable trip data.")

    session = store.create(source="sensiwatch", filename=SOURCE_NAME, df=agg, user_id=request_context.user_id())
    try:
        column_meta.save(session.session_id, session.df)
    except Exception:  # noqa: BLE001 - best effort, like an upload
        pass
    buf = io.BytesIO()
    sensors.to_parquet(buf, index=False)
    file_store.put(session.session_id, SENSORS_FILE, buf.getvalue())
    audit_log.log_event(
        session.session_id, session.user_id, "swp_load",
        {"status": status or None, "trips": len(ids), "rows": len(agg), "sensor_readings": len(sensors)},
    )
    return LoadResponse(
        session_id=session.session_id, filename=SOURCE_NAME, row_count=len(agg),
        column_count=len(agg.columns), columns=[str(c) for c in agg.columns], trip_ids=ids,
    )


def _sensors(session_id: str) -> pd.DataFrame:
    get_or_404(session_id)
    raw = file_store.get(session_id, SENSORS_FILE)
    if raw is None:
        raise HTTPException(status_code=404, detail="No raw sensor data is stored for this session.")
    return pd.read_parquet(io.BytesIO(raw))


class TripSensors(BaseModel):
    trip_id: str
    sensors: list[str]
    readings: int


@router.get("/{session_id}/trips", response_model=list[TripSensors])
def session_trips(session_id: str) -> list[TripSensors]:
    """The trips of this session that have raw sensor readings, and which sensors they have."""
    df = _sensors(session_id)
    return [
        TripSensors(trip_id=str(tid), sensors=sorted(g["sensor"].unique().tolist()), readings=len(g))
        for tid, g in df.groupby("tripID", sort=False)
    ]


class SensorSeries(BaseModel):
    sensor: str
    serial_number: str | None
    x: list[str]
    y: list[float]


class TripRaw(BaseModel):
    trip_id: str
    series: list[SensorSeries]


@router.get("/{session_id}/trips/{trip_id}/raw", response_model=TripRaw)
def trip_raw(session_id: str, trip_id: str) -> TripRaw:
    """Every raw sensor reading of one trip, one series per sensor and logger."""
    df = _sensors(session_id)
    trip = df[df["tripID"].astype(str).str.lower() == trip_id.lower()]
    if trip.empty:
        raise HTTPException(status_code=404, detail="No sensor readings for this trip.")
    series = []
    for (sensor, serial), g in trip.groupby(["sensor", "serialNumber"], sort=True, dropna=False):
        g = g.sort_values("dateTime")
        series.append(SensorSeries(
            sensor=str(sensor), serial_number=None if pd.isna(serial) else str(serial),
            x=g["dateTime"].dt.strftime("%Y-%m-%dT%H:%M:%SZ").tolist(), y=g["value"].astype(float).tolist(),
        ))
    return TripRaw(trip_id=str(trip["tripID"].iloc[0]), series=series)
