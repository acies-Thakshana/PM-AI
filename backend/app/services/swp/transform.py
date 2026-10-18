"""Turns SWP trip JSON into the tables the app uses: one aggregate row per trip (what the audit,
features and analyses run on), plus the raw sensor readings kept for the graphs."""
from __future__ import annotations

import pandas as pd

from app.services.swp.client import GUID_NAMES, STATUS_LABELS

SENSOR_LISTS = {
    "temperatureData": "Temperature", "simulatedTemperatureData": "SimulatedTemperature",
    "lightData": "Light", "humidityData": "Humidity", "co2Data": "CO2",
    "temperatureProbeData": "TemperatureProbe",
}
SENSOR_COLUMNS = ["tripID", "serialNumber", "sensor", "dateTime", "value"]


def to_naive_utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce").dt.tz_localize(None)


def pick(d, *path):
    """d[path[0]][path[1]]... where a list on the way means "its first item"; None if anything is missing."""
    for p in path:
        if isinstance(d, list):
            d = d[0] if d else None
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def sensor_frame(detail: dict) -> pd.DataFrame:
    """Long table of every sensor reading of one trip: serialNumber, sensor, dateTime (UTC), value."""
    rows = []
    for dev in detail.get("sensorData") or []:
        for key, name in SENSOR_LISTS.items():
            for p in dev.get(key) or []:
                rows.append({"serialNumber": dev.get("serialNumber"), "sensor": name,
                             "dateTime": p.get("dateTime"), "value": p.get("value")})
    df = pd.DataFrame(rows, columns=["serialNumber", "sensor", "dateTime", "value"])
    if not df.empty:
        df["dateTime"] = to_naive_utc(df["dateTime"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["dateTime", "value"]).sort_values(["serialNumber", "dateTime", "sensor"])
        df = df.reset_index(drop=True)
    return df


def _status(detail: dict) -> str | None:
    key = GUID_NAMES.get(str(detail.get("tripStatusGuid", "")).upper())
    return STATUS_LABELS.get(key, key) if key else detail.get("tripStatusGuid")


def aggregate_row(basic: dict, detail: dict, sens: pd.DataFrame) -> dict:
    row = {
        "tripID": detail.get("tripID"),
        "tripStatus": _status(detail),
        "createDate (UTC)": detail.get("createDate"),
        "lastUpdatedDate (UTC)": detail.get("lastUpdatedDate"),
        "alarmed": detail.get("alarmed"),
        "origin": pick(detail, "tripOrigin", "locations", "locationName"),
        "destination": pick(detail, "destinations", "locationName"),
        "carrier": pick(detail, "tripOrigin", "carrier", "name"),
        "modeOfTransportation": pick(detail, "destinations", "modeOfTransportation"),
        "orderNumber": pick(detail, "destinations", "orderNumber"),
        "trailerID": detail.get("trailerID"),
        "serialNumbers": ", ".join(basic.get("serialNumbers") or []),
        "actualDeparture (UTC)": pick(detail, "tripOrigin", "actualDepartureTime"),
        "actualArrival (UTC)": detail.get("tripActualArrivalTime"),
        "gpsPoints": len((detail.get("tripRoute") or {}).get("tripCoordinates") or []),
        "lastKnownAddress": pick(detail, "tripRecentData", "address"),
        "lastReadingTime": pick(detail, "tripRecentData", "time"),
    }
    if not sens.empty:
        first, last = sens["dateTime"].min(), sens["dateTime"].max()
        row["firstReading (UTC)"] = first
        row["lastReading (UTC)"] = last
        row["durationHours"] = round((last - first).total_seconds() / 3600, 2)
        for name, g in sens.groupby("sensor"):
            v = g["value"].astype(float)
            row[f"{name} count"] = len(v)
            row[f"{name} min"] = round(v.min(), 2)
            row[f"{name} max"] = round(v.max(), 2)
            row[f"{name} mean"] = round(v.mean(), 2)
            row[f"{name} stdev"] = round(v.std(), 2) if len(v) > 1 else None
    return row


def build_tables(trips_data: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(aggregate, sensors) for a list of {tripID, basic, detail}."""
    agg_rows, sensors = [], []
    for t in trips_data:
        sens = sensor_frame(t["detail"])
        agg_rows.append(aggregate_row(t["basic"], t["detail"], sens))
        if not sens.empty:
            sensors.append(sens.assign(tripID=t["tripID"]))
    agg = pd.DataFrame(agg_rows).dropna(axis=1, how="all")
    sensor_df = pd.concat(sensors, ignore_index=True)[SENSOR_COLUMNS] if sensors else pd.DataFrame(columns=SENSOR_COLUMNS)
    return agg, sensor_df
