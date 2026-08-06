"""
Phase 2 ingestion + triage. Parses the 4 uploaded data sources and applies the
same first-pass checks Frank described doing by hand: is a SensiWatch trip
actually stuck, or does its last GPS reading already sit at the destination?
Is a ColdStream trip a genuine statistical outlier? This is deliberately
plain pandas + regex -- no LLM involved, matching "since this process is
pretty deterministic" from the discovery call.

This store is intake-only for now (see the plan's scope boundary) -- it does
not yet feed the Phase 1 dashboard/agents.
"""
import io
import json
import re
import threading
from datetime import datetime

import pandas as pd

from app.services.geo import haversine_km

DEFAULT_THRESHOLDS = {
    "sensiwatch_stuck_trip_days_since_creation": 14,
    "sensiwatch_gps_arrival_radius_km": 5,
    "coldstream_min_trip_duration_days": 0.25,
    "coldstream_max_trip_duration_days": 21,
    "temp_sane_min_c": -10,
    "temp_sane_max_c": 60,
    "humidity_sane_min_pct": 0,
    "humidity_sane_max_pct": 100,
}

TRIP_ID_PATTERN = re.compile(r"\b(?:SW|CS)-\d{4}-\d{4}\b")

_lock = threading.Lock()


class IngestionStore:
    def __init__(self):
        self.sensiwatch: dict | None = None      # {trip_header, sensor_readings, triage}
        self.coldstream: dict | None = None       # {trip_header, sensor_readings, triage}
        self.customer_profile_text: str | None = None
        self.business_rules: dict | None = None

    def thresholds(self) -> dict:
        merged = dict(DEFAULT_THRESHOLDS)
        if self.business_rules and "anomaly_thresholds" in self.business_rules:
            merged.update(self.business_rules["anomaly_thresholds"])
        return merged


store = IngestionStore()


def _flag_counts(triage: pd.DataFrame) -> dict:
    return {k: int(v) for k, v in triage["Flag"].value_counts().items()}


def _confirmations_from_profile(text: str | None) -> dict[str, str]:
    """Small regex read of the customer profile's delivery-confirmation language --
    maps TripID -> 'arrived' | 'not_arrived'. This is what lets a customer's own
    confirmation override a GPS-only guess."""
    confirmations = {}
    if not text:
        return confirmations
    for match in TRIP_ID_PATTERN.finditer(text):
        trip_id = match.group(0)
        window = text[match.end():match.end() + 250].lower()
        if "not" in window and "received" in window:
            confirmations[trip_id] = "not_arrived"
        elif "received" in window or "arrived" in window:
            confirmations[trip_id] = "arrived"
    return confirmations


def _triage_sensiwatch(trip_header: pd.DataFrame, sensor_readings: pd.DataFrame, thresholds: dict,
                        confirmations: dict[str, str]) -> pd.DataFrame:
    now = datetime.utcnow()
    rows = []
    for _, trip in trip_header.iterrows():
        trip_id = trip["TripID"]
        confirmation = confirmations.get(trip_id)
        distance_km = None

        if trip["TripStatus"] == "Closed":
            flag = "closed"
        else:
            days_since_created = (now - pd.Timestamp(trip["CreatedDate"]).to_pydatetime()).days
            readings = sensor_readings[sensor_readings["TripID"] == trip_id].sort_values("Timestamp")
            if not readings.empty:
                last = readings.iloc[-1]
                distance_km = round(
                    haversine_km(last["Lat"], last["Lon"], trip["DestinationLat"], trip["DestinationLon"]), 2
                )

            if days_since_created < thresholds["sensiwatch_stuck_trip_days_since_creation"]:
                flag = "active"
            elif distance_km is not None and distance_km <= thresholds["sensiwatch_gps_arrival_radius_km"]:
                flag = "likely_arrived"
            else:
                flag = "stuck_unresolved"

            # a customer's own confirmation overrides the GPS-only guess
            if confirmation == "arrived":
                flag = "likely_arrived"
            elif confirmation == "not_arrived":
                flag = "stuck_unresolved"

        rows.append(dict(TripID=trip_id, Flag=flag, DistanceToDestinationKm=distance_km,
                          CustomerConfirmation=confirmation))
    return pd.DataFrame(rows)


def _triage_coldstream(trip_header: pd.DataFrame, sensor_readings: pd.DataFrame, thresholds: dict) -> pd.DataFrame:
    rows = []
    for _, trip in trip_header.iterrows():
        trip_id = trip["TripID"]
        duration = trip["DurationDays"]
        readings = sensor_readings[sensor_readings["TripID"] == trip_id]

        if pd.isna(trip.get("EndDate")):
            flag = "missing_end_date"
        elif duration < thresholds["coldstream_min_trip_duration_days"]:
            flag = "duration_too_short"
        elif duration > thresholds["coldstream_max_trip_duration_days"]:
            flag = "duration_too_long"
        elif not readings.empty and (
            (readings["TemperatureC"] < thresholds["temp_sane_min_c"]).any()
            or (readings["TemperatureC"] > thresholds["temp_sane_max_c"]).any()
            or (readings["HumidityPct"] < thresholds["humidity_sane_min_pct"]).any()
            or (readings["HumidityPct"] > thresholds["humidity_sane_max_pct"]).any()
        ):
            flag = "value_outlier"
        else:
            flag = "clean"

        rows.append(dict(TripID=trip_id, Flag=flag))
    return pd.DataFrame(rows)


def ingest_sensiwatch(file_bytes: bytes) -> dict:
    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    trip_header = pd.read_excel(xls, "Trip_Header")
    sensor_readings = pd.read_excel(xls, "Sensor_Readings")
    confirmations = _confirmations_from_profile(store.customer_profile_text)
    triage = _triage_sensiwatch(trip_header, sensor_readings, store.thresholds(), confirmations)

    with _lock:
        store.sensiwatch = dict(trip_header=trip_header, sensor_readings=sensor_readings, triage=triage)

    return dict(source="sensiwatch", trip_count=len(trip_header), reading_count=len(sensor_readings),
                flags=_flag_counts(triage))


def ingest_coldstream(file_bytes: bytes) -> dict:
    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    trip_header = pd.read_excel(xls, "Trip_Header")
    sensor_readings = pd.read_excel(xls, "Sensor_Readings")
    triage = _triage_coldstream(trip_header, sensor_readings, store.thresholds())

    with _lock:
        store.coldstream = dict(trip_header=trip_header, sensor_readings=sensor_readings, triage=triage)

    return dict(source="coldstream", trip_count=len(trip_header), reading_count=len(sensor_readings),
                flags=_flag_counts(triage))


def ingest_customer_profile(text: str) -> dict:
    with _lock:
        store.customer_profile_text = text

    confirmations = _confirmations_from_profile(text)
    if store.sensiwatch is not None:
        triage = _triage_sensiwatch(store.sensiwatch["trip_header"], store.sensiwatch["sensor_readings"],
                                     store.thresholds(), confirmations)
        with _lock:
            store.sensiwatch["triage"] = triage

    return dict(source="customer_profile", char_count=len(text), section_count=text.count("\n## "),
                confirmed_trip_count=len(confirmations))


def ingest_business_rules(json_bytes: bytes) -> dict:
    parsed = json.loads(json_bytes)
    with _lock:
        store.business_rules = parsed

    # thresholds may have just changed -- re-triage whatever is already loaded
    if store.sensiwatch is not None:
        confirmations = _confirmations_from_profile(store.customer_profile_text)
        triage = _triage_sensiwatch(store.sensiwatch["trip_header"], store.sensiwatch["sensor_readings"],
                                     store.thresholds(), confirmations)
        with _lock:
            store.sensiwatch["triage"] = triage
    if store.coldstream is not None:
        triage = _triage_coldstream(store.coldstream["trip_header"], store.coldstream["sensor_readings"],
                                     store.thresholds())
        with _lock:
            store.coldstream["triage"] = triage

    return dict(source="business_rules", product_count=len(parsed.get("product_specs", {})),
                standard_kpi_count=len(parsed.get("standard_kpis", [])),
                customer_kpi_count=len(parsed.get("customer_kpis", [])))


def get_status() -> dict:
    sensiwatch_summary = None
    if store.sensiwatch is not None:
        sensiwatch_summary = dict(trip_count=len(store.sensiwatch["trip_header"]),
                                   reading_count=len(store.sensiwatch["sensor_readings"]),
                                   flags=_flag_counts(store.sensiwatch["triage"]))

    coldstream_summary = None
    if store.coldstream is not None:
        coldstream_summary = dict(trip_count=len(store.coldstream["trip_header"]),
                                   reading_count=len(store.coldstream["sensor_readings"]),
                                   flags=_flag_counts(store.coldstream["triage"]))

    return dict(sensiwatch=sensiwatch_summary, coldstream=coldstream_summary,
                customer_profile_loaded=store.customer_profile_text is not None,
                business_rules_loaded=store.business_rules is not None)
