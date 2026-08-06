"""Dashboard endpoints backed by the Phase 2 ingested/triaged trip data
(SensiWatch + ColdStream uploads) instead of the Phase 1 workbook. Every
response is derived live from app.services.trip_analytics -- nothing hardcoded."""
from fastapi import APIRouter, HTTPException

from app.services import trip_analytics

router = APIRouter(prefix="/api/trips", tags=["trips"])


@router.get("/kpis")
def get_kpis():
    return trip_analytics.kpi_summary()


@router.get("/executive-summary")
def get_executive_summary():
    return trip_analytics.executive_summary()


@router.get("/rca")
def get_rca():
    return trip_analytics.rca_summary()


@router.get("/bloom-risk")
def get_bloom_risk():
    return trip_analytics.bloom_risk_by_product()


@router.get("")
def get_trips():
    return trip_analytics.to_records(trip_analytics.all_trips_summary())


@router.get("/{trip_id}/sensor-series")
def get_sensor_series(trip_id: str):
    series = trip_analytics.trip_sensor_series(trip_id)
    if series is None:
        raise HTTPException(status_code=404, detail="trip not found")
    return series


@router.get("/flagged")
def get_flagged():
    return trip_analytics.to_records(trip_analytics.flagged_trips())


@router.get("/product-risk")
def get_product_risk():
    return trip_analytics.to_records(trip_analytics.product_risk())


@router.get("/destination-ranking")
def get_destination_ranking():
    return trip_analytics.to_records(trip_analytics.destination_ranking())
