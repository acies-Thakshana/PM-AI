"""
Simulates a SensiWatch platform export (Trip_Header + Sensor_Readings) for one
customer, Belvoire Chocolatier. Every trip is "In Transit" -- SensiWatch is a
real-time platform, so a trip only ever gets a TripStatus of "In Transit" from
the device feed itself; "Closed" is a status a PM sets by hand after review,
which is exactly the manual step this whole pipeline exists to avoid. Two
distinct behaviors are modeled:

  - "active": recently dispatched, genuinely still moving -- last GPS reading
    reflects real elapsed time, always fresh as of "now".
  - "stale": dispatched long enough ago that the trip should have concluded,
    but was never manually closed. Some have a last-known GPS reading sitting
    right at the destination (should have been closed -- the exact "did it
    actually arrive" check the client wants), one is genuinely stalled
    mid-route (a real structural problem worth flagging to the customer).

This module only builds the DataFrames -- writing the workbook is the
orchestrator's job (scripts/simulate_all_data.py) so every simulator stays
independently testable.
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from app.services.sites import SITES

RNG = np.random.default_rng(7)
NOW = datetime.utcnow()

CUSTOMER = "Belvoire Chocolatier"

PRODUCT_SPECS = {
    "Dark Chocolate Couverture 70%": dict(temp_min=15.0, temp_max=18.0, humidity_min=30, humidity_max=55),
    "Milk Chocolate Pralines": dict(temp_min=16.0, temp_max=18.0, humidity_min=30, humidity_max=50),
    "Cocoa Butter Blocks": dict(temp_min=16.0, temp_max=20.0, humidity_min=30, humidity_max=60),
}

INTERVAL_OPTIONS_MIN = [15, 30, 60, 360]  # matches the call: "anywhere between ~50 min and 6 hours"
INTERVAL_WEIGHTS = [0.15, 0.35, 0.35, 0.15]
DWELL_INTERVAL_MIN = 720  # coarser heartbeat cadence once a monitor is idle/stationary
MAX_DWELL_READINGS = 8


def _lerp_point(a, b, t):
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def _build_trip_scenarios():
    """Explicit scenario list so we control exactly which triage problems show
    up, rather than leaving it to chance. `kind="active"` trips compute their
    last-known position from real elapsed time (still genuinely moving);
    `kind="stale"` trips use an explicit stalled `gps_progress` and then idle
    in place -- the created_days_ago has run well past the trip's own
    transit_hours, which is what actually makes them look overdue."""
    scenarios = []
    counter = 1

    def add(product, origin, destination, dispatch_days_ago, transit_hours, kind,
             gps_progress=None, created_days_ago=None):
        nonlocal counter
        scenarios.append(dict(
            trip_id=f"SW-2026-{counter:04d}", product=product, origin=origin, destination=destination,
            dispatch_days_ago=dispatch_days_ago, transit_hours=transit_hours, kind=kind,
            gps_progress=gps_progress,
            created_days_ago=created_days_ago if created_days_ago is not None else dispatch_days_ago + 0.3,
        ))
        counter += 1

    # -- active: dispatched recently, elapsed time is still well within the
    # trip's own transit_hours, so it's genuinely still en route (9) --
    add("Dark Chocolate Couverture 70%", "Turin Production Facility", "Rotterdam Distribution Hub", 1.0, 30, "active")
    add("Milk Chocolate Pralines", "Antwerp Cocoa Processing Plant", "Frankfurt Regional DC", 0.3, 14, "active")
    add("Cocoa Butter Blocks", "Turin Production Facility", "Milan Distribution Center", 0.15, 9, "active")
    add("Dark Chocolate Couverture 70%", "Antwerp Cocoa Processing Plant", "Lyon Cold Storage", 0.4, 16, "active")
    add("Milk Chocolate Pralines", "Turin Production Facility", "Vienna Regional DC", 0.1, 20, "active")
    add("Cocoa Butter Blocks", "Antwerp Cocoa Processing Plant", "Rotterdam Distribution Hub", 0.35, 11, "active")
    add("Dark Chocolate Couverture 70%", "Turin Production Facility", "Frankfurt Regional DC", 0.6, 19, "active")
    add("Milk Chocolate Pralines", "Antwerp Cocoa Processing Plant", "Milan Distribution Center", 0.7, 22, "active")
    add("Cocoa Butter Blocks", "Turin Production Facility", "Lyon Cold Storage", 0.25, 13, "active")

    # -- stale, GPS-only (no customer confirmation in the profile doc) -- shows
    # the triage still works without a customer cross-check (2) --
    add("Dark Chocolate Couverture 70%", "Antwerp Cocoa Processing Plant", "Vienna Regional DC", 19, 21, "stale",
        gps_progress=1.0, created_days_ago=19)
    add("Milk Chocolate Pralines", "Turin Production Facility", "Rotterdam Distribution Hub", 18, 15, "stale",
        gps_progress=0.45, created_days_ago=18)

    # -- stale, GPS at destination, ALSO customer-confirmed arrived (matches
    # belvoire_customer_profile.md's Confirmed Delivery Log) (2) --
    add("Cocoa Butter Blocks", "Turin Production Facility", "Frankfurt Regional DC", 35, 18, "stale",
        gps_progress=1.0, created_days_ago=36)
    add("Dark Chocolate Couverture 70%", "Antwerp Cocoa Processing Plant", "Milan Distribution Center", 28, 21, "stale",
        gps_progress=1.0, created_days_ago=29)

    # -- stale, GPS stalled mid-route, customer-confirmed NOT arrived (matches
    # the profile doc) -- a genuine structural problem (1) --
    add("Milk Chocolate Pralines", "Turin Production Facility", "Lyon Cold Storage", 22, 13, "stale",
        gps_progress=0.62, created_days_ago=23)

    return scenarios


def _generate_trip(scenario, reading_id_start):
    product = scenario["product"]
    spec = PRODUCT_SPECS[product]
    origin_coord = SITES[scenario["origin"]]
    dest_coord = SITES[scenario["destination"]]

    dispatch = NOW - timedelta(days=scenario["dispatch_days_ago"])
    created = NOW - timedelta(days=scenario["created_days_ago"])
    interval_min = int(RNG.choice(INTERVAL_OPTIONS_MIN, p=INTERVAL_WEIGHTS))
    transit_hours = scenario["transit_hours"]
    monitor_id = f"SW-MON-{RNG.integers(1000, 9999)}"

    if scenario["kind"] == "active":
        # still genuinely moving -- last known position reflects real elapsed time
        elapsed_hours = scenario["dispatch_days_ago"] * 24
        transit_end_progress = min(elapsed_hours / transit_hours, 0.97)
    else:
        transit_end_progress = scenario["gps_progress"]

    readings = []
    reading_id = reading_id_start

    # transit leg: from dispatch, moving from origin -> destination
    n_transit_points = max(3, int(transit_hours * 60 / interval_min * transit_end_progress))
    for i in range(n_transit_points):
        progress = (i / max(n_transit_points - 1, 1)) * transit_end_progress
        ts = dispatch + timedelta(minutes=interval_min * i)
        lat, lon = _lerp_point(origin_coord, dest_coord, progress)
        temp = float(np.clip(RNG.uniform(spec["temp_min"], spec["temp_max"]) + RNG.uniform(-0.3, 0.3),
                              spec["temp_min"] - 1, spec["temp_max"] + 1))
        humidity = float(np.clip(RNG.uniform(spec["humidity_min"], spec["humidity_max"]), 20, 100))
        light = float(RNG.choice([RNG.uniform(0, 4), RNG.uniform(50, 300)], p=None)) if RNG.random() < 0.06 else float(RNG.uniform(0, 4))
        readings.append(dict(ReadingID=f"SW-RD-{reading_id:05d}", TripID=scenario["trip_id"], Timestamp=ts,
                              TemperatureC=round(temp, 2), HumidityPct=round(humidity, 1),
                              LightLux=round(light, 1), Lat=round(lat, 4), Lon=round(lon, 4)))
        reading_id += 1

    # dwell leg: only kicks in for "stale" trips -- for "active" trips the transit
    # leg above already runs right up to "now", so dwell_span_hours comes out ~0
    # and no dwell readings get added (the monitor is idle at its last position,
    # coarse heartbeat, continuing up to "now" so the export genuinely looks
    # unresolved rather than freshly stopped)
    dwell_start = dispatch + timedelta(hours=transit_hours * transit_end_progress)
    dwell_span_hours = max(0.0, (NOW - dwell_start).total_seconds() / 3600)
    n_dwell = min(MAX_DWELL_READINGS, int(dwell_span_hours * 60 / DWELL_INTERVAL_MIN))
    lat, lon = _lerp_point(origin_coord, dest_coord, transit_end_progress)
    for j in range(n_dwell):
        ts = dwell_start + timedelta(minutes=DWELL_INTERVAL_MIN * (j + 1))
        if ts > NOW:
            break
        temp = float(np.clip(spec["temp_max"] + RNG.uniform(-0.5, 2.5), spec["temp_min"] - 1, spec["temp_max"] + 4))
        humidity = float(np.clip(RNG.uniform(spec["humidity_min"], spec["humidity_max"] + 5), 20, 100))
        readings.append(dict(ReadingID=f"SW-RD-{reading_id:05d}", TripID=scenario["trip_id"], Timestamp=ts,
                              TemperatureC=round(temp, 2), HumidityPct=round(humidity, 1),
                              LightLux=round(float(RNG.uniform(0, 3)), 1), Lat=round(lat, 4), Lon=round(lon, 4)))
        reading_id += 1

    header = dict(
        TripID=scenario["trip_id"], Customer=CUSTOMER, Product=product,
        OriginSite=scenario["origin"], DestinationSite=scenario["destination"],
        DestinationLat=dest_coord[0], DestinationLon=dest_coord[1],
        MonitorID=monitor_id, ReportingIntervalMinutes=interval_min,
        CreatedDate=created, DepartureDateTime=dispatch, ArrivalDateTime=None,
        TripStatus="In Transit",
        TargetTempMinC=spec["temp_min"], TargetTempMaxC=spec["temp_max"],
        TargetHumidityMinPct=spec["humidity_min"], TargetHumidityMaxPct=spec["humidity_max"],
    )
    return header, readings, reading_id


def generate() -> dict[str, pd.DataFrame]:
    scenarios = _build_trip_scenarios()
    headers = []
    all_readings = []
    reading_id = 1
    for scenario in scenarios:
        header, readings, reading_id = _generate_trip(scenario, reading_id)
        headers.append(header)
        all_readings.extend(readings)

    return {
        "Trip_Header": pd.DataFrame(headers),
        "Sensor_Readings": pd.DataFrame(all_readings),
    }
