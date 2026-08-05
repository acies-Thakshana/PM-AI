"""
Simulates a live IoT sensor feed for shipments currently "In Transit" so the
dashboard has something real to poll -- purely deterministic random-walk
simulation, no LLM involved. Runs as a background asyncio task started at
FastAPI startup (see app/main.py).
"""
import asyncio
import random

from app.services.data_loader import store

CHECKPOINTS = ["Origin Loading Bay", "Highway Checkpoint 1", "Highway Checkpoint 2",
               "Regional Transfer Point", "Destination Dock"]


def _tick():
    for _, shp in store.in_transit_shipments().iterrows():
        shipment_id = shp["ShipmentID"]
        last = store.latest_reading_for(shipment_id)
        target_min, target_max = shp["TargetTempMinC"], shp["TargetTempMaxC"]
        hum_min, hum_max = shp["TargetHumidityMinPct"], shp["TargetHumidityMaxPct"]

        if last is None:
            temp = random.uniform(target_min, target_max)
            humidity = random.uniform(hum_min, hum_max)
        else:
            temp = float(last["TemperatureC"]) + random.uniform(-0.6, 0.6)
            humidity = float(last["HumidityPct"]) + random.uniform(-1.5, 1.5)

        door_open = "Y" if random.random() < 0.08 else "N"
        if door_open == "Y":
            temp += random.uniform(0.5, 1.5)
            humidity -= random.uniform(2, 5)

        temp = max(target_min - 1, min(target_max + 3, temp))
        humidity = max(40.0, min(100.0, humidity))

        checkpoint = random.choice(CHECKPOINTS)
        store.append_sensor_reading(shipment_id, temp, humidity, checkpoint, door_open)


async def run_live_feed_loop(interval_seconds: float = 12.0):
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            _tick()
        except Exception:
            # the simulator must never take the API down
            pass
