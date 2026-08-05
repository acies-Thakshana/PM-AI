"""
Deterministic analytics over the loaded data -- every number here is computed
with plain pandas arithmetic, never by an LLM. Agent 1 consumes the *output*
of this module, it never sees or touches the raw sheets.
"""
import json

import pandas as pd

from app.services.data_loader import store


def to_records(df: pd.DataFrame) -> list[dict]:
    """NaN-safe DataFrame -> list[dict] (pandas to_json handles NaN/NaT as null)."""
    if df is None or df.empty:
        return []
    return json.loads(df.to_json(orient="records"))


def _compliance_and_excursion(sensor_df: pd.DataFrame, target_min: float, target_max: float):
    if sensor_df.empty:
        return dict(compliance_pct=100.0, deg_hours=0.0, max_delta=0.0, door_opens=0, n_readings=0)

    sensor_df = sensor_df.sort_values("Timestamp")
    in_band = sensor_df["TemperatureC"].between(target_min, target_max)
    compliance_pct = round(100 * in_band.mean(), 1)

    # assume ~45 min between readings (matches generator); compute deviation degree-hours
    interval_hours = 45 / 60
    above = (sensor_df["TemperatureC"] - target_max).clip(lower=0)
    below = (target_min - sensor_df["TemperatureC"]).clip(lower=0)
    deviation = above + below
    deg_hours = round(float((deviation * interval_hours).sum()), 2)
    max_delta = round(float(deviation.max()), 2)
    door_opens = int((sensor_df["DoorOpenEvent"] == "Y").sum())

    return dict(compliance_pct=compliance_pct, deg_hours=deg_hours, max_delta=max_delta,
                door_opens=door_opens, n_readings=len(sensor_df))


def shipment_metrics(shipment_id: str) -> dict:
    shp_rows = store.shipments[store.shipments["ShipmentID"] == shipment_id]
    if shp_rows.empty:
        return {}
    shp = shp_rows.iloc[0]
    sensor_df = store.sensor_readings[store.sensor_readings["ShipmentID"] == shipment_id]
    metrics = _compliance_and_excursion(sensor_df, shp["TargetTempMinC"], shp["TargetTempMaxC"])
    metrics["shipment_id"] = shipment_id
    return metrics


def all_shipments_summary() -> pd.DataFrame:
    """One row per shipment: shipment/facility/commodity info + computed metrics + quality outcome."""
    rows = []
    for _, shp in store.shipments.iterrows():
        m = shipment_metrics(shp["ShipmentID"])
        quality_row = store.quality[store.quality["ShipmentID"] == shp["ShipmentID"]]
        q = quality_row.iloc[0].to_dict() if not quality_row.empty else {}
        rows.append({
            "ShipmentID": shp["ShipmentID"],
            "Commodity": shp["Commodity"],
            "OriginFarm": shp["OriginFarm"],
            "DestinationFacilityID": shp["DestinationFacilityID"],
            "DestinationFacility": shp["DestinationFacility"],
            "TransitStatus": shp["TransitStatus"],
            "DistanceKM": shp["DistanceKM"],
            "QuantityKG": shp["QuantityKG"],
            "CompliancePct": m.get("compliance_pct"),
            "ExcursionDegHours": m.get("deg_hours"),
            "MaxDeltaC": m.get("max_delta"),
            "DoorOpenEvents": m.get("door_opens"),
            "SpoilagePct": q.get("SpoilagePct"),
            "GreenLifeRemainingDays": q.get("GreenLifeRemainingDays"),
            "ArrivalGradeScore": q.get("ArrivalGradeScore"),
            "RejectionReason": q.get("RejectionReason"),
        })
    return pd.DataFrame(rows)


def kpi_summary() -> dict:
    summary = all_shipments_summary()
    delivered = summary[summary["TransitStatus"] == "Delivered"]
    targets = {row["KPIName"]: row["TargetValue"] for _, row in store.kpi_targets.iterrows()}

    avg_compliance = round(float(summary["CompliancePct"].mean()), 1) if not summary.empty else 0.0
    avg_spoilage = round(float(delivered["SpoilagePct"].mean()), 1) if not delivered.empty else 0.0
    at_risk = int((delivered["SpoilagePct"] > targets.get("Maximum Acceptable Spoilage", 8)).sum())

    base_life = {"Alphonso Mango": 14, "Roma Tomato": 14, "Cavendish Banana": 10,
                 "Baby Spinach": 7, "Strawberry": 5}
    if not delivered.empty:
        retention = delivered.apply(
            lambda r: 100 * r["GreenLifeRemainingDays"] / base_life.get(r["Commodity"], 10), axis=1
        )
        avg_retention = round(float(retention.mean()), 1)
    else:
        avg_retention = 0.0

    return dict(
        shipments_assessed=len(delivered),
        shipments_in_transit=len(summary[summary["TransitStatus"] == "In Transit"]),
        avg_temperature_compliance_pct=avg_compliance,
        avg_spoilage_pct=avg_spoilage,
        avg_green_life_retention_pct=avg_retention,
        at_risk_shipment_count=at_risk,
        targets=targets,
    )


def excursion_alerts() -> pd.DataFrame:
    summary = all_shipments_summary()
    targets = {row["KPIName"]: row["TargetValue"] for _, row in store.kpi_targets.iterrows()}
    door_target = targets.get("Door-Open Events per Shipment", 2)
    alerts = summary[
        (summary["ExcursionDegHours"] > 5) | (summary["DoorOpenEvents"] > door_target)
    ].copy()
    return alerts.sort_values("ExcursionDegHours", ascending=False)


def facility_ranking() -> pd.DataFrame:
    summary = all_shipments_summary()
    delivered = summary[summary["TransitStatus"] == "Delivered"]
    if delivered.empty:
        return pd.DataFrame()
    grouped = delivered.groupby(["DestinationFacilityID", "DestinationFacility"]).agg(
        ShipmentCount=("ShipmentID", "count"),
        AvgCompliancePct=("CompliancePct", "mean"),
        AvgSpoilagePct=("SpoilagePct", "mean"),
        AvgExcursionDegHours=("ExcursionDegHours", "mean"),
    ).reset_index()
    facility_info = store.facilities[["FacilityID", "FacilityType", "RefrigerationSystemType", "InstallYear"]]
    merged = grouped.merge(facility_info, left_on="DestinationFacilityID", right_on="FacilityID", how="left")
    for col in ["AvgCompliancePct", "AvgSpoilagePct", "AvgExcursionDegHours"]:
        merged[col] = merged[col].round(1)
    return merged.sort_values("AvgSpoilagePct", ascending=False)


def commodity_risk() -> pd.DataFrame:
    summary = all_shipments_summary()
    delivered = summary[summary["TransitStatus"] == "Delivered"]
    if delivered.empty:
        return pd.DataFrame()
    base_life = {"Alphonso Mango": 14, "Roma Tomato": 14, "Cavendish Banana": 10,
                 "Baby Spinach": 7, "Strawberry": 5}
    delivered = delivered.copy()
    delivered["GreenLifeRetentionPct"] = delivered.apply(
        lambda r: round(100 * r["GreenLifeRemainingDays"] / base_life.get(r["Commodity"], 10), 1), axis=1
    )
    grouped = delivered.groupby("Commodity").agg(
        ShipmentCount=("ShipmentID", "count"),
        AvgSpoilagePct=("SpoilagePct", "mean"),
        AvgGreenLifeRetentionPct=("GreenLifeRetentionPct", "mean"),
        AvgExcursionDegHours=("ExcursionDegHours", "mean"),
    ).reset_index()
    for col in ["AvgSpoilagePct", "AvgGreenLifeRetentionPct", "AvgExcursionDegHours"]:
        grouped[col] = grouped[col].round(1)
    return grouped.sort_values("AvgGreenLifeRetentionPct")


def top_risk_shipments(n: int = 5) -> pd.DataFrame:
    summary = all_shipments_summary()
    delivered = summary[summary["TransitStatus"] == "Delivered"]
    return delivered.sort_values("SpoilagePct", ascending=False).head(n)
