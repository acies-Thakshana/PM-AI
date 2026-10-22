"""Pre-processing of SWP API data: the trip list, the stored raw data and the aggregate table.

  call 2, trip search  --->  the trip list. One record per trip, with SWP's own trip statistics: enough to show every trip
                             with its mean temperature and segment days right away (record_kpis below).
  call 4, trip detail  --->  raw store        one JSON file per trip, exactly as the API returned it (the search record and
                             the detail with sensor readings and GPS route); see cache.py. Fetched in the background by
                             prefetch.py for the trips that will be analysed. Nothing is fetched twice: an arrived trip
                             never changes, any other trip is fetched again only when its lastUpdatedDate moved.
  aggregate table      --->  the SensiWatch export's columns, in its order, one row per trip, logger and sensor. Always
                             rebuilt from the raw files (transform.py holds the field-to-column mapping) and written to the
                             store as 'Tabular Shipment Data.xlsx' with the export's header texts.

Why JSON for the raw data: the API's answers are nested and differ from trip to trip, so they are kept as they come and the
aggregate can be rebuilt from them (a new column, a corrected conversion) without calling the rate-limited API.
The aggregate is flat and tabular, so it is a DataFrame in the app and Excel on disk, the format people already use.

Run by itself (fetches with the key pool, writes the raw JSON files and the Excel into a folder):

    python -m app.services.swp.preprocess --program 1968 --status Arrived --limit 20 --out out/
"""
from __future__ import annotations

import argparse
import io
import json
import re
from pathlib import Path

import pandas as pd

from app import config
from app.services.swp import cache, client
from app.services.swp.transform import EXPORT_COLUMNS, build_tables, f_to_c, pick

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


# ---- the raw data in the store --------------------------------------------------------------------------------------

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


def payloads_for(program: str, ids: list[str], records: dict[str, dict], on_progress=None) -> list[dict]:
    """The raw payload of each trip, in the order of `ids`. What the background fetch already stored is used; anything
    outstanding is waited for (the fetch runs on every key at once)."""
    from app.services.swp import prefetch  # imported here: prefetch itself uses this module

    prefetch.submit(program, ids, records)
    prefetch.wait(program, ids, on_progress)
    stored = stored_payloads(program, ids, records)
    missing = [t for t in ids if t not in stored]
    if missing:
        raise client.SwpError(f"{len(missing)} trip(s) could not be read from the store after fetching: {missing[:3]}")
    return [stored[t] for t in ids]


# ---- what the Configure page shows per trip: from the search record alone --------------------------------------------

def _days(text: str | None) -> float | None:
    """'3.17:00:00' (days.hours:minutes:seconds) -> days."""
    m = re.match(r"(?:(\d+)\.)?(\d+):(\d+):(\d+)", text or "")
    if not m:
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d + h / 24 + mi / 1440 + s / 86400


def record_kpis(record: dict) -> dict:
    """The numbers of one trip, read from its search record (no detail call): mean temperature in Celsius from SWP's own trip
    statistics, segment days from tripLength, and the names. For a trip still on its way both are as of the moment of the search."""
    mean_f = pick(record, "tripStatistics", "tempVariance", "mean")
    days = _days(record.get("tripLength"))
    product = next((p.get("productName") for d in record.get("destinations") or [] for p in d.get("products") or [] if p.get("productName")), None)
    return {
        "number": None if record.get("id") is None else str(record["id"]),
        "mean_temp": None if mean_f is None else round(f_to_c(mean_f), 2),
        "segment_days": None if days is None else round(days, 2),
        "product": product,
        "origin": pick(record, "tripOrigin", "locations", "locationName"),
        "destination": pick(record, "destinations", "locationName"),
        "carrier": pick(record, "tripOrigin", "carrier", "name"),
        "alarmed": record.get("alarmed"),
        "departure": pick(record, "tripOrigin", "actualDepartureTime") or client.departure_of(record),
        "arrival": record.get("tripActualArrivalTime") or client.arrival_of(record),
    }


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
    by_id = {r["tripID"]: r for r in chosen}
    payloads = payloads_for(args.program, list(by_id), by_id, lambda done, total: print(f"  {done}/{total} trip details", end="\r"))
    table, _readings, _route = build_tables(payloads, None, None, by_id)

    out = Path(args.out)
    (out / "raw").mkdir(parents=True, exist_ok=True)
    for p in payloads:
        (out / "raw" / f"{p['tripID']}.json").write_text(json.dumps(p, indent=1, default=str), encoding="utf-8")
    (out / AGGREGATE_FILE).write_bytes(excel_bytes(table))
    print({"trips": len(payloads), "rows": len(table), "folder": str(out)})


if __name__ == "__main__":
    main()
