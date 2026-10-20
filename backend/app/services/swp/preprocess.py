"""Pre-processing of SWP API data: from the raw API responses to the stored raw data and the aggregate table.

  SWP API  --->  raw store        one JSON file per trip, exactly as the API returned it (list record, basic trip, trip
     |                             detail with sensor readings and GPS route); see cache.py. Nothing is lost, and
     |                             nothing is fetched twice: an arrived trip never changes, any other trip is
     v                             fetched again only when its lastUpdatedDate in the trip list moved.
  aggregate table  --->  the SensiWatch export's columns, in its order, one row per trip, logger and sensor. It is
                         always rebuilt from the raw files (transform.py holds the field-to-column mapping) and is
                         also written to the store as 'Tabular Shipment Data.xlsx' with the export's header texts.

Why JSON for the raw data: the API's answers are nested and differ from trip to trip, so they are kept as they come and
the aggregate can be rebuilt from them (a new column, a corrected conversion) without calling the rate-limited API.
The aggregate is flat and tabular, so it is a DataFrame in the app and Excel on disk, the format people already use.

Run by itself (writes the raw JSON files and the Excel into a folder):

    python -m app.services.swp.preprocess --program 1968 --status Arrived --limit 20 --out out/
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pandas as pd

from app import config
from app.services.swp import cache, client
from app.services.swp.transform import EXPORT_COLUMNS, build_tables

AGGREGATE_FILE = "Tabular Shipment Data.xlsx"
SHEET_NAME = "Tabular Shipment Data"

# The export's header texts, verbatim: a few contain a line break or a stray space. The app works with the
# whitespace-collapsed names (EXPORT_COLUMNS); the Excel file gets the originals.
_HEADER_TEXT = {
    "Trip Create Date CET": "Trip Create Date \nCET",
    "Segment Length (Days)": "Segment Length \n(Days)",
    "Value Minutes Above Ideal": " Value Minutes Above Ideal",
    "Specs Last Updated Date/Time": "Specs Last Updated \nDate/Time",
    "Shipment Created Date/Time": "Shipment Created\nDate/Time",
}
AGGREGATE_COLUMNS = [c for c in EXPORT_COLUMNS if c not in ("SWP Trip Key", "editedInApp")]  # the export's 59 columns
EXCEL_HEADERS = [_HEADER_TEXT.get(c, c) for c in AGGREGATE_COLUMNS]
DATETIME_FORMAT = "dd/mm/yyyy hh:mm:ss"


# ---- the raw data: from the store where current, else from the API --------------------------------------------------

def stored_payloads(program: str, ids: list[str], records: dict[str, dict]) -> dict[str, dict]:
    """The stored raw payloads that are still current, by trip id. Arrived trips never change; any other trip is
    current while the list record's lastUpdatedDate is the one it was stored with."""
    current: dict[str, dict] = {}
    for tid in ids:
        record = records[tid]
        stored = cache.load_trip(program, tid)
        if not stored or not stored.get("detail"):
            continue
        same = (stored.get("record") or {}).get("lastUpdatedDate") == record.get("lastUpdatedDate")
        if client.status_name(record) == "Arrived" or same:
            current[tid] = {**stored, "tripID": tid, "record": record}
    return current


def expected_calls(ids: list[str], records: dict[str, dict], saved: dict[str, dict]) -> int:
    """API calls fetch_payloads will make: the detail of every trip not stored (plus the single-trip call when the
    list record lacks its basics), plus a token when any call is made at all."""
    calls = sum(0 if t in saved else (1 if "serialNumbers" in records[t] else 2) for t in ids)
    return calls + (1 if calls and not client.has_token() else 0)


def fetch_payloads(program: str, ids: list[str], records: dict[str, dict], saved: dict[str, dict], token: str) -> list[dict]:
    """The raw payload of each trip, in the order of `ids`: from the store where current, else from the API (and
    then stored)."""
    payloads = []
    for tid in ids:
        if tid in saved:
            payloads.append(saved[tid])
            continue
        # The list record already carries the basic fields (serial numbers), which saves one rate-limited call.
        basic = records[tid]
        if "serialNumbers" not in basic:
            basic = client.get_trip(token, tid, program)
        payload = {"tripID": tid, "record": records[tid], "basic": basic, "detail": client.get_trip_detail(token, tid, program)}
        cache.save_trip(program, tid, payload)
        payloads.append(payload)
    return payloads


# ---- what the pages show per trip -----------------------------------------------------------------------------------

def trip_times(payload: dict) -> tuple[str | None, str | None]:
    """(departure, arrival) of a trip as UTC ISO text: from the trip detail, else from the list record."""
    detail, record = payload.get("detail") or {}, payload.get("record") or {}
    departure = (detail.get("tripOrigin") or {}).get("actualDepartureTime") or client.departure_of(record)
    arrival = detail.get("tripActualArrivalTime") or client.arrival_of(record)
    return departure, arrival


def trip_kpis(table: pd.DataFrame) -> dict[str, dict]:
    """Per trip (by its SWP key): the numbers the Configure page's cards and list use, read from the aggregate."""
    out: dict[str, dict] = {}
    if table.empty:
        return out

    def num(value):
        return None if value is None or pd.isna(value) else round(float(value), 2)

    def text(value):
        return None if value is None or pd.isna(value) else str(value)

    for key, rows in table.groupby("SWP Trip Key", sort=False):
        temperature = rows[rows["Sensor Type"] == "Temperature"]
        first = rows.iloc[0]
        trip_id = first["Trip ID"]
        out[str(key)] = {
            "number": None if pd.isna(trip_id) else str(int(trip_id)) if float(trip_id).is_integer() else str(trip_id),
            "mean_temp": num(temperature["Mean Value"].mean()) if len(temperature) else None,
            "segment_days": num(first["Segment Length (Days)"]),
            "product": text(first["Product"]), "origin": text(first["Origin"]),
            "destination": text(first["Destination"]), "carrier": text(first["Carrier"]),
            "alarmed": None if pd.isna(first["Is Alarmed"]) else first["Is Alarmed"] == "Yes",
        }
    return out


# ---- the aggregate file ----------------------------------------------------------------------------------------------

def excel_bytes(table: pd.DataFrame) -> bytes:
    """The aggregate as the .xlsx the export looks like: a title row, a blank row, then the header row (verbatim
    header texts) and the data. `table` may carry the app's extra columns; they are left out."""
    out = table.reindex(columns=AGGREGATE_COLUMNS)
    out.columns = EXCEL_HEADERS
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl", datetime_format=DATETIME_FORMAT) as writer:
        out.to_excel(writer, sheet_name=SHEET_NAME, index=False, startrow=2)
        sheet = writer.sheets[SHEET_NAME]
        sheet["A1"] = SHEET_NAME
        sheet["A1"].font = sheet["A1"].font.copy(bold=True, size=18)
        for cell in sheet[3]:
            cell.alignment = cell.alignment.copy(wrap_text=True, vertical="center")
            cell.font = cell.font.copy(bold=True)
        for column, header in zip(sheet.iter_cols(min_row=3, max_row=3), EXCEL_HEADERS):
            sheet.column_dimensions[column[0].column_letter].width = min(max(len(max(header.split("\n"), key=len)) + 4, 12), 32)
        sheet.row_dimensions[3].height = 32
    return buffer.getvalue()


def sync_program(program: str, records: dict[str, dict], token_getter) -> tuple[list[dict], pd.DataFrame]:
    """Bring the store up to date for EVERY trip in `records` (stored trips are reused, the rest fetched), then
    build the aggregate of all of them and write it to the store. Returns (payloads, aggregate)."""
    ids = list(records)
    saved = stored_payloads(program, ids, records)
    needed = expected_calls(ids, records, saved)
    token = token_getter() if needed else ""
    payloads = fetch_payloads(program, ids, records, saved, token)
    table, _readings, _route = build_tables(payloads, None, None, records)
    cache.write_bytes(cache.aggregate_path(program), excel_bytes(table))
    return payloads, table


# ---- command line --------------------------------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch SWP trips (store first) and write the raw JSON files and the aggregate Excel.")
    parser.add_argument("--program", default=config.SWP_PROGRAM_ID, help="program id (default: SWP_PROGRAM_ID)")
    parser.add_argument("--status", help="only trips with this status, e.g. Arrived")
    parser.add_argument("--limit", type=int, default=0, help="only the newest N trips (default: all)")
    parser.add_argument("--out", default="swp_output", help="folder to write into")
    args = parser.parse_args()

    records = client.all_trips(args.program)
    want = (args.status or "").replace(" ", "").lower()
    chosen = [r for r in records if not want or client.status_name(r).lower() == want]
    chosen.sort(key=lambda r: r.get("lastUpdatedDate") or "", reverse=True)
    if args.limit:
        chosen = chosen[: args.limit]
    payloads, table = sync_program(args.program, {r["tripID"]: r for r in chosen}, client.get_token)

    out = Path(args.out)
    (out / "raw").mkdir(parents=True, exist_ok=True)
    for p in payloads:
        (out / "raw" / f"{p['tripID']}.json").write_text(json.dumps(p, indent=1, default=str), encoding="utf-8")
    (out / AGGREGATE_FILE).write_bytes(excel_bytes(table))
    print({"trips": len(payloads), "rows": len(table), "folder": str(out)})


if __name__ == "__main__":
    main()
