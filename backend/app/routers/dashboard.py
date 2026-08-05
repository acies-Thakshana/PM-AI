"""Read-only endpoints that feed the React dashboard. Every response is
derived live from the loaded Excel data (app.services.data_loader /
analytics) -- nothing here is hardcoded."""
from fastapi import APIRouter, HTTPException

from app.services import analytics
from app.services.data_loader import store

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/kpis")
def get_kpis():
    return analytics.kpi_summary()


@router.get("/shipments")
def get_shipments():
    return analytics.to_records(analytics.all_shipments_summary())


@router.get("/shipments/{shipment_id}/sensor-series")
def get_sensor_series(shipment_id: str):
    shp_rows = store.shipments[store.shipments["ShipmentID"] == shipment_id]
    if shp_rows.empty:
        raise HTTPException(status_code=404, detail="shipment not found")
    shp = shp_rows.iloc[0]
    readings = store.sensor_readings[store.sensor_readings["ShipmentID"] == shipment_id].sort_values("Timestamp")
    return {
        "shipment_id": shipment_id,
        "commodity": str(shp["Commodity"]),
        "target_temp_min": float(shp["TargetTempMinC"]),
        "target_temp_max": float(shp["TargetTempMaxC"]),
        "target_humidity_min": float(shp["TargetHumidityMinPct"]),
        "target_humidity_max": float(shp["TargetHumidityMaxPct"]),
        "transit_status": str(shp["TransitStatus"]),
        "readings": analytics.to_records(readings),
    }


@router.get("/facilities")
def get_facilities():
    return analytics.to_records(analytics.facility_ranking())


@router.get("/excursions")
def get_excursions():
    return analytics.to_records(analytics.excursion_alerts())


@router.get("/commodity-risk")
def get_commodity_risk():
    return analytics.to_records(analytics.commodity_risk())
