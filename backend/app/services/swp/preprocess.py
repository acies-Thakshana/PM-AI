"""Pre-processing of SWP API data: from the raw API responses to the aggregate file and the raw-data archive.

  raw API responses  --->  raw archive        one JSON file per trip, exactly as the API returned it (list record,
        |                                      basic trip, trip detail with sensor readings and GPS route), zipped
        v
  aggregate table    --->  aggregate file     "Tabular Shipment Data.xlsx": the SensiWatch export's columns, in its
                                               order and with its header texts, one row per trip, logger and sensor

Why this split: the API's answers are nested and differ from trip to trip, so the raw files stay JSON -- nothing is
lost, and the aggregate can be rebuilt from them later without calling the API again (the API is rate limited).
The aggregate is flat and tabular, so it is Excel, the format the rest of the app (and people) already work in.

The mapping of API fields to columns lives in transform.py (trip_rows); this module fetches (with the on-disk cache),
orders and writes. It can also be run by itself:

    python -m app.services.swp.preprocess --program 1968 --status Arrived --limit 20 --out out/
    python -m app.services.swp.preprocess --program 1968 --trip-ids <guid> <guid> --out out/
"""
from __future__ import annotations

import argparse
import io
import json
import zipfile
from pathlib import Path

import pandas as pd

from app import config
from app.services.swp import cache, client
from app.services.swp.transform import EXPORT_COLUMNS, build_tables

AGGREGATE_FILE = "Tabular Shipment Data.xlsx"
RAW_ARCHIVE = "SWP raw data.zip"
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


# ---- fetching: the raw API responses -----------------------------------------------------------------------------

def cached_payloads(program: str, ids: list[str], records: dict[str, dict]) -> dict[str, dict]:
    """Payloads of ARRIVED trips fetched before (an arrived trip no longer changes), by trip id."""
    saved: dict[str, dict] = {}
    for tid in ids:
        if client.status_name(records[tid]) == "Arrived":
            hit = cache.load_trip(program, tid)
            if hit and hit.get("detail"):
                saved[tid] = {"tripID": tid, "record": records[tid], "basic": hit["basic"], "detail": hit["detail"]}
    return saved


def expected_calls(ids: list[str], records: dict[str, dict], saved: dict[str, dict]) -> int:
    """API calls fetch_payloads will make: the detail of every trip not cached, plus the single-trip call when the
    list record lacks its basics, plus a token when any call is made at all."""
    calls = sum(0 if t in saved else (1 if "serialNumbers" in records[t] else 2) for t in ids)
    return calls + (1 if calls and not client.has_token() else 0)


def fetch_payloads(program: str, ids: list[str], records: dict[str, dict], saved: dict[str, dict], token: str) -> list[dict]:
    """The raw payload of each trip, in the order of `ids`: from the cache where possible, else from the API."""
    payloads = []
    for tid in ids:
        if tid in saved:
            payloads.append(saved[tid])
            continue
        # The list record already carries the basic fields (serial numbers), which saves one rate-limited call.
        basic = records[tid]
        if "serialNumbers" not in basic:
            basic = client.get_trip(token, tid, program)
        detail = client.get_trip_detail(token, tid, program)
        if client.status_name(records[tid]) == "Arrived":
            cache.save_trip(program, tid, basic, detail)
        payloads.append({"tripID": tid, "record": records[tid], "basic": basic, "detail": detail})
    return payloads


# ---- the raw archive ---------------------------------------------------------------------------------------------

def raw_zip(payloads: list[dict], program: str = "") -> bytes:
    """A zip of raw/<trip guid>.json per trip plus manifest.json (what is in it)."""
    manifest = {"program": program, "source": "SWP API", "trips": []}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for p in payloads:
            name = f"raw/{p['tripID']}.json"
            archive.writestr(name, json.dumps(p, indent=1, default=str))
            manifest["trips"].append({
                "tripID": p["tripID"], "tripNumber": (p.get("detail") or {}).get("id"),
                "status": client.status_name(p.get("record") or {}), "file": name,
            })
        archive.writestr("manifest.json", json.dumps(manifest, indent=1))
    return buffer.getvalue()


# ---- the aggregate file ------------------------------------------------------------------------------------------

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


# ---- the whole run ------------------------------------------------------------------------------------------------

def run(program: str, trip_ids: list[str], out_dir: Path, sensors: list[str] | None = None, edits: dict | None = None) -> dict:
    """Fetch the trips (cache first), then write out_dir/'Tabular Shipment Data.xlsx' and out_dir/'SWP raw data.zip'."""
    records_list = client.all_trips(program)
    records = {r["tripID"]: r for r in records_list}
    by_lower = {k.lower(): k for k in records}
    ids = [by_lower[t.lower()] for t in trip_ids if t.lower() in by_lower]
    if not ids:
        raise client.SwpError("None of those trips is in the program.")
    saved = cached_payloads(program, ids, records)
    token = client.get_token() if expected_calls(ids, records, saved) else ""
    payloads = fetch_payloads(program, ids, records, saved, token)
    table, _readings, _route = build_tables(payloads, sensors, edits, records)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / AGGREGATE_FILE).write_bytes(excel_bytes(table))
    (out_dir / RAW_ARCHIVE).write_bytes(raw_zip(payloads, program))
    return {"trips": len(ids), "rows": len(table), "aggregate": str(out_dir / AGGREGATE_FILE), "raw": str(out_dir / RAW_ARCHIVE)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch SWP trips and write the aggregate Excel and the raw JSON archive.")
    parser.add_argument("--program", default=config.SWP_PROGRAM_ID, help="program id (default: SWP_PROGRAM_ID)")
    parser.add_argument("--status", help="only trips with this status, e.g. Arrived")
    parser.add_argument("--limit", type=int, default=10, help="how many trips (newest first) when no ids are given")
    parser.add_argument("--trip-ids", nargs="*", default=[], help="specific trip GUIDs")
    parser.add_argument("--out", default="swp_output", help="folder to write into")
    args = parser.parse_args()
    ids = args.trip_ids
    if not ids:
        want = (args.status or "").replace(" ", "").lower()
        trips = [r for r in client.all_trips(args.program) if not want or client.status_name(r).lower() == want]
        trips.sort(key=lambda r: r.get("lastUpdatedDate") or "", reverse=True)
        ids = [r["tripID"] for r in trips[: args.limit]]
    print(run(args.program, ids, Path(args.out)))


if __name__ == "__main__":
    main()
