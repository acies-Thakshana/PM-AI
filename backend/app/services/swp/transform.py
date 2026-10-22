"""Turns SWP trip JSON into the tables the app uses.

  * the audit table: the same columns, in the same order, as a SensiWatch tabular-shipment export (Serial
    Number, Trip ID, Product, Origin, Segment Length (Days), Sensor Type, Limit Low, Mean Value, ...), one row
    per trip and sensor (Temperature, Light) -- the "long sensor format" the audit, outlier checks, features
    and analyses already understand;
  * the raw sensor readings and the GPS route, kept for the Inspect graph and map.

Where each column comes from is listed next to it below. Times are converted from UTC to CET; temperatures
from Fahrenheit (what the API returns) to Celsius.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from app import config
from app.services.swp import client
from app.services.swp.client import GUID_NAMES, STATUS_LABELS

SENSOR_LISTS = {
    "temperatureData": "Temperature", "simulatedTemperatureData": "SimulatedTemperature",
    "lightData": "Light", "humidityData": "Humidity", "co2Data": "CO2",
    "temperatureProbeData": "TemperatureProbe",
}
TEMPERATURE_SENSORS = {"Temperature", "SimulatedTemperature", "TemperatureProbe"}
# The audit table has a row per trip for each of these (the export format knows only these two).
TABLE_SENSORS = ("Temperature", "Light")
SENSOR_COLUMNS = ["tripID", "serialNumber", "sensor", "dateTime", "value"]
ROUTE_COLUMNS = ["tripID", "lat", "long", "createdOn"]
TIMEZONE = "Europe/Berlin"  # "CET" in the column names

EXPORT_COLUMNS = [
    "Serial Number", "Trip ID", "Trip Detail", "Trip Create Date CET", "Trip Status", "Segment Name",
    "Quality Status", "Quality Comment", "Product", "Origin", "Destination", "Managing Carrier", "Carrier",
    "Parent Supplier", "Order Number", "PO Number", "Internal Trip ID", "Trailer ID", "Mode Of Transportation",
    "Driver Name", "Driver Cell", "Planned Departure Time CET", "Actual Departure Time CET",
    "Planned Arrival Time CET", "Actual Arrival Time CET", "Segment Length (Days)", "Container Name", "Zone Name",
    "Segment Type", "Segment Number", "Segment Start Date Time", "Segment End Date Time", "Sensor Type",
    "Degree Unit", "Limit Low", "Limit Ideal", "Limit High", "Mean Value", "Standard Deviation", "Min Value",
    "Max Value", "MKT Statistics Value", "Time Below Low Hours", "Time Below Ideal Hours",
    "Time Above Ideal Hours", "Time Above High Hours", "Value Minutes Below Low", "Value Minutes Below Ideal",
    "Value Minutes Above Ideal", "Value Minutes Above High", "Specs Last Updated Date/Time",
    "Shipment Created Date/Time", "Shipment Created By", "Trip Note", "Latest Reprocess Date",
    "Latest Reprocess User", "Reprocess Type", "Is Alarmed", "Trip Review",
    # Not in the export: the trip's GUID (what the SWP API and the Inspect view are keyed by) and whether the
    # app changed its status or times. Neither name contains "trip" and "id" together, so the outlier checks
    # still find "Trip ID" as the trip column.
    "SWP Trip Key", "editedInApp",
]


def to_naive_utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce").dt.tz_localize(None)


def to_cet(value) -> pd.Timestamp | None:
    """An ISO UTC time as a CET wall-clock time (no time zone attached), or None."""
    ts = pd.to_datetime(value, utc=True, errors="coerce") if value else pd.NaT
    return None if pd.isna(ts) else ts.tz_convert(TIMEZONE).tz_localize(None)


def f_to_c(value):
    """Fahrenheit -> Celsius (SWP_TEMPERATURE_FAHRENHEIT=0 leaves values as they are)."""
    if value is None or pd.isna(value):
        return None
    return (float(value) - 32.0) * 5.0 / 9.0 if config.SWP_TEMPERATURE_FAHRENHEIT else float(value)


def pick(d, *path):
    """d[path[0]][path[1]]... where a list on the way means "its first item"; None if anything is missing."""
    for p in path:
        if isinstance(d, list):
            d = d[0] if d else None
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def duration_days(text: str | None) -> float | None:
    """'3.17:00:00' (days.hours:minutes:seconds) -> days."""
    m = re.match(r"(?:(\d+)\.)?(\d+):(\d+):(\d+)", text or "")
    if not m:
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d + h / 24 + mi / 1440 + s / 86400


def _flatten(obj, prefix: str = "") -> dict:
    out: dict = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}{k}."))
    elif isinstance(obj, list):
        if obj:
            out.update(_flatten(obj[0], prefix))
    else:
        out[prefix.rstrip(".")] = obj
    return out


def _first(flat: dict, suffix: str):
    """The first non-empty value whose field path ends with `suffix` (case-insensitive)."""
    suffix = suffix.lower()
    for key, value in flat.items():
        if key.lower().endswith(suffix) and value not in (None, ""):
            return value
    return None


def sensor_frame(detail: dict) -> pd.DataFrame:
    """Long table of every sensor reading of one trip: serialNumber, sensor, dateTime (UTC), value. Temperatures
    are converted to Celsius."""
    rows = []
    for dev in detail.get("sensorData") or []:
        for key, name in SENSOR_LISTS.items():
            for p in dev.get(key) or []:
                rows.append({"serialNumber": dev.get("serialNumber"), "sensor": name,
                             "dateTime": p.get("dateTime"), "value": p.get("value")})
    df = pd.DataFrame(rows, columns=["serialNumber", "sensor", "dateTime", "value"])
    if not df.empty:
        df["dateTime"] = to_naive_utc(df["dateTime"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce").astype(float)
        df = df.dropna(subset=["dateTime", "value"]).sort_values(["serialNumber", "dateTime", "sensor"])
        df = df.reset_index(drop=True)
        is_temp = df["sensor"].isin(TEMPERATURE_SENSORS)
        if config.SWP_TEMPERATURE_FAHRENHEIT and is_temp.any():
            df.loc[is_temp, "value"] = (df.loc[is_temp, "value"] - 32.0) * 5.0 / 9.0
    return df


def route_frame(detail: dict) -> pd.DataFrame:
    """The GPS points of one trip in time order: lat, long, createdOn (UTC)."""
    coords = (detail.get("tripRoute") or {}).get("tripCoordinates") or []
    df = pd.DataFrame(coords)
    if df.empty or not {"lat", "long"} <= set(df.columns):
        return pd.DataFrame(columns=ROUTE_COLUMNS[1:])
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["long"] = pd.to_numeric(df["long"], errors="coerce")
    df["createdOn"] = to_naive_utc(df["createdOn"]) if "createdOn" in df.columns else pd.NaT
    return df.dropna(subset=["lat", "long"]).sort_values("createdOn")[ROUTE_COLUMNS[1:]].reset_index(drop=True)


def _status(detail: dict, record: dict) -> str | None:
    key = GUID_NAMES.get(str(detail.get("tripStatusGuid", "")).upper())
    if key:
        return STATUS_LABELS.get(key, key)
    return client.status_name(record) if record else detail.get("tripStatusGuid")


def _round(value, digits: int = 2):
    return None if value is None or pd.isna(value) else round(float(value), digits)


def mean_kinetic_temperature(celsius: pd.Series) -> float | None:
    """MKT in Celsius from the readings (the standard formula with delta-H/R = 10000 K)."""
    kelvin = celsius.astype(float) + 273.15
    if kelvin.empty:
        return None
    return float(10000.0 / -np.log(np.exp(-10000.0 / kelvin).mean()) - 273.15)


def _reading_stats(values: pd.DataFrame, low, ideal, high) -> dict:
    """Mean, SD, min, max of one sensor's readings and -- for temperature, when the limits are known -- how long
    and by how many degree-minutes it was beyond each limit. Each reading counts for the time until the next one
    (the last one for the typical step)."""
    v = values.sort_values("dateTime")
    out = {
        "Mean Value": _round(v["value"].mean()), "Min Value": _round(v["value"].min()),
        "Max Value": _round(v["value"].max()),
        "Standard Deviation": _round(v["value"].std()) if len(v) > 1 else None,
    }
    minutes = v["dateTime"].diff().shift(-1).dt.total_seconds().div(60)
    minutes = minutes.fillna(minutes.median() if minutes.notna().any() else 15.0)
    temp = v["value"]

    def beyond(limit, above: bool):
        # Hours are whole numbers in the export; degree-minutes keep six decimals.
        if limit is None:
            return None, None
        gap = (temp - limit) if above else (limit - temp)
        hit = gap > 0
        return float(round(minutes[hit].sum() / 60)), _round((gap[hit] * minutes[hit]).sum(), 6)

    out["Time Below Low Hours"], out["Value Minutes Below Low"] = beyond(low, above=False)
    out["Time Below Ideal Hours"], out["Value Minutes Below Ideal"] = beyond(ideal, above=False)
    out["Time Above Ideal Hours"], out["Value Minutes Above Ideal"] = beyond(ideal, above=True)
    out["Time Above High Hours"], out["Value Minutes Above High"] = beyond(high, above=True)
    return out


def trip_rows(basic: dict, detail: dict, sens: pd.DataFrame, edit: dict | None = None, record: dict | None = None) -> list[dict]:
    """The audit-table rows of one trip: one per logger and sensor in TABLE_SENSORS that has readings (always at
    least one row, so a trip with no readings is not lost). `edit` holds the changes made in the app (status, departure,
    arrival), which replace what the API returned because nothing is written back to SWP; `record` is the trip's
    entry in the trip list (search result)."""
    edit = edit or {}
    record = record or {}
    origin = detail.get("tripOrigin") or {}
    flat = _flatten(detail)

    departure = edit.get("departure") or origin.get("actualDepartureTime") or client.departure_of(record)
    arrival = (
        edit.get("arrival") or detail.get("tripActualArrivalTime") or pick(detail, "destinations", "actualArrivalTime")
        or client.arrival_of(record)
    )
    segments = detail.get("segments") or []
    seg_start = departure if edit.get("departure") or not segments else (segments[0].get("startTime") or departure)
    seg_end = arrival if edit.get("arrival") or not segments else (segments[-1].get("endTime") or arrival)
    start = pd.to_datetime(departure, utc=True, errors="coerce") if departure else pd.NaT
    end = pd.to_datetime(arrival, utc=True, errors="coerce") if arrival else pd.NaT
    length_days = _round((end - start).total_seconds() / 86400) if pd.notna(start) and pd.notna(end) else None

    # Limits: the trip's own product limits, else the specification in the trip list's statistics.
    spec = pick(record, "tripStatistics", "tempSpec") or {}
    limits = {
        "low": f_to_c(_first(flat, "zoneProducts.minTemperature") if _first(flat, "zoneProducts.minTemperature") is not None else spec.get("low")),
        "ideal": f_to_c(_first(flat, "zoneProducts.idealTemperature")),
        "high": f_to_c(_first(flat, "zoneProducts.maxTemperature") if _first(flat, "zoneProducts.maxTemperature") is not None else spec.get("high")),
    }
    limits = {k: _round(v) for k, v in limits.items()}
    stats = record.get("tripStatistics") or {}

    common = {
        "Trip ID": detail.get("id") or detail.get("tripID"),
        "Trip Create Date CET": to_cet(detail.get("createDate")),
        "Trip Status": edit.get("status") or _status(detail, record),
        "Segment Name": "Full Trip",
        "Quality Status": basic.get("quality"),
        "Quality Comment": basic.get("qualityComment"),
        "Product": _first(flat, "products.productName"),
        "Origin": pick(detail, "tripOrigin", "locations", "locationName"),
        "Destination": pick(detail, "destinations", "locationName"),
        "Managing Carrier": pick(detail, "tripOrigin", "managingCarrier", "name"),
        "Carrier": pick(detail, "tripOrigin", "carrier", "name"),
        "Parent Supplier": basic.get("parentSupplierId"),
        "Order Number": pick(detail, "destinations", "orderNumber"),
        "PO Number": pick(detail, "destinations", "poNumber"),
        "Internal Trip ID": basic.get("internalTripId") or origin.get("internalTripID"),
        "Trailer ID": detail.get("trailerID"),
        "Mode Of Transportation": pick(detail, "destinations", "modeOfTransportation"),
        "Driver Name": origin.get("driverName"),
        "Driver Cell": origin.get("driverCell"),
        "Planned Departure Time CET": to_cet(origin.get("plannedDepartureTime")),
        "Actual Departure Time CET": to_cet(departure),
        "Planned Arrival Time CET": to_cet(pick(detail, "destinations", "plannedArrivalTime")),
        "Actual Arrival Time CET": to_cet(arrival),
        "Segment Length (Days)": length_days,
        "Segment Start Date Time": to_cet(seg_start),
        "Segment End Date Time": to_cet(seg_end),
        "Shipment Created Date/Time": to_cet(detail.get("createDate")),
        "Shipment Created By": record.get("createdBy"),
        "Trip Note": basic.get("notes") or detail.get("notes"),
        "Is Alarmed": None if detail.get("alarmed") is None else ("Yes" if detail.get("alarmed") else "No"),
        "SWP Trip Key": detail.get("tripID"),
        "editedInApp": ", ".join(k for k in ("status", "departure", "arrival") if edit.get(k)) or None,
    }
    # The logger of a trip without readings: from call 3 when it was fetched, else the loggers listed in the trip detail itself.
    listed_serials = [m.get("serialNumber") for c in detail.get("containers") or [] for z in c.get("zones") or []
                      for m in z.get("monitors") or [] if m.get("serialNumber")]
    default_serial = next(iter(basic.get("serialNumbers") or listed_serials), None)

    # One row per logger (serial number) and sensor, Light before Temperature -- as in the export.
    rows = []
    if not sens.empty and default_serial is not None:
        sens = sens.assign(serialNumber=sens["serialNumber"].fillna(default_serial))
    for serial in sorted(sens["serialNumber"].dropna().unique()) if not sens.empty else []:
        for sensor in sorted(TABLE_SENSORS):
            values = sens[(sens["serialNumber"] == serial) & (sens["sensor"] == sensor)]
            if values.empty:
                continue
            row = {**common, "Sensor Type": sensor, "Serial Number": serial}
            if sensor == "Temperature":
                row["Degree Unit"] = "C"
                row["Limit Low"], row["Limit Ideal"], row["Limit High"] = limits["low"], limits["ideal"], limits["high"]
                row.update(_reading_stats(values, limits["low"], limits["ideal"], limits["high"]))
                mkt = f_to_c(stats.get("mkt")) if stats.get("mkt") is not None else mean_kinetic_temperature(values["value"])
                row["MKT Statistics Value"] = _round(mkt)
            else:
                row["Degree Unit"] = "%"
                row.update({k: v for k, v in _reading_stats(values, None, None, None).items() if k in ("Mean Value", "Min Value", "Max Value", "Standard Deviation")})
            rows.append(row)
    if not rows:
        # No temperature or light readings: keep the trip with its search statistics (Fahrenheit) if there are any.
        var, reading = stats.get("tempVariance") or {}, stats.get("tempReading") or {}
        rows.append({
            **common, "Sensor Type": "Temperature", "Serial Number": default_serial, "Degree Unit": "C",
            "Limit Low": limits["low"], "Limit Ideal": limits["ideal"], "Limit High": limits["high"],
            "Mean Value": _round(f_to_c(var.get("mean"))),
            "Standard Deviation": _round(var.get("sd") * 5.0 / 9.0) if var.get("sd") is not None and config.SWP_TEMPERATURE_FAHRENHEIT else _round(var.get("sd")),
            "Min Value": _round(f_to_c(reading.get("min"))), "Max Value": _round(f_to_c(reading.get("max"))),
            "MKT Statistics Value": _round(f_to_c(stats.get("mkt"))),
        })
    return rows


_NO_READINGS = pd.DataFrame(columns=["serialNumber", "sensor", "dateTime", "value"])


def record_rows(record: dict, edit: dict | None = None) -> list[dict]:
    """The audit-table rows of one trip from its SEARCH record alone (no detail call): SWP's own trip statistics stand in
    for the numbers computed from the readings. About 40 of the 59 columns are filled; the ones that need the readings
    (the ideal-based hours and minutes, one row per logger) and the segment type and number stay empty until the detail
    is fetched. The record has the same layout as the detail for everything used here, so the detail's code is reused."""
    row = trip_rows({}, record, _NO_READINGS, edit, record)[0]   # the Temperature row, from the statistics
    stats = record.get("tripStatistics") or {}

    def whole_hours(text):
        days = duration_days(text)
        return None if days is None else float(round(days * 24))

    def degree_minutes(value):
        return None if value is None else _round(value * 5.0 / 9.0, 6)

    row["Time Below Low Hours"] = whole_hours(pick(stats, "tempTime", "below"))
    row["Time Above High Hours"] = whole_hours(pick(stats, "tempTime", "above"))
    row["Value Minutes Below Low"] = degree_minutes(pick(stats, "tempDegreeMinutes", "low"))
    row["Value Minutes Above High"] = degree_minutes(pick(stats, "tempDegreeMinutes", "high"))
    rows = [row]
    variance, reading = stats.get("lightVariance"), stats.get("lightReadings")
    if variance:
        light = {k: row[k] for k in row if k in EXPORT_COLUMNS and k not in (
            "Limit Low", "Limit Ideal", "Limit High", "Mean Value", "Standard Deviation", "Min Value", "Max Value", "MKT Statistics Value",
            "Time Below Low Hours", "Time Above High Hours", "Value Minutes Below Low", "Value Minutes Above High")}
        light.update({"Sensor Type": "Light", "Degree Unit": "%", "Mean Value": _round(variance.get("mean")),
                      "Standard Deviation": _round(variance.get("sd")),
                      "Min Value": _round((reading or {}).get("min")), "Max Value": _round((reading or {}).get("max"))})
        rows.insert(0, light)   # Light before Temperature, as in the export
    return rows


def record_table(records: list[dict], sensors: list[str] | None = None, edits: dict[str, dict] | None = None) -> pd.DataFrame:
    """The audit table for these search records (see record_rows); `sensors` and `edits` work as in build_tables."""
    keep = {s.lower() for s in sensors} if sensors else None
    out = []
    for record in records:
        rows = record_rows(record, (edits or {}).get(record["tripID"]))
        if keep is not None:
            rows = [r for r in rows if str(r["Sensor Type"]).lower() in keep] or rows[-1:]
        out += rows
    return pd.DataFrame(out).reindex(columns=EXPORT_COLUMNS)


def build_tables(
    trips_data: list[dict],
    sensors: list[str] | None = None,
    edits: dict[str, dict] | None = None,
    records: dict[str, dict] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(audit table, sensor readings, GPS route) for a list of {tripID, basic, detail}. `sensors` limits which
    sensors are kept (None = all); `edits` are the per-trip changes made in the app; `records` are the trips'
    entries in the trip list."""
    keep = {s.lower() for s in sensors} if sensors else None
    table_rows, readings, routes = [], [], []
    for t in trips_data:
        sens = sensor_frame(t["detail"])
        if keep is not None and not sens.empty:
            sens = sens[sens["sensor"].str.lower().isin(keep)]
        table_rows += trip_rows(t["basic"], t["detail"], sens, (edits or {}).get(t["tripID"]), (records or {}).get(t["tripID"]))
        if not sens.empty:
            readings.append(sens.assign(tripID=t["tripID"]))
        route = route_frame(t["detail"])
        if not route.empty:
            routes.append(route.assign(tripID=t["tripID"]))
    table = pd.DataFrame(table_rows).reindex(columns=EXPORT_COLUMNS)
    sensor_df = pd.concat(readings, ignore_index=True)[SENSOR_COLUMNS] if readings else pd.DataFrame(columns=SENSOR_COLUMNS)
    route_df = pd.concat(routes, ignore_index=True)[ROUTE_COLUMNS] if routes else pd.DataFrame(columns=ROUTE_COLUMNS)
    return table, sensor_df, route_df
