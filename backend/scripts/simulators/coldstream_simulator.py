"""
Simulates a ColdStream export for the same customer (Belvoire Chocolatier).

NOTE: this schema is an assumption, not a confirmed spec -- the discovery call
only described ColdStream secondhand ("a report on the raw data... look for
statistical outliers... extremely short or extremely long trips... temperature
values which doesn't make any sense... we might set a proper end date, a
proper start date... we might even delete trips"). Modeled as a simpler
periodic data logger: coarser readings, no GPS, no light sensor -- unlike
SensiWatch it isn't real-time, so there's no live "still in transit" state,
only trip records with (sometimes bad) start/end dates. Flag this file if the
real ColdStream schema turns out to differ.
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from scripts.simulators.sensiwatch_simulator import CUSTOMER, PRODUCT_SPECS

RNG = np.random.default_rng(23)
NOW = datetime.utcnow()


def _build_trip_scenarios():
    scenarios = []
    counter = 1

    def add(product, origin, destination, start_days_ago, duration_days, data_quality="clean"):
        nonlocal counter
        scenarios.append(dict(
            trip_id=f"CS-2026-{counter:04d}", product=product, origin=origin, destination=destination,
            start_days_ago=start_days_ago, duration_days=duration_days, data_quality=data_quality,
        ))
        counter += 1

    # -- clean trips (5) --
    add("Dark Chocolate Couverture 70%", "Turin Production Facility", "Milan Distribution Center", 25, 3.2)
    add("Cocoa Butter Blocks", "Antwerp Cocoa Processing Plant", "Rotterdam Distribution Hub", 19, 1.8)
    add("Milk Chocolate Pralines", "Turin Production Facility", "Lyon Cold Storage", 16, 2.6)
    add("Dark Chocolate Couverture 70%", "Antwerp Cocoa Processing Plant", "Frankfurt Regional DC", 11, 2.1)
    add("Cocoa Butter Blocks", "Turin Production Facility", "Vienna Regional DC", 7, 4.0)

    # -- planted data-quality problems (3), matching what Frank described --
    add("Milk Chocolate Pralines", "Antwerp Cocoa Processing Plant", "Milan Distribution Center", 9, 0.01,
        data_quality="duration_too_short")   # data entry error: start/end essentially identical
    add("Dark Chocolate Couverture 70%", "Turin Production Facility", "Rotterdam Distribution Hub", 90, 85.4,
        data_quality="duration_too_long")     # trip never properly closed, end date drifted
    add("Cocoa Butter Blocks", "Antwerp Cocoa Processing Plant", "Lyon Cold Storage", 13, 2.4,
        data_quality="sensor_glitch")         # otherwise normal trip, implausible temperature spike

    return scenarios


def _generate_trip(scenario, reading_id_start):
    product = scenario["product"]
    spec = PRODUCT_SPECS[product]
    start = NOW - timedelta(days=scenario["start_days_ago"])
    duration_days = scenario["duration_days"]
    end = start + timedelta(days=duration_days)
    device_id = f"CS-DEV-{RNG.integers(100, 999)}"
    quality = scenario["data_quality"]

    readings = []
    reading_id = reading_id_start
    interval_hours = 2  # coarser periodic logger, unlike SensiWatch's near-real-time cadence

    if quality == "duration_too_short":
        # essentially one or two points -- not enough transit to be a real trip
        n_points = 2
    elif quality == "duration_too_long":
        # a genuinely stale/never-closed record wouldn't have dense readings for 85 days --
        # sparse, trailing-off data is itself part of what makes this look wrong
        n_points = 10
    else:
        n_points = max(3, int(duration_days * 24 / interval_hours))

    for i in range(n_points):
        if quality == "duration_too_long":
            ts = start + timedelta(days=(duration_days * i / max(n_points - 1, 1)))
        else:
            ts = start + timedelta(hours=interval_hours * i)
        if ts > min(end, NOW):
            break

        temp = float(np.clip(RNG.uniform(spec["temp_min"], spec["temp_max"]) + RNG.uniform(-0.4, 0.4),
                              spec["temp_min"] - 1, spec["temp_max"] + 1))
        humidity = float(np.clip(RNG.uniform(spec["humidity_min"], spec["humidity_max"]), 20, 100))

        if quality == "sensor_glitch" and i == n_points // 2:
            temp = float(RNG.choice([-42.0, 96.5]))  # physically implausible for a chocolate shipment

        readings.append(dict(ReadingID=f"CS-RD-{reading_id:05d}", TripID=scenario["trip_id"], Timestamp=ts,
                              TemperatureC=round(temp, 2), HumidityPct=round(humidity, 1)))
        reading_id += 1

    header = dict(
        TripID=scenario["trip_id"], Customer=CUSTOMER, Product=product,
        OriginSite=scenario["origin"], DestinationSite=scenario["destination"],
        DeviceID=device_id, StartDate=start,
        EndDate=None if quality == "duration_too_long" else end,
        DurationDays=round(duration_days, 2),
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
