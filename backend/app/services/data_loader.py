"""
Deterministic data access layer. Reads the Excel workbook once, keeps it in
memory, and is the ONLY place that touches the raw file. Nothing upstream of
this module (agents, routers) ever parses Excel directly -- this is the
guardrail that keeps the LLM agents away from raw data manipulation.
"""
import threading
from datetime import datetime, timezone

import pandas as pd

from app.config import EXCEL_PATH

_lock = threading.Lock()


class DataStore:
    def __init__(self):
        self.shipments: pd.DataFrame = pd.DataFrame()
        self.sensor_readings: pd.DataFrame = pd.DataFrame()
        self.facilities: pd.DataFrame = pd.DataFrame()
        self.quality: pd.DataFrame = pd.DataFrame()
        self.kpi_targets: pd.DataFrame = pd.DataFrame()
        self._next_reading_seq = 1
        self.load()

    def load(self):
        with _lock:
            xls = pd.ExcelFile(EXCEL_PATH)
            self.shipments = pd.read_excel(xls, "Shipment_Log")
            self.sensor_readings = pd.read_excel(xls, "Sensor_Readings")
            self.facilities = pd.read_excel(xls, "Facility_Master")
            self.quality = pd.read_excel(xls, "Quality_Assessment")
            self.kpi_targets = pd.read_excel(xls, "Program_KPI_Targets")
            self._next_reading_seq = len(self.sensor_readings) + 1

    def append_sensor_reading(self, shipment_id: str, temperature_c: float,
                               humidity_pct: float, checkpoint: str, door_open: str):
        """Used by the live-feed simulator to append a new reading in-memory.
        This never touches the Excel file -- the workbook stays the immutable
        source-of-truth snapshot, the live feed only extends the in-memory view.
        """
        with _lock:
            reading_id = f"RD-LIVE-{self._next_reading_seq:05d}"
            self._next_reading_seq += 1
            new_row = pd.DataFrame([dict(
                ReadingID=reading_id,
                ShipmentID=shipment_id,
                Timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
                TemperatureC=round(temperature_c, 2),
                HumidityPct=round(humidity_pct, 1),
                CheckpointLocation=checkpoint,
                DoorOpenEvent=door_open,
            )])
            self.sensor_readings = pd.concat([self.sensor_readings, new_row], ignore_index=True)

    def latest_reading_for(self, shipment_id: str):
        rows = self.sensor_readings[self.sensor_readings["ShipmentID"] == shipment_id]
        if rows.empty:
            return None
        return rows.sort_values("Timestamp").iloc[-1]

    def in_transit_shipments(self):
        return self.shipments[self.shipments["TransitStatus"] == "In Transit"]


store = DataStore()
