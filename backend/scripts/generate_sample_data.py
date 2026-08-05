"""
Generates backend/app/data/cold_chain_metrics.xlsx — realistic, internally-consistent
structured data for the Cold Chain / Post-Harvest Assessment PoC.

Run once (or whenever you want a fresh dataset):
    python scripts/generate_sample_data.py

The generation is deterministic (fixed seed) and builds in real causal structure —
temperature excursions actually drive spoilage/green-life outcomes — so Agent 1
has genuine signal to reason over instead of random noise.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import EXCEL_PATH  # noqa: E402

RNG = np.random.default_rng(42)
# Real wall-clock time (UTC, naive) at generation, NOT a fixed constant -- this
# keeps the "In Transit" shipments' historical readings contiguous with the
# live-feed simulator (app/services/live_feed.py), which appends at real UTC
# now(). Naive-UTC (not local time) because pandas' to_json epoch conversion
# treats naive timestamps as UTC -- using local time here would silently skew
# every timestamp shown on the dashboard by the server's UTC offset.
NOW = datetime.utcnow()

# ---------------------------------------------------------------------------
# Reference data: commodity post-harvest sensitivity profiles
# ---------------------------------------------------------------------------
COMMODITIES = {
    "Alphonso Mango": dict(target_min=10.0, target_max=13.0, hum_min=85, hum_max=90,
                            chill_sensitive=True, base_green_life=14, excursion_sensitivity=0.55),
    "Roma Tomato": dict(target_min=12.0, target_max=15.0, hum_min=90, hum_max=95,
                         chill_sensitive=True, base_green_life=14, excursion_sensitivity=0.45),
    "Cavendish Banana": dict(target_min=13.0, target_max=14.5, hum_min=90, hum_max=95,
                              chill_sensitive=True, base_green_life=10, excursion_sensitivity=0.65),
    "Baby Spinach": dict(target_min=0.0, target_max=4.0, hum_min=95, hum_max=100,
                          chill_sensitive=False, base_green_life=7, excursion_sensitivity=0.9),
    "Strawberry": dict(target_min=0.0, target_max=2.0, hum_min=90, hum_max=95,
                        chill_sensitive=False, base_green_life=5, excursion_sensitivity=1.1),
}

ORIGIN_FARMS = {
    "Alphonso Mango": ("Konkan Hill Growers", "Ratnagiri, Maharashtra"),
    "Roma Tomato": ("Sunrise Agro Collective", "Nashik, Maharashtra"),
    "Cavendish Banana": ("Jalgaon Banana Growers Co-op", "Jalgaon, Maharashtra"),
    "Baby Spinach": ("Nilgiri Greens Farm", "Ooty, Tamil Nadu"),
    "Strawberry": ("Mahabaleshwar Berry Farms", "Mahabaleshwar, Maharashtra"),
}

FACILITIES = pd.DataFrame([
    dict(FacilityID="FAC-01", FacilityName="Mumbai Cold Storage Hub", FacilityType="Cold Storage",
         Region="Mumbai, Maharashtra", CapacityMT=2500, RefrigerationSystemType="Ammonia (NH3) Screw Compressor",
         InstallYear=2014, LastMaintenanceDate="2026-05-12"),
    dict(FacilityID="FAC-02", FacilityName="Pune Distribution Center", FacilityType="Distribution Center",
         Region="Pune, Maharashtra", CapacityMT=1200, RefrigerationSystemType="R404A Multi-Compressor Rack",
         InstallYear=2019, LastMaintenanceDate="2026-07-02"),
    dict(FacilityID="FAC-03", FacilityName="Nagpur Regional Pack House", FacilityType="Pack House",
         Region="Nagpur, Maharashtra", CapacityMT=800, RefrigerationSystemType="R404A Split Units",
         InstallYear=2011, LastMaintenanceDate="2025-11-20"),
    dict(FacilityID="FAC-04", FacilityName="Delhi NCR Cold Storage", FacilityType="Cold Storage",
         Region="Delhi NCR", CapacityMT=3000, RefrigerationSystemType="Ammonia (NH3) Screw Compressor",
         InstallYear=2021, LastMaintenanceDate="2026-06-28"),
    dict(FacilityID="FAC-05", FacilityName="Bengaluru Distribution Center", FacilityType="Distribution Center",
         Region="Bengaluru, Karnataka", CapacityMT=1500, RefrigerationSystemType="R404A Multi-Compressor Rack",
         InstallYear=2017, LastMaintenanceDate="2026-04-15"),
    dict(FacilityID="FAC-06", FacilityName="Chennai Cold Storage", FacilityType="Cold Storage",
         Region="Chennai, Tamil Nadu", CapacityMT=1800, RefrigerationSystemType="R404A Multi-Compressor Rack",
         InstallYear=2012, LastMaintenanceDate="2025-09-30"),
])

# facilities known (by design) to run older/under-maintained refrigeration -> more excursions
RISKY_FACILITIES = {"FAC-01", "FAC-03", "FAC-06"}

REJECTION_REASONS = {
    "Alphonso Mango": "Chilling injury - internal browning / uneven ripening",
    "Roma Tomato": "Chilling injury - pitting and surface scald",
    "Cavendish Banana": "Chilling injury - peel discoloration, failure to ripen",
    "Baby Spinach": "Wilting and yellowing from heat exposure",
    "Strawberry": "Softening and mold onset from heat exposure",
}


def build_shipments(n=22):
    commodities = list(COMMODITIES.keys())
    rows = []
    for i in range(1, n + 1):
        commodity = commodities[(i - 1) % len(commodities)]
        profile = COMMODITIES[commodity]
        farm_name, origin_region = ORIGIN_FARMS[commodity]
        dest = FACILITIES.sample(random_state=int(RNG.integers(0, 1_000_000))).iloc[0]

        # last 3 shipments are still in transit (recent dispatch) -> used for the live feed
        in_transit = i > n - 3
        if in_transit:
            dispatch = NOW - timedelta(hours=float(RNG.uniform(2, 7)))
        else:
            days_ago = RNG.uniform(2, 30)
            dispatch = NOW - timedelta(days=float(days_ago))

        distance_km = float(RNG.uniform(180, 1400))
        transit_hours = round(distance_km / RNG.uniform(38, 55) + RNG.uniform(1, 4), 1)
        arrival = dispatch + timedelta(hours=transit_hours)

        rows.append(dict(
            ShipmentID=f"SHP-{1000 + i}",
            Commodity=commodity,
            OriginFarm=farm_name,
            OriginRegion=origin_region,
            DestinationFacilityID=dest["FacilityID"],
            DestinationFacility=dest["FacilityName"],
            DispatchDateTime=dispatch,
            ArrivalDateTime=None if in_transit else arrival,
            TransitHours=transit_hours,
            VehicleID=f"MH-{RNG.integers(10,49):02d}-RF-{RNG.integers(1000,9999)}",
            ReeferUnitID=f"RU-{RNG.integers(100,999)}",
            DistanceKM=round(distance_km, 1),
            QuantityKG=int(RNG.integers(800, 6000)),
            TargetTempMinC=profile["target_min"],
            TargetTempMaxC=profile["target_max"],
            TargetHumidityMinPct=profile["hum_min"],
            TargetHumidityMaxPct=profile["hum_max"],
            TransitStatus="In Transit" if in_transit else "Delivered",
        ))
    return pd.DataFrame(rows)


def build_sensor_readings(shipments: pd.DataFrame):
    all_rows = []
    reading_id = 1
    excursion_log = {}  # ShipmentID -> (excursion_deg_hours, max_temp_delta, door_open_count)

    for _, shp in shipments.iterrows():
        profile = COMMODITIES[shp["Commodity"]]
        target_min, target_max = profile["target_min"], profile["target_max"]
        hum_min, hum_max = profile["hum_min"], profile["hum_max"]

        start = shp["DispatchDateTime"]
        end = shp["ArrivalDateTime"] if pd.notna(shp["ArrivalDateTime"]) else NOW
        interval_min = 45
        n_readings = max(4, int((end - start).total_seconds() / 60 / interval_min))

        # facilities with older/under-maintained systems + longer routes -> higher excursion risk
        risk_bump = 0.55 if shp["DestinationFacilityID"] in RISKY_FACILITIES else 0.15
        has_excursion = RNG.random() < risk_bump

        deg_hours_above = 0.0
        max_delta = 0.0
        door_open_count = 0
        checkpoints = ["Origin Loading Bay", "Highway Checkpoint 1", "Highway Checkpoint 2",
                       "Regional Transfer Point", "Destination Dock"]

        # pick a contiguous excursion window if this shipment has one
        excursion_start_idx, excursion_len = None, 0
        if has_excursion:
            excursion_len = int(RNG.integers(3, max(4, n_readings // 2)))
            excursion_start_idx = int(RNG.integers(1, max(2, n_readings - excursion_len)))

        for r in range(n_readings):
            ts = start + timedelta(minutes=interval_min * r)
            in_excursion = has_excursion and excursion_start_idx <= r < excursion_start_idx + excursion_len

            door_open = "Y" if (RNG.random() < (0.12 if in_excursion else 0.04)) else "N"
            if door_open == "Y":
                door_open_count += 1

            base_temp = RNG.uniform(target_min, target_max)
            if in_excursion:
                # sustained excursion above target max (reefer struggling / door events)
                delta = RNG.uniform(2.5, 7.5) + (2.0 if door_open == "Y" else 0.0)
                temp = target_max + delta
                deg_hours_above += delta * (interval_min / 60)
                max_delta = max(max_delta, delta)
            else:
                jitter = RNG.uniform(-0.4, 0.4) + (1.2 if door_open == "Y" else 0.0)
                temp = float(np.clip(base_temp + jitter, target_min - 0.3, target_max + 0.6))
                if temp > target_max:
                    deg_hours_above += (temp - target_max) * (interval_min / 60)
                    max_delta = max(max_delta, temp - target_max)

            humidity = float(np.clip(RNG.uniform(hum_min, hum_max) - (6 if door_open == "Y" else 0), 40, 100))

            all_rows.append(dict(
                ReadingID=f"RD-{reading_id:05d}",
                ShipmentID=shp["ShipmentID"],
                Timestamp=ts,
                TemperatureC=round(temp, 2),
                HumidityPct=round(humidity, 1),
                CheckpointLocation=checkpoints[min(r * len(checkpoints) // max(n_readings, 1), len(checkpoints) - 1)],
                DoorOpenEvent=door_open,
            ))
            reading_id += 1

        excursion_log[shp["ShipmentID"]] = dict(
            deg_hours_above=round(deg_hours_above, 2),
            max_delta=round(max_delta, 2),
            door_open_count=door_open_count,
        )

    return pd.DataFrame(all_rows), excursion_log


def build_quality_assessment(shipments: pd.DataFrame, excursion_log: dict):
    rows = []
    for _, shp in shipments.iterrows():
        if shp["TransitStatus"] == "In Transit":
            continue  # not arrived yet, no quality data
        profile = COMMODITIES[shp["Commodity"]]
        exc = excursion_log[shp["ShipmentID"]]
        sensitivity = profile["excursion_sensitivity"]

        # causal model: more degree-hours above threshold -> more spoilage, less green life left
        spoilage_pct = float(np.clip(
            exc["deg_hours_above"] * sensitivity * 0.9 + RNG.uniform(0, 1.5), 0, 45
        ))
        green_life_loss_days = min(profile["base_green_life"] - 0.5,
                                    exc["deg_hours_above"] * sensitivity * 0.35 + RNG.uniform(0, 0.6))
        green_life_remaining = round(max(0.5, profile["base_green_life"] - green_life_loss_days), 1)
        grade_score = float(np.clip(100 - spoilage_pct * 1.8 - exc["door_open_count"] * 0.8, 35, 99))

        rejected = spoilage_pct > 12
        rows.append(dict(
            ShipmentID=shp["ShipmentID"],
            ArrivalGradeScore=round(grade_score, 1),
            SpoilagePct=round(spoilage_pct, 1),
            GreenLifeRemainingDays=green_life_remaining,
            ExcursionDegHours=exc["deg_hours_above"],
            MaxTempDeltaC=exc["max_delta"],
            DoorOpenEvents=exc["door_open_count"],
            RejectionReason=REJECTION_REASONS[shp["Commodity"]] if rejected else "None - Accepted",
            InspectorNotes=(
                f"Sustained excursion of {exc['deg_hours_above']:.1f} deg-hours above target max "
                f"(peak +{exc['max_delta']:.1f}C) recorded in transit."
                if exc["deg_hours_above"] > 1.0 else
                "Within target range throughout transit; no significant deviations noted."
            ),
        ))
    return pd.DataFrame(rows)


def build_kpi_targets():
    return pd.DataFrame([
        dict(KPIName="Temperature Compliance Rate", TargetValue=95, Unit="%",
             Description="Share of sensor readings within the commodity's target temperature band"),
        dict(KPIName="Maximum Acceptable Spoilage", TargetValue=8, Unit="%",
             Description="Ceiling on arrival spoilage percentage before a shipment is flagged"),
        dict(KPIName="Minimum Green Life Retention", TargetValue=70, Unit="% of base shelf life",
             Description="Minimum share of a commodity's base green life that must remain at arrival"),
        dict(KPIName="Door-Open Events per Shipment", TargetValue=2, Unit="count (max)",
             Description="Maximum acceptable reefer door-open events during transit"),
    ])


def main():
    shipments = build_shipments()
    sensor_readings, excursion_log = build_sensor_readings(shipments)
    quality = build_quality_assessment(shipments, excursion_log)
    kpi_targets = build_kpi_targets()

    EXCEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(EXCEL_PATH, engine="openpyxl") as writer:
        shipments.to_excel(writer, sheet_name="Shipment_Log", index=False)
        sensor_readings.to_excel(writer, sheet_name="Sensor_Readings", index=False)
        FACILITIES.to_excel(writer, sheet_name="Facility_Master", index=False)
        quality.to_excel(writer, sheet_name="Quality_Assessment", index=False)
        kpi_targets.to_excel(writer, sheet_name="Program_KPI_Targets", index=False)

    print(f"Wrote {EXCEL_PATH}")
    print(f"  Shipment_Log: {len(shipments)} rows")
    print(f"  Sensor_Readings: {len(sensor_readings)} rows")
    print(f"  Facility_Master: {len(FACILITIES)} rows")
    print(f"  Quality_Assessment: {len(quality)} rows")
    print(f"  Program_KPI_Targets: {len(kpi_targets)} rows")


if __name__ == "__main__":
    main()
