"""For each column of the aggregate file: which API call can fill it, the field in each, and whether the two agree.

Calls: 2 = trip search (the "record"), 4 = trip detail (the raw data with the readings). Call 3 (get trip) is mentioned
in the notes only, since everything it holds is empty or also in the detail.

`matrix()` returns one row per aggregate column:
  [column, field in 2, field in 4, available in, values agree (arrived trips), note]
"Available in" is Both / Search (2) only / Detail (4) only / Get trip (3) only / Neither. "Values agree" is measured on the
stored trips that are Arrived and have both a search record and a detail: the value taken from the search record is
compared with the value taken from the detail (computed from its readings where that is how the column is made).
"""
from __future__ import annotations

import re

import pandas as pd

from app.services.swp import client
from app.services.swp.transform import _flatten, _first, _reading_stats, f_to_c, pick, sensor_frame, to_cet


def _days(text):
    """'3.17:00:00' -> 3.708 days."""
    m = re.match(r"(?:(\d+)\.)?(\d+):(\d+):(\d+)", text or "")
    if not m:
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d + h / 24 + mi / 1440 + s / 86400


def _hours(text):
    days = _days(text)
    return None if days is None else days * 24


def _first_of(lst, *path):
    return pick(lst, *path)


def _temps(detail):
    sens = sensor_frame(detail)
    return sens[sens["sensor"] == "Temperature"]["value"] if not sens.empty else pd.Series(dtype=float)


def _lights(detail):
    sens = sensor_frame(detail)
    return sens[sens["sensor"] == "Light"]["value"] if not sens.empty else pd.Series(dtype=float)


def _serials_record(r):
    return sorted({m.get("serialNumber") for c in r.get("containers") or [] for z in c.get("zones") or [] for m in z.get("monitors") or [] if m.get("serialNumber")})


def _serials_detail(d):
    return sorted({dev.get("serialNumber") for dev in d.get("sensorData") or [] if dev.get("serialNumber")})


def _time(value):
    return to_cet(value)


def _mean(series, fn=lambda x: x):
    return None if series.empty else fn(series.mean())


def _std(series, scale=1.0):
    return None if len(series) < 2 else series.std() * scale


def _limit(detail, key):
    return f_to_c(_first(_flatten(detail), f"zoneProducts.{key}"))


def _beyond(detail, column):
    """A 'Time ... Hours' / 'Value Minutes ...' column computed from the detail's temperature readings and limits."""
    sens = sensor_frame(detail)
    values = sens[sens["sensor"] == "Temperature"] if not sens.empty else sens
    if values.empty:
        return None
    return _reading_stats(values, _limit(detail, "minTemperature"), _limit(detail, "idealTemperature"), _limit(detail, "maxTemperature")).get(column)


def _scaled(value, factor):
    return None if value is None else value * factor


# column -> (value from the search record, value from the detail, kind, tolerance).
# kind: text | num (absolute tolerance) | rel (within 5% or 1 unit) | time | list
COMPARE = {
    "Serial Number": (_serials_record, _serials_detail, "list", 0),
    "Trip ID": (lambda r: r.get("id"), lambda d: d.get("id"), "num", 0),
    "Trip Create Date CET": (lambda r: _time(r.get("createDate")), lambda d: _time(d.get("createDate")), "time", 0),
    "Trip Status": (client.status_name, lambda d: client.status_name({"tripStatusGuid": d.get("tripStatusGuid")}), "text", 0),
    "Product": (lambda r: _first(_flatten(r), "products.productName"), lambda d: _first(_flatten(d), "products.productName"), "text", 0),
    "Origin": (lambda r: pick(r, "tripOrigin", "locations", "locationName"), lambda d: pick(d, "tripOrigin", "locations", "locationName"), "text", 0),
    "Destination": (lambda r: pick(r, "destinations", "locationName"), lambda d: pick(d, "destinations", "locationName"), "text", 0),
    "Managing Carrier": (lambda r: pick(r, "tripOrigin", "managingCarrier", "name"), lambda d: pick(d, "tripOrigin", "managingCarrier", "name"), "text", 0),
    "Carrier": (lambda r: pick(r, "tripOrigin", "carrier", "name"), lambda d: pick(d, "tripOrigin", "carrier", "name"), "text", 0),
    "Order Number": (lambda r: pick(r, "destinations", "orderNumber"), lambda d: pick(d, "destinations", "orderNumber"), "text", 0),
    "PO Number": (lambda r: pick(r, "destinations", "poNumber"), lambda d: pick(d, "destinations", "poNumber"), "text", 0),
    "Internal Trip ID": (lambda r: pick(r, "tripOrigin", "internalTripID"), lambda d: pick(d, "tripOrigin", "internalTripID"), "text", 0),
    "Trailer ID": (lambda r: r.get("trailerID"), lambda d: d.get("trailerID"), "text", 0),
    "Mode Of Transportation": (lambda r: pick(r, "destinations", "modeOfTransportation"), lambda d: pick(d, "destinations", "modeOfTransportation"), "text", 0),
    "Driver Name": (lambda r: pick(r, "tripOrigin", "driverName"), lambda d: pick(d, "tripOrigin", "driverName"), "text", 0),
    "Driver Cell": (lambda r: pick(r, "tripOrigin", "driverCell"), lambda d: pick(d, "tripOrigin", "driverCell"), "text", 0),
    "Planned Departure Time CET": (lambda r: _time(pick(r, "tripOrigin", "plannedDepartureTime")), lambda d: _time(pick(d, "tripOrigin", "plannedDepartureTime")), "time", 0),
    "Actual Departure Time CET": (lambda r: _time(pick(r, "tripOrigin", "actualDepartureTime")), lambda d: _time(pick(d, "tripOrigin", "actualDepartureTime")), "time", 0),
    "Planned Arrival Time CET": (lambda r: _time(pick(r, "destinations", "plannedArrivalTime")), lambda d: _time(pick(d, "destinations", "plannedArrivalTime")), "time", 0),
    "Actual Arrival Time CET": (lambda r: _time(r.get("tripActualArrivalTime")), lambda d: _time(d.get("tripActualArrivalTime")), "time", 0),
    "Segment Length (Days)": (
        lambda r: _days(r.get("tripLength")),
        lambda d: None if not (pick(d, "tripOrigin", "actualDepartureTime") and d.get("tripActualArrivalTime")) else
        (pd.to_datetime(d["tripActualArrivalTime"], utc=True) - pd.to_datetime(pick(d, "tripOrigin", "actualDepartureTime"), utc=True)).total_seconds() / 86400,
        "num", 0.01),
    "Container Name": (lambda r: pick(r, "containers", "containerName"), lambda d: pick(d, "containers", "containerName"), "text", 0),
    "Zone Name": (lambda r: pick(r, "containers", "zones", "zoneName"), lambda d: pick(d, "containers", "zones", "zoneName"), "text", 0),
    "Limit Low": (lambda r: f_to_c(_first(_flatten(r), "zoneProducts.minTemperature")), lambda d: f_to_c(_first(_flatten(d), "zoneProducts.minTemperature")), "num", 0.01),
    "Limit Ideal": (lambda r: f_to_c(_first(_flatten(r), "zoneProducts.idealTemperature")), lambda d: f_to_c(_first(_flatten(d), "zoneProducts.idealTemperature")), "num", 0.01),
    "Limit High": (lambda r: f_to_c(_first(_flatten(r), "zoneProducts.maxTemperature")), lambda d: f_to_c(_first(_flatten(d), "zoneProducts.maxTemperature")), "num", 0.01),
    "Mean Value": (lambda r: f_to_c(pick(r, "tripStatistics", "tempVariance", "mean")), lambda d: _mean(_temps(d)), "num", 0.05),
    "Standard Deviation": (
        lambda r: None if pick(r, "tripStatistics", "tempVariance", "sd") is None else pick(r, "tripStatistics", "tempVariance", "sd") * 5 / 9,
        lambda d: _std(_temps(d)), "num", 0.05),
    "Min Value": (lambda r: f_to_c(pick(r, "tripStatistics", "tempReading", "min")), lambda d: None if _temps(d).empty else _temps(d).min(), "num", 0.05),
    "Max Value": (lambda r: f_to_c(pick(r, "tripStatistics", "tempReading", "max")), lambda d: None if _temps(d).empty else _temps(d).max(), "num", 0.05),
    "Time Below Low Hours": (lambda r: _hours(pick(r, "tripStatistics", "tempTime", "below")), lambda d: _beyond(d, "Time Below Low Hours"), "num", 1.0),
    "Time Above High Hours": (lambda r: _hours(pick(r, "tripStatistics", "tempTime", "above")), lambda d: _beyond(d, "Time Above High Hours"), "num", 1.0),
    "Value Minutes Below Low": (lambda r: _scaled(pick(r, "tripStatistics", "tempDegreeMinutes", "low"), 5 / 9), lambda d: _beyond(d, "Value Minutes Below Low"), "rel", 0),
    "Value Minutes Above High": (lambda r: _scaled(pick(r, "tripStatistics", "tempDegreeMinutes", "high"), 5 / 9), lambda d: _beyond(d, "Value Minutes Above High"), "rel", 0),
}

# column -> (field in the search record, field in the detail, available in, note). Columns not in COMPARE are not compared.
MATRIX = [
    ("Serial Number", "containers[].zones[].monitors[].serialNumber", "sensorData[].serialNumber (also containers[].zones[].monitors[].serialNumber)", "Both", "the app writes one row per logger; call 3 serialNumbers[] has the same serials"),
    ("Trip ID", "id", "id", "Both", "numeric Trip ID"),
    ("Trip Detail", "-", "-", "Neither", "empty in the export"),
    ("Trip Create Date CET", "createDate", "createDate", "Both", "UTC to CET"),
    ("Trip Status", "tripStatus (text)", "tripStatusGuid (a GUID that maps to the text)", "Both", "the search gives the text directly"),
    ("Segment Name", "-", "segments[].segmentName (per-leg names)", "Neither", "the app writes the constant 'Full Trip'"),
    ("Quality Status", "-", "-", "Get trip (3) only", "quality, null for every trip"),
    ("Quality Comment", "-", "-", "Get trip (3) only", "qualityComment, null for every trip"),
    ("Product", "destinations[].products[].productName", "destinations[].products[].productName", "Both", "empty for a trip without a product"),
    ("Origin", "tripOrigin.locations[].locationName", "tripOrigin.locations.locationName", "Both", ""),
    ("Destination", "destinations[].locationName", "destinations[].locationName", "Both", ""),
    ("Managing Carrier", "tripOrigin.managingCarrier", "tripOrigin.managingCarrier", "Both", "null for every trip"),
    ("Carrier", "tripOrigin.carrier.name", "tripOrigin.carrier.name", "Both", ""),
    ("Parent Supplier", "tripOrigin.parentSupplier", "parentSupplierId", "Both", "null for every trip (an ID only; a name needs the Admin API)"),
    ("Order Number", "destinations[].orderNumber", "destinations[].orderNumber", "Both", ""),
    ("PO Number", "destinations[].poNumber", "destinations[].poNumber", "Both", ""),
    ("Internal Trip ID", "tripOrigin.internalTripID", "tripOrigin.internalTripID", "Both", "also in call 3 as internalTripId"),
    ("Trailer ID", "trailerID", "trailerID", "Both", ""),
    ("Mode Of Transportation", "destinations[].modeOfTransportation", "destinations[].modeOfTransportation", "Both", ""),
    ("Driver Name", "tripOrigin.driverName", "tripOrigin.driverName", "Both", ""),
    ("Driver Cell", "tripOrigin.driverCell", "tripOrigin.driverCell", "Both", ""),
    ("Planned Departure Time CET", "tripOrigin.plannedDepartureTime", "tripOrigin.plannedDepartureTime", "Both", "UTC to CET"),
    ("Actual Departure Time CET", "tripOrigin.actualDepartureTime", "tripOrigin.actualDepartureTime", "Both", "UTC to CET"),
    ("Planned Arrival Time CET", "destinations[].plannedArrivalTime", "destinations[].plannedArrivalTime", "Both", "UTC to CET"),
    ("Actual Arrival Time CET", "tripActualArrivalTime", "tripActualArrivalTime", "Both", "UTC to CET"),
    ("Segment Length (Days)", "tripLength (text 'd.hh:mm:ss')", "actual arrival minus actual departure", "Both", "days; for a trip still on its way the search value is as of the moment of the call"),
    ("Container Name", "containers[].containerName", "containers[].containerName", "Both", "empty in the export; the app does not fill it yet"),
    ("Zone Name", "containers[].zones[].zoneName", "containers[].zones[].zoneName", "Both", "empty in the export; the app does not fill it yet"),
    ("Segment Type", "-", "segments[].segmentType", "Detail (4) only", "empty in the export; the app does not fill it yet"),
    ("Segment Number", "-", "segments[].segmentNumber", "Detail (4) only", "empty in the export; the app does not fill it yet"),
    ("Segment Start Date Time", "tripOrigin.actualDepartureTime (same instant)", "segments[0].startTime", "Both", "equals the actual departure"),
    ("Segment End Date Time", "tripActualArrivalTime (same instant)", "segments[-1].endTime", "Both", "equals the actual arrival"),
    ("Sensor Type", "tripStatistics.availableSensor (hasTemperature, hasLight)", "sensorData[].temperatureData / lightData", "Both", "one row per sensor"),
    ("Degree Unit", "-", "-", "Neither", "constant: C for Temperature, % for Light"),
    ("Limit Low", "containers[].zones[].zoneProducts[].minTemperature; tripStatistics.tempSpec.low", "containers[].zones[].zoneProducts[].minTemperature", "Both", "Fahrenheit to Celsius; empty for a trip without a product"),
    ("Limit Ideal", "containers[].zones[].zoneProducts[].idealTemperature", "containers[].zones[].zoneProducts[].idealTemperature", "Both", "Fahrenheit to Celsius"),
    ("Limit High", "containers[].zones[].zoneProducts[].maxTemperature; tripStatistics.tempSpec.high", "containers[].zones[].zoneProducts[].maxTemperature", "Both", "Fahrenheit to Celsius"),
    ("Mean Value", "tripStatistics.tempVariance.mean (Light: lightVariance.mean)", "mean of sensorData[].temperatureData[].value (Light: lightData)", "Both", "search value is SWP's own, in Fahrenheit; for the detail it is computed"),
    ("Standard Deviation", "tripStatistics.tempVariance.sd (Light: lightVariance.sd)", "standard deviation of the readings", "Both", "Fahrenheit scale: multiply by 5/9"),
    ("Min Value", "tripStatistics.tempReading.min (Light: lightReadings.min)", "minimum of the readings", "Both", "Fahrenheit to Celsius"),
    ("Max Value", "tripStatistics.tempReading.max (Light: lightReadings.max)", "maximum of the readings", "Both", "Fahrenheit to Celsius"),
    ("MKT Statistics Value", "tripStatistics.mkt", "computed from the temperature readings", "Both", "search value is null for some trips; Fahrenheit to Celsius"),
    ("Time Below Low Hours", "tripStatistics.tempTime.below (text 'd.hh:mm:ss')", "readings below Limit Low, counted in time", "Both", "the export shows whole hours"),
    ("Time Below Ideal Hours", "-", "readings below Limit Ideal, counted in time", "Detail (4) only", "the search only has the low and high spec, not the ideal"),
    ("Time Above Ideal Hours", "-", "readings above Limit Ideal, counted in time", "Detail (4) only", "the search only has the low and high spec, not the ideal"),
    ("Time Above High Hours", "tripStatistics.tempTime.above (text 'd.hh:mm:ss')", "readings above Limit High, counted in time", "Both", "the export shows whole hours"),
    ("Value Minutes Below Low", "tripStatistics.tempDegreeMinutes.low", "degrees below Limit Low times minutes", "Both", "search value in Fahrenheit degree-minutes: multiply by 5/9"),
    ("Value Minutes Below Ideal", "-", "degrees below Limit Ideal times minutes", "Detail (4) only", "needs the ideal and the readings"),
    ("Value Minutes Above Ideal", "-", "degrees above Limit Ideal times minutes", "Detail (4) only", "needs the ideal and the readings"),
    ("Value Minutes Above High", "tripStatistics.tempDegreeMinutes.high", "degrees above Limit High times minutes", "Both", "search value in Fahrenheit degree-minutes: multiply by 5/9"),
    ("Specs Last Updated Date/Time", "-", "-", "Neither", "not in the trip calls"),
    ("Shipment Created Date/Time", "createDate", "createDate", "Both", "UTC to CET"),
    ("Shipment Created By", "createdBy", "-", "Search (2) only", "not in the detail or in call 3"),
    ("Trip Note", "notes", "notes", "Both", "also in call 3"),
    ("Latest Reprocess Date", "-", "-", "Neither", "empty in the export"),
    ("Latest Reprocess User", "-", "-", "Neither", "empty in the export"),
    ("Reprocess Type", "-", "-", "Neither", "empty in the export"),
    ("Is Alarmed", "alarmed", "alarmed", "Both", "true/false to Yes/No"),
    ("Trip Review", "-", "-", "Neither", "empty in the export"),
]


def _same(kind: str, a, b, tol: float) -> bool:
    empty_a = a is None or (isinstance(a, float) and pd.isna(a)) or a == ""
    empty_b = b is None or (isinstance(b, float) and pd.isna(b)) or b == ""
    if empty_a or empty_b:
        return empty_a and empty_b
    if kind == "num":
        return abs(float(a) - float(b)) <= max(tol, 1e-9)
    if kind == "rel":
        return abs(float(a) - float(b)) <= max(1.0, 0.05 * max(abs(float(a)), abs(float(b))))
    if kind == "text":
        return str(a).strip() == str(b).strip()
    return a == b


def agreement(payloads: list[dict]) -> dict[str, str]:
    """column -> 'n of m agree' over the Arrived trips that have both a search record and a detail."""
    pairs = [(p["record"], p["detail"]) for p in payloads if p.get("record") and p.get("detail") and client.status_name(p["record"]) == "Arrived"]
    out: dict[str, str] = {}
    for column, (search_fn, detail_fn, kind, tol) in COMPARE.items():
        agree = filled = 0
        for record, detail in pairs:
            try:
                a, b = search_fn(record), detail_fn(detail)
            except Exception:  # noqa: BLE001 - a record with an unexpected shape counts as a disagreement
                a, b = "?", None
            if _same(kind, a, b, tol):
                agree += 1
                filled += 0 if (a is None or a == "" or (isinstance(a, list) and not a)) else 1
        total = len(pairs)
        if total == 0:
            out[column] = "no arrived trips with both"
        elif filled == 0:
            out[column] = f"{agree} of {total} (empty in both)"
        else:
            out[column] = f"{agree} of {total} agree ({filled} with a value)"
    return out


def matrix(payloads: list[dict]) -> list[list]:
    checked = agreement(payloads)
    return [[column, search, detail, where, checked.get(column, "-"), note] for column, search, detail, where, note in MATRIX]
