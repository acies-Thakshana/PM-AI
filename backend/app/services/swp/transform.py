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
ROUTE_COLUMNS = ["tripID", "lat", "long", "createdOn"]


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


def product_of(detail: dict) -> tuple[str | None, str | None]:
    """(product name, product id) of a trip, found by field name because the detail's layout for products is not
    documented: a text field with "product" and "name" in its path, and a field ending in "productId"."""
    name = pid = None
    for key, value in _flatten(detail).items():
        low = key.lower()
        if name is None and "product" in low and "name" in low and isinstance(value, str) and value.strip():
            name = value.strip()
        if pid is None and low.endswith("productid") and value not in (None, "", -1, 0):
            pid = str(value)
    return name, pid


def _status(detail: dict) -> str | None:
    key = GUID_NAMES.get(str(detail.get("tripStatusGuid", "")).upper())
    return STATUS_LABELS.get(key, key) if key else detail.get("tripStatusGuid")


def aggregate_row(
    basic: dict,
    detail: dict,
    sens: pd.DataFrame,
    edit: dict | None = None,
    listed: dict | None = None,
    products: dict[str, dict] | None = None,
) -> dict:
    """`edit` holds the changes made in the app for this trip (status, departure, arrival): they replace
    what the API returned, because nothing is written back to SWP."""
    edit = edit or {}
    listed = listed or {}   # departure / arrival as the trip list showed them, for when the detail has none
    # Column names the outlier checks look for: Origin, Destination, Product, Segment Length (Days), the
    # *_Temperature statistics and Limit Low / High / Ideal_Temperature.
    product_name, product_id = product_of(detail)
    product = (products or {}).get(product_id or "", {})
    row = {
        "tripID": detail.get("tripID"),
        "tripStatus": edit.get("status") or _status(detail),
        "createDate (UTC)": detail.get("createDate"),
        "lastUpdatedDate (UTC)": detail.get("lastUpdatedDate"),
        "alarmed": detail.get("alarmed"),
        "Origin": pick(detail, "tripOrigin", "locations", "locationName"),
        "Destination": pick(detail, "destinations", "locationName"),
        "Carrier": pick(detail, "tripOrigin", "carrier", "name"),
        "Product": product_name or product.get("name"),
        "Limit Low_Temperature": product.get("low"),
        "Limit High_Temperature": product.get("high"),
        "Limit Ideal_Temperature": product.get("ideal"),
        "modeOfTransportation": pick(detail, "destinations", "modeOfTransportation"),
        "orderNumber": pick(detail, "destinations", "orderNumber"),
        "trailerID": detail.get("trailerID"),
        "serialNumbers": ", ".join(basic.get("serialNumbers") or []),
        "actualDeparture (UTC)": edit.get("departure") or pick(detail, "tripOrigin", "actualDepartureTime") or listed.get("departure"),
        "actualArrival (UTC)": edit.get("arrival") or detail.get("tripActualArrivalTime") or listed.get("arrival"),
        "gpsPoints": len((detail.get("tripRoute") or {}).get("tripCoordinates") or []),
        "lastKnownAddress": pick(detail, "tripRecentData", "address"),
        "lastReadingTime": pick(detail, "tripRecentData", "time"),
    }
    if edit:
        row["editedInApp"] = ", ".join(k for k in ("status", "departure", "arrival") if edit.get(k))
    start = pd.to_datetime(row["actualDeparture (UTC)"], utc=True, errors="coerce")
    end = pd.to_datetime(row["actualArrival (UTC)"], utc=True, errors="coerce")
    if pd.notna(start) and pd.notna(end):
        row["Segment Length (Days)"] = round((end - start).total_seconds() / 86400, 2)
    if not sens.empty:
        first, last = sens["dateTime"].min(), sens["dateTime"].max()
        row["firstReading (UTC)"] = first
        row["lastReading (UTC)"] = last
        row["durationHours"] = round((last - first).total_seconds() / 3600, 2)
        for name, g in sens.groupby("sensor"):
            v = g["value"].astype(float)
            stats = {
                "count": len(v), "min": round(v.min(), 2), "max": round(v.max(), 2), "mean": round(v.mean(), 2),
                "stdev": round(v.std(), 2) if len(v) > 1 else None,
            }
            row[f"{name} count"] = stats["count"]
            if name == "Temperature":
                row["Min Value_Temperature"] = stats["min"]
                row["Max Value_Temperature"] = stats["max"]
                row["Mean Value_Temperature"] = stats["mean"]
                row["Standard Deviation_Temperature"] = stats["stdev"]
            else:
                row[f"{name} min"], row[f"{name} max"] = stats["min"], stats["max"]
                row[f"{name} mean"], row[f"{name} stdev"] = stats["mean"], stats["stdev"]
    return row


def build_tables(
    trips_data: list[dict],
    sensors: list[str] | None = None,
    edits: dict[str, dict] | None = None,
    listed: dict[str, dict] | None = None,
    products: dict[str, dict] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(aggregate, sensor readings, GPS route) for a list of {tripID, basic, detail}. `sensors` limits
    which sensors are kept (None = all); `edits` are the per-trip changes made in the app."""
    keep = {s.lower() for s in sensors} if sensors else None
    agg_rows, readings, routes = [], [], []
    for t in trips_data:
        sens = sensor_frame(t["detail"])
        if keep is not None:
            sens = sens[sens["sensor"].str.lower().isin(keep)]
        agg_rows.append(aggregate_row(t["basic"], t["detail"], sens, (edits or {}).get(t["tripID"]), (listed or {}).get(t["tripID"]), products))
        if not sens.empty:
            readings.append(sens.assign(tripID=t["tripID"]))
        route = route_frame(t["detail"])
        if not route.empty:
            routes.append(route.assign(tripID=t["tripID"]))
    agg = pd.DataFrame(agg_rows).dropna(axis=1, how="all")
    sensor_df = pd.concat(readings, ignore_index=True)[SENSOR_COLUMNS] if readings else pd.DataFrame(columns=SENSOR_COLUMNS)
    route_df = pd.concat(routes, ignore_index=True)[ROUTE_COLUMNS] if routes else pd.DataFrame(columns=ROUTE_COLUMNS)
    return agg, sensor_df, route_df
