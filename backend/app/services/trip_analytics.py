"""
Deterministic analytics over the Phase 2 ingested/triaged trip data
(app.services.ingestion.store) -- this is the dashboard's data source once
SensiWatch/ColdStream/customer-profile/business-rules have been loaded via the
Data Upload page. Same principle as analytics.py: plain pandas, no LLM, and
this module is the only place that reads ingestion.store's raw DataFrames.
"""
import json

import pandas as pd

from app.services import ingestion
from app.services.sites import SITES

NEEDS_ATTENTION_FLAGS = {
    "stuck_unresolved", "likely_arrived", "duration_too_short",
    "duration_too_long", "missing_end_date", "value_outlier",
}

# category + plain-language root cause, mirroring how Frank described each
# manual check in the discovery call
FLAG_INFO = {
    "likely_arrived": dict(
        category="SensiWatch", label="Trip Closure Gap",
        description="Trip still shows 'In Transit' but GPS position (or a customer delivery "
                     "confirmation) indicates the shipment has arrived. Needs to be closed manually "
                     "so it is picked up correctly in reporting.",
    ),
    "stuck_unresolved": dict(
        category="SensiWatch", label="Stalled In Transit",
        description="Trip is overdue for arrival and the last GPS reading is not near the "
                     "destination coordinates. Worth investigating for a structural cause "
                     "(routing, customs delay, wrong destination configuration) before closing.",
    ),
    "duration_too_short": dict(
        category="ColdStream", label="Data Entry Error",
        description="Trip duration is implausibly short (near-zero) -- most likely a start/end "
                     "date entry mistake rather than a real shipment.",
    ),
    "duration_too_long": dict(
        category="ColdStream", label="Trip Never Closed",
        description="Trip duration is implausibly long with no end date recorded -- the record "
                     "was never properly closed out.",
    ),
    "missing_end_date": dict(
        category="ColdStream", label="Missing End Date",
        description="Trip has no end date recorded, so duration and compliance can't be "
                     "reliably calculated.",
    ),
    "value_outlier": dict(
        category="ColdStream", label="Sensor Anomaly",
        description="One or more readings fall outside physically plausible bounds -- most "
                     "likely a sensor glitch rather than a real temperature/humidity excursion.",
    ),
}


def to_records(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    return json.loads(df.to_json(orient="records"))


def _product_spec(product: str) -> dict | None:
    rules = ingestion.store.business_rules
    if rules and product in rules.get("product_specs", {}):
        spec = rules["product_specs"][product]
        return dict(temp_min=spec["temp_min_c"], temp_max=spec["temp_max_c"])
    return None


def _compliance_pct(product: str, readings: pd.DataFrame, fallback_min, fallback_max):
    if readings.empty:
        return None
    spec = _product_spec(product)
    temp_min = spec["temp_min"] if spec else fallback_min
    temp_max = spec["temp_max"] if spec else fallback_max
    in_band = readings["TemperatureC"].between(temp_min, temp_max)
    return round(100 * float(in_band.mean()), 1)


def _humidity_compliance_pct(product: str, readings: pd.DataFrame):
    if readings.empty or "HumidityPct" not in readings:
        return None
    rules = ingestion.store.business_rules
    spec = rules.get("product_specs", {}).get(product) if rules else None
    if not spec:
        return None
    in_band = readings["HumidityPct"].between(spec["humidity_min_pct"], spec["humidity_max_pct"])
    return round(100 * float(in_band.mean()), 1)


def _site_coords(site: str) -> tuple[float | None, float | None]:
    coords = SITES.get(site)
    return (coords[0], coords[1]) if coords else (None, None)


def all_trips_summary() -> pd.DataFrame:
    rows = []

    if ingestion.store.sensiwatch is not None:
        trip_header = ingestion.store.sensiwatch["trip_header"]
        sensor_readings = ingestion.store.sensiwatch["sensor_readings"]
        triage = ingestion.store.sensiwatch["triage"].set_index("TripID")
        for _, trip in trip_header.iterrows():
            readings = sensor_readings[sensor_readings["TripID"] == trip["TripID"]]
            flag_row = triage.loc[trip["TripID"]]
            origin_lat, origin_lon = _site_coords(trip["OriginSite"])
            rows.append(dict(
                TripID=trip["TripID"], Source="SensiWatch", Product=trip["Product"],
                Origin=trip["OriginSite"], Destination=trip["DestinationSite"],
                OriginLat=origin_lat, OriginLon=origin_lon,
                DestinationLat=trip["DestinationLat"], DestinationLon=trip["DestinationLon"],
                Status=trip["TripStatus"], Flag=flag_row["Flag"],
                DistanceToDestinationKm=flag_row["DistanceToDestinationKm"],
                CustomerConfirmation=flag_row["CustomerConfirmation"],
                CompliancePct=_compliance_pct(trip["Product"], readings,
                                               trip["TargetTempMinC"], trip["TargetTempMaxC"]),
                HumidityCompliancePct=_humidity_compliance_pct(trip["Product"], readings),
                CreatedDate=trip["CreatedDate"], ReadingCount=len(readings),
            ))

    if ingestion.store.coldstream is not None:
        trip_header = ingestion.store.coldstream["trip_header"]
        sensor_readings = ingestion.store.coldstream["sensor_readings"]
        triage = ingestion.store.coldstream["triage"].set_index("TripID")
        for _, trip in trip_header.iterrows():
            readings = sensor_readings[sensor_readings["TripID"] == trip["TripID"]]
            flag_row = triage.loc[trip["TripID"]]
            origin_lat, origin_lon = _site_coords(trip["OriginSite"])
            dest_lat, dest_lon = _site_coords(trip["DestinationSite"])
            rows.append(dict(
                TripID=trip["TripID"], Source="ColdStream", Product=trip["Product"],
                Origin=trip["OriginSite"], Destination=trip["DestinationSite"],
                OriginLat=origin_lat, OriginLon=origin_lon,
                DestinationLat=dest_lat, DestinationLon=dest_lon,
                Status="Closed" if pd.notna(trip.get("EndDate")) else "Unresolved",
                Flag=flag_row["Flag"], DistanceToDestinationKm=None, CustomerConfirmation=None,
                CompliancePct=_compliance_pct(trip["Product"], readings,
                                               trip["TargetTempMinC"], trip["TargetTempMaxC"]),
                HumidityCompliancePct=_humidity_compliance_pct(trip["Product"], readings),
                CreatedDate=trip["StartDate"], ReadingCount=len(readings),
            ))

    return pd.DataFrame(rows)


def kpi_summary() -> dict:
    summary = all_trips_summary()
    sources_loaded = [s for s, loaded in
                       [("SensiWatch", ingestion.store.sensiwatch is not None),
                        ("ColdStream", ingestion.store.coldstream is not None)] if loaded]

    if summary.empty:
        return dict(trips_loaded=0, avg_compliance_pct=None, flagged_trip_count=0,
                    active_trip_count=0, likely_arrived_count=0, stuck_trip_count=0,
                    sources_loaded=sources_loaded)

    avg_compliance = summary["CompliancePct"].dropna().mean()
    return dict(
        trips_loaded=len(summary),
        avg_compliance_pct=round(float(avg_compliance), 1) if pd.notna(avg_compliance) else None,
        flagged_trip_count=int(summary["Flag"].isin(NEEDS_ATTENTION_FLAGS).sum()),
        active_trip_count=int((summary["Flag"] == "active").sum()),
        likely_arrived_count=int((summary["Flag"] == "likely_arrived").sum()),
        stuck_trip_count=int((summary["Flag"] == "stuck_unresolved").sum()),
        sources_loaded=sources_loaded,
    )


def flagged_trips() -> pd.DataFrame:
    summary = all_trips_summary()
    if summary.empty:
        return summary
    return summary[summary["Flag"].isin(NEEDS_ATTENTION_FLAGS)].sort_values("Flag")


def product_risk() -> pd.DataFrame:
    summary = all_trips_summary()
    if summary.empty:
        return summary
    grouped = summary.groupby("Product").agg(
        TripCount=("TripID", "count"),
        AvgCompliancePct=("CompliancePct", "mean"),
        FlaggedCount=("Flag", lambda s: s.isin(NEEDS_ATTENTION_FLAGS).sum()),
    ).reset_index()
    grouped["AvgCompliancePct"] = grouped["AvgCompliancePct"].round(1)
    return grouped.sort_values("AvgCompliancePct")


def destination_ranking() -> pd.DataFrame:
    summary = all_trips_summary()
    if summary.empty:
        return summary
    grouped = summary.groupby("Destination").agg(
        TripCount=("TripID", "count"),
        AvgCompliancePct=("CompliancePct", "mean"),
        FlaggedCount=("Flag", lambda s: s.isin(NEEDS_ATTENTION_FLAGS).sum()),
    ).reset_index()
    grouped["AvgCompliancePct"] = grouped["AvgCompliancePct"].round(1)
    return grouped.sort_values("AvgCompliancePct")


def trip_sensor_series(trip_id: str) -> dict | None:
    for source_name, store_attr in (("SensiWatch", ingestion.store.sensiwatch),
                                     ("ColdStream", ingestion.store.coldstream)):
        if store_attr is None:
            continue
        trip_header = store_attr["trip_header"]
        row = trip_header[trip_header["TripID"] == trip_id]
        if row.empty:
            continue
        trip = row.iloc[0]
        sensor_readings = store_attr["sensor_readings"]
        readings = sensor_readings[sensor_readings["TripID"] == trip_id].sort_values("Timestamp")
        spec = _product_spec(trip["Product"])
        return dict(
            trip_id=trip_id, source=source_name, product=str(trip["Product"]),
            target_temp_min=float(spec["temp_min"] if spec else trip["TargetTempMinC"]),
            target_temp_max=float(spec["temp_max"] if spec else trip["TargetTempMaxC"]),
            readings=to_records(readings),
        )
    return None


def executive_summary() -> dict:
    rules = ingestion.store.business_rules
    customer = rules.get("customer") if rules else None
    summary = all_trips_summary()

    by_source = (
        summary.groupby("Source").size().to_dict() if not summary.empty else {}
    )

    top_flagged_products = []
    risk = product_risk()
    if not risk.empty:
        flagged = risk[risk["FlaggedCount"] > 0].sort_values("FlaggedCount", ascending=False).head(3)
        top_flagged_products = to_records(flagged)

    return dict(
        customer=customer or "Customer",
        kpis=kpi_summary(),
        by_source=by_source,
        top_flagged_products=top_flagged_products,
    )


def rca_summary() -> list[dict]:
    summary = all_trips_summary()
    if summary.empty:
        return []

    flagged = summary[summary["Flag"].isin(NEEDS_ATTENTION_FLAGS)]
    if flagged.empty:
        return []

    results = []
    for flag, group in flagged.groupby("Flag"):
        info = FLAG_INFO.get(flag, dict(category="Other", label=flag, description=""))
        trips = group[["TripID", "Product", "Destination", "CompliancePct"]].to_dict(orient="records")
        results.append(dict(
            flag=flag, category=info["category"], label=info["label"],
            description=info["description"], trip_count=len(group), trips=trips,
        ))
    return sorted(results, key=lambda r: r["trip_count"], reverse=True)


def bloom_risk_by_product() -> list[dict]:
    """Composite 0-100 risk score per product combining temperature and humidity
    excursion share, matching the 'Bloom Risk Score' custom KPI from the
    business rules doc. Weighting (70% temperature / 30% humidity) is an
    assumed split -- temperature is the dominant bloom driver -- not something
    confirmed on the discovery call."""
    summary = all_trips_summary()
    if summary.empty:
        return []

    rows = summary.dropna(subset=["CompliancePct"]).copy()
    if rows.empty:
        return []

    def _risk(row):
        temp_excursion = 100 - row["CompliancePct"]
        humidity_excursion = 100 - row["HumidityCompliancePct"] if pd.notna(row["HumidityCompliancePct"]) else temp_excursion
        return round(min(100.0, 0.7 * temp_excursion + 0.3 * humidity_excursion), 1)

    rows["BloomRisk"] = rows.apply(_risk, axis=1)
    grouped = rows.groupby("Product").agg(
        TripCount=("TripID", "count"),
        BloomRiskScore=("BloomRisk", "mean"),
    ).reset_index()
    grouped["BloomRiskScore"] = grouped["BloomRiskScore"].round(1)

    rules = ingestion.store.business_rules
    target_max = 15
    if rules:
        for kpi in rules.get("customer_kpis", []):
            if kpi.get("name") == "Bloom Risk Score" and "target_max" in kpi:
                target_max = kpi["target_max"]

    grouped["TargetMax"] = target_max
    return to_records(grouped.sort_values("BloomRiskScore", ascending=False))
