#!/usr/bin/env python
"""Fetch every Arrived and InTransit trip of the last quarter and time each API call.

Standalone: it needs only `requests` and `openpyxl` (and python-dotenv if installed). It does not use the app.

What it does
  1. Gets a token.
  2. Call 2, trip search: pages through the search for each status (Arrived, InTransit) and times every page.
  3. Keeps the trips whose departure falls in the quarter (default: the last full calendar quarter, so on
     2026-10-22 that is 1 July to 30 September 2026).
  4. Call 4, trip detail: fetches every one of those trips and times every call.
  5. Writes swp_timing_<from>_<to>.xlsx (Summary, Timing & rate limits, Search calls (2), Detail calls (4)) and, unless
     --no-raw, the raw JSON of every trip (the search record and the detail) under raw/.
     "Timing & rate limits" holds what was measured, the API's call limits and an estimate of how long N trips take.
  Add that tab to a workbook from an earlier run:  python scripts/swp_timing_check.py --add-limits FILE.xlsx

Timing: each call is timed from sending the request until the whole answer has been received (`seconds`); `first byte`
is the part of that until the server started to answer, so `seconds - first byte` is the download time. The pause
between calls (the API allows 20 calls a minute) is not part of any call's time; it is reported separately.

Usage (from the backend folder; credentials come from backend/.env, see .env.example):
  python scripts/swp_timing_check.py                                  # last quarter, both statuses, all trips
  python scripts/swp_timing_check.py --program 651
  python scripts/swp_timing_check.py --from 2026-07-01 --to 2026-09-30
  python scripts/swp_timing_check.py --all                            # EVERY trip the search returns, any date
  python scripts/swp_timing_check.py --limit 5                        # only 5 detail calls, to try it quickly
  python scripts/swp_timing_check.py --statuses Arrived --delay 3.2
"""
from __future__ import annotations

import argparse
import calendar
import collections
import json
import os
import statistics
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BACKEND = Path(__file__).resolve().parents[1]
SEARCH_PATH = "/api/trip/external/ExternalTrip/tripsearch/programId/{program}"
DETAIL_PATH = "/api/trip/external/ExternalTripDetail/programId/{program}/tripId/{trip}"
TOKEN_PATH = "/api/security-external/external/auth/connect/token"
REQUIRED = ("SWP_BASE_URL", "SWP_SECURITY_KEY", "SWP_TRIP_KEY", "SWP_USER", "SWP_PASS")


def load_env() -> None:
    env_file = BACKEND / ".env"
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file)
        return
    except ImportError:
        pass
    if env_file.is_file():  # a minimal reader when python-dotenv is not installed
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def last_quarter(today: date) -> tuple[date, date]:
    quarter, year = (today.month - 1) // 3 - 1, today.year
    if quarter < 0:
        quarter, year = 3, year - 1
    last_month = 3 * quarter + 3
    return date(year, 3 * quarter + 1, 1), date(year, last_month, calendar.monthrange(year, last_month)[1])


class Timer:
    """Makes the calls, keeps one row per call, and paces them."""

    def __init__(self, base: str, delay: float):
        self.base, self.delay = base, delay
        self.session = requests.Session()
        self.rows: list[dict] = []
        self.slept = 0.0

    def call(self, kind: str, label: str, method: str, path: str, key: str, token: str | None = None, **kwargs):
        headers = {"Ocp-Apim-Subscription-Key": key}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        retries, data = 0, None
        while True:
            started = datetime.now()
            t0 = time.perf_counter()
            error = ""
            try:
                response = self.session.request(method, self.base + path, headers=headers, timeout=120, **kwargs)
                seconds = time.perf_counter() - t0
                first_byte, size, status = response.elapsed.total_seconds(), len(response.content), response.status_code
            except requests.RequestException as exc:
                seconds, first_byte, size, status, response, error = time.perf_counter() - t0, 0.0, 0, 0, None, str(exc)[:120]
            self.rows.append({
                "kind": kind, "label": label, "started": started.strftime("%H:%M:%S"), "seconds": round(seconds, 3),
                "first_byte": round(first_byte, 3), "kb": round(size / 1024, 1), "http": status or error, "retry": retries,
            })
            if status == 200:
                data = response.json()
            elif status in (429, 403) and retries < 3:  # too many calls in a minute: wait it out and try again
                retries += 1
                print(f"    HTTP {status} (rate limit); waiting 65 s, retry {retries}")
                time.sleep(65)
                self.slept += 65
                continue
            else:
                print(f"    FAILED {label}: HTTP {status or error}")
            break
        time.sleep(self.delay)  # the pause is not part of the call's time
        self.slept += self.delay
        return data, self.rows[-1]


def departure_of(record: dict) -> datetime | None:
    """The trip's departure (UTC) from its search record: actual departure, else created."""
    origin = record.get("tripOrigin") or {}
    text = origin.get("actualDepartureTime") or record.get("createDate")
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def readings_in(detail: dict) -> int:
    return sum(len(dev.get(k) or []) for dev in detail.get("sensorData") or [] for k in ("temperatureData", "lightData", "humidityData"))


def summarize(rows: list[dict]) -> dict:
    seconds = sorted(r["seconds"] for r in rows)
    if not seconds:
        return {"calls": 0}
    pick = lambda q: seconds[min(len(seconds) - 1, int(q * len(seconds)))]  # noqa: E731
    return {
        "calls": len(seconds), "total s": round(sum(seconds), 1), "mean s": round(statistics.mean(seconds), 2),
        "median s": round(statistics.median(seconds), 2), "p90 s": round(pick(0.9), 2), "max s": round(seconds[-1], 2),
        "min s": round(seconds[0], 2), "avg KB": round(statistics.mean(r["kb"] for r in rows), 1),
        "avg first byte s": round(statistics.mean(r["first_byte"] for r in rows), 2),
    }


# What the SWP guide says (Troubleshooting, "Too many API requests (429/403)"): calls per 60 seconds and per 3600 seconds.
RATE_LIMITS = [
    ("external-trip: trip search, get trip, trip detail (calls 2, 3, 4)", 20, 1000),
    ("external-trip-manage: create / update trip (not enabled here)", 20, 500),
    ("external-trip-monitor: monitor (sensor) data (not used here)", 30, 1000),
]


def add_limits_sheet(wb, search_rows: list[dict], detail_rows: list[dict], found: dict, pause: float) -> None:
    """The 'Timing & rate limits' tab: what was measured, the API's limits, and a live estimate for N trips."""
    ws = wb.create_sheet("Timing & rate limits", 1)
    bold, head = Font(bold=True), PatternFill("solid", fgColor="010198")

    def put(*values, style=None):
        ws.append(list(values))
        if style == "title":
            ws.cell(row=ws.max_row, column=1).font = Font(bold=True, size=14)
        elif style == "head":
            for cell in ws[ws.max_row]:
                if cell.value is not None:
                    cell.font, cell.fill = Font(bold=True, color="FFFFFF"), head
        return ws.max_row

    s2, s4 = summarize(search_rows), summarize(detail_rows)
    put("Timing and rate limits", style="title")
    put()
    put("1. Measured in this run", style="head")
    put("Trip search (call 2)", "", "", "", "")
    put("  calls (pages of up to 50 trips)", s2.get("calls"))
    put("  trips retrieved with the statuses asked for", found.get("total"), found.get("detail", ""))
    put("  total time in the search calls, seconds", s2.get("total s"))
    put("  mean / slowest call, seconds", s2.get("mean s"), s2.get("max s"))
    mean_search = put("  mean seconds per search call", s2.get("mean s"))
    put("Trip detail (call 4), one trip per call", "", "", "", "")
    put("  calls (trips)", s4.get("calls"))
    mean_detail = put("  mean seconds for one trip", s4.get("mean s"))
    put("  median / fastest / slowest, seconds", s4.get("median s"), s4.get("min s"), s4.get("max s"))
    put("  average size of a detail answer, KB", s4.get("avg KB"))
    put("Pause the script leaves between calls, seconds", pause)
    pause_row = ws.max_row
    put()
    put("2. Rate limits (SWP getting-started guide)", style="head")
    put("API product", "Calls per minute", "Calls per hour", "Average gap at the limit, s (60 / calls per minute)", "Pace sustained over an hour, s per call")
    ws.cell(row=ws.max_row, column=1).font = bold
    first_limit = ws.max_row + 1
    for name, per_minute, per_hour in RATE_LIMITS:
        r = ws.max_row + 1
        put(name, per_minute, per_hour, f"=60/B{r}", f"=3600/MIN(B{r}*60,C{r})")
    put("Over the limit the API answers HTTP 429 (or 403). The script then waits 65 seconds and retries, up to 3 times.")
    put("Sensor-data answers can be too large: the guide advises asking for a few trips at a time (an overlarge answer can be an HTTP 500).")
    put("To go faster the guide suggests a parallel process with a different subscription key: see section 5.")
    put()
    put("3. What the limits mean", style="head")
    put("The limit is a number of calls per window (20 in any 60 seconds), not a required pause: calls can be made faster in a burst, as long as no more than 20 fall in one minute.")
    put("On average that is one call every 3 seconds. A call takes about 1 second, so the limit, not the API, sets the pace.")
    put("This script simply waits 3.1 s after every call. That is safe but a little slower than needed: with the call itself it makes about 14 calls a minute, not 20.")
    put("The hourly cap (1000) is lower than 20 a minute for an hour (1200): a run of more than about 50 minutes of calls reaches it.")
    put()
    put("4. How long will N trips take?", style="head")
    put("See the 'Simple estimate' tab: one table for one key and for several keys, in minutes, with the calculation in plain words.")
    put()
    put("5. Going faster: a second subscription key (a parallel process)", style="head")
    put("What the guide says: if you get HTTP 429/403 'space out your requests or create a parallel process by using a different subscription key'.")
    put("Why it works: the limits (20 calls a minute, 1000 an hour) are counted per subscription key. A second key has its own counter.")
    put("So two processes, each with its own key, can each make 20 calls a minute: 40 in all. N keys give about N times the speed.")
    put("Whether the limit is really counted per key depends on how Sensitech set it up (the guide does not say): test with both processes at once and watch for HTTP 429.")
    put()
    put("How to set it up", style="head")
    put("1. Developer portal: Products, the trip API product, Subscribe again under a new name (for example 'Trip API worker 2').")
    put("2. Sensitech approves the subscription and emails you; until then the key is visible in your profile but does not work.")
    put("3. Split the trips into lists and give each list to its own process, each with its own key and its own pause (about 3 s) between calls.")
    put("4. The login token (valid 1 hour) can be shared by all processes; only the trip calls need a process's own key.")
    put("5. Keep the search (call 2) in one process: it is only a few calls. Spread the detail calls (call 4), one per trip, across the keys.")
    put("In this app: SWP_TRIP_KEY is a single key and the client makes one call at a time; using several keys needs a list of keys (for example SWP_TRIP_KEYS).")
    put()
    put("The estimate for one key and for several keys is in the 'Simple estimate' tab.")
    for letter, width in zip("ABCDEF", (66, 22, 22, 30, 28, 36)):
        ws.column_dimensions[letter].width = width
    add_simple_sheet(wb, s2.get("mean s") or 0, s4.get("mean s") or 0, pause)


def add_simple_sheet(wb, mean_search: float, mean_detail: float, pause: float) -> None:
    """The 'Simple estimate' tab: the calculation in plain steps and one table for 1 key and for several keys, in minutes."""
    ws = wb.create_sheet("Simple estimate", 1)
    blue = PatternFill("solid", fgColor="DCEBFF")
    head = PatternFill("solid", fgColor="010198")

    def put(*values, bold=False, size=None, header=False):
        ws.append(list(values))
        for cell in ws[ws.max_row]:
            if cell.value is None:
                continue
            if header:
                cell.font, cell.fill, cell.alignment = Font(bold=True, color="FFFFFF"), head, Alignment(wrap_text=True, vertical="center")
            elif bold or size:
                cell.font = Font(bold=True, size=size or 11)
        return ws.max_row

    put("How long will it take?", size=14)
    put("Change the blue cells. Everything else is worked out from them.")
    put()
    put("Inputs", header=True)
    put("Calls the API allows per minute, per key", 20)
    per_minute = ws.max_row
    put("Seconds between calls at that limit (60 / calls per minute)", f"=60/B{per_minute}")
    gap = ws.max_row
    put("Statuses searched (Arrived, InTransit = 2)", 2)
    statuses = ws.max_row
    put("Trips one search call returns", 50)
    page = ws.max_row
    put("Seconds one search call takes (measured)", mean_search)
    t_search = ws.max_row
    put("Seconds one trip-detail call takes (measured)", mean_detail)
    t_detail = ws.max_row
    put("Pause the script adds after every call, seconds", pause)
    pause_row = ws.max_row
    put("Calls the API allows per hour, per key", 1000)
    hourly = ws.max_row
    for r in (per_minute, statuses, page, t_search, t_detail, pause_row, hourly):
        ws.cell(row=r, column=2).fill = blue
    put()
    put("The calculation, in plain words", header=True)
    put("1. Every trip needs one trip-detail call. So N trips = N detail calls.")
    put("2. Add the search: one call per status plus one more per 50 trips. Add 1 call for the login token.")
    put("3. Total calls = token + search calls + N.")
    put("4. TIME LIMIT BETWEEN CALLS: the API allows 20 calls a minute per key, which is one call every 3 seconds on average. So the fastest possible time with ONE key = total calls x 3 seconds.")
    put("5. With TWO keys the detail calls are shared out, each key making half of them (each key still keeps its own 3 seconds between its calls), so the time is about halved.")
    put("6. 'Today's script' is slower than the best case: after every call it waits 3.1 seconds, on top of the call's own time (about 1 second), so about 4.2 seconds per call.")
    put()
    put("Worked example for 100 trips", header=True)
    put("Trips", 100)
    n_row = ws.max_row
    ws.cell(row=n_row, column=2).fill = blue
    put("Search calls (statuses + trips / 50, rounded up)", f"=B{statuses}+ROUNDUP(B{n_row}/B{page},0)")
    sc = ws.max_row
    put("Total calls (1 token + search + one per trip)", f"=1+B{sc}+B{n_row}")
    tc = ws.max_row
    put("Time limit between calls (per key)", f'=TEXT(B{gap},"0.0")&" seconds, on average (20 calls a minute)"')
    put("Fastest possible with 1 key", f'=TEXT(B{tc}*B{gap},"0")&" seconds  =  "&TEXT(B{tc}*B{gap}/60,"0.0")&" minutes"')
    put("Fastest possible with 2 keys", f'=TEXT((1+B{sc}+ROUNDUP(B{n_row}/2,0))*B{gap},"0")&" seconds  =  "&TEXT((1+B{sc}+ROUNDUP(B{n_row}/2,0))*B{gap}/60,"0.0")&" minutes"')
    put("Today's script with 1 key", f'=TEXT(B{tc}*B{pause_row}+B{sc}*B{t_search}+B{n_row}*B{t_detail},"0")&" seconds  =  "&TEXT((B{tc}*B{pause_row}+B{sc}*B{t_search}+B{n_row}*B{t_detail})/60,"0.0")&" minutes"')
    put()
    put("All sizes: 1 key and 2 keys, in minutes", header=True)
    put("Trips (N)", "Total calls", "Time limit between calls, s (per key)", "Today's script, 1 key (min)", "Fastest, 1 key (min)", "Fastest, 2 keys (min)", "Hourly cap per key (1000 calls)")
    for cell in ws[ws.max_row]:
        cell.font, cell.fill, cell.alignment = Font(bold=True, color="FFFFFF"), head, Alignment(wrap_text=True, vertical="center")
    for n in (30, 50, 100, 250, 500, 1000, 2000):
        r = ws.max_row + 1
        search = f"($B${statuses}+ROUNDUP(A{r}/$B${page},0))"
        put(
            n,
            f"=1+{search}+A{r}",
            f"=$B${gap}",
            f"=(B{r}*$B${pause_row}+{search}*$B${t_search}+A{r}*$B${t_detail})/60",
            f"=B{r}*$B${gap}/60",
            f"=(1+{search}+ROUNDUP(A{r}/2,0))*$B${gap}/60",
            f'=IF(B{r}>$B${hourly},"1 key: over (at least "&TEXT(B{r}/$B${hourly},"0.0")&" h); 2 keys: "&IF(B{r}/2>$B${hourly},"over","within"),"within")',
        )
        ws.cell(row=r, column=1).fill = blue
        ws.cell(row=r, column=3).number_format = "0.0"
        for col in range(4, 7):
            ws.cell(row=r, column=col).number_format = "0.0"
    put()
    put("Notes", header=True)
    put("Minutes. 'Fastest' means calls spaced exactly at the time limit (3 seconds apart per key) with nothing wasted; real runs are a little slower.")
    put("The time limit is an average: the API counts 20 calls in any 60 seconds, so calls can also be made in a short burst as long as 20 a minute is not exceeded.")
    put("Two keys need a second subscription key from the SWP developer portal (approved by Sensitech) and the script split into two processes, one per key.")
    put("Whether the limit is counted per key is not stated in the guide; test it before relying on it.")
    for letter, width in zip("ABCDEFG", (62, 14, 24, 22, 20, 20, 44)):
        ws.column_dimensions[letter].width = width


def write_workbook(path: Path, summary_rows: list[list], search: list[dict], detail: list[dict], found: dict, pause: float) -> None:
    wb = Workbook()

    def sheet(title: str, headers: list[str], rows: list[list], widths: list[int], first: bool = False):
        ws = wb.active if first else wb.create_sheet()
        ws.title = title
        ws.append(headers)
        for row in rows:
            ws.append(row)
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="010198")
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        for i, width in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = width
        ws.freeze_panes = "A2"

    sheet("Summary", ["Measure", "Value"], summary_rows, [44, 70], first=True)
    sheet("Search calls (2)", ["#", "Search", "Started", "Seconds", "First byte s", "KB", "Records", "HTTP", "Retries"],
          [[i, r["label"], r["started"], r["seconds"], r["first_byte"], r["kb"], r.get("records", ""), r["http"], r["retry"]] for i, r in enumerate(search, 1)],
          [6, 36, 10, 10, 12, 10, 10, 8, 8])
    sheet("Detail calls (4)", ["#", "Trip", "Status", "Departure", "Started", "Seconds", "First byte s", "KB", "Readings", "HTTP", "Retries"],
          [[i, r["label"], r.get("status", ""), r.get("departure", ""), r["started"], r["seconds"], r["first_byte"], r["kb"], r.get("readings", ""), r["http"], r["retry"]]
           for i, r in enumerate(detail, 1)],
          [6, 40, 12, 18, 10, 10, 12, 10, 10, 8, 8])
    add_limits_sheet(wb, search, detail, found, pause)
    wb.save(path)


def add_to_existing(path: Path, pause: float) -> None:
    """Add the 'Timing & rate limits' tab to a workbook from an earlier run (it is rebuilt from that workbook's own tabs)."""
    from openpyxl import load_workbook

    wb = load_workbook(path)
    for name in list(wb.sheetnames):  # these two tabs are rebuilt below (also any copy a repeated run left, e.g. "Simple estimate1")
        if name.startswith(("Timing & rate limits", "Simple estimate")):
            del wb[name]
    summary = {r[0]: r[1] for r in wb["Summary"].iter_rows(min_row=2, values_only=True) if r[0]}
    headers = [c.value for c in wb["Search calls (2)"][1]]
    search = [dict(zip(headers, r)) for r in wb["Search calls (2)"].iter_rows(min_row=2, values_only=True)]
    search = [{"seconds": r["Seconds"], "kb": r["KB"], "first_byte": r["First byte s"], "records": r.get("Records")} for r in search]
    headers = [c.value for c in wb["Detail calls (4)"][1]]
    detail = [dict(zip(headers, r)) for r in wb["Detail calls (4)"].iter_rows(min_row=2, values_only=True)]
    detail = [{"seconds": r["Seconds"], "kb": r["KB"], "first_byte": r["First byte s"]} for r in detail]
    found = {"total": summary.get("Trips found with those statuses")}
    add_limits_sheet(wb, search, detail, found, pause)
    try:
        wb.save(path)
        print("added the Timing & rate limits tab to", path)
    except PermissionError:  # the workbook is open in Excel: leave it alone and save a copy next to it
        copy = path.with_name(path.stem + "_updated.xlsx")
        wb.save(copy)
        print(f"{path.name} is open in Excel, so it was not changed. Saved a copy with the new tab: {copy}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--program", default="", help="program id (default: SWP_PROGRAM_ID)")
    parser.add_argument("--from", dest="start", help="first departure date, YYYY-MM-DD (default: start of the last quarter)")
    parser.add_argument("--to", dest="end", help="last departure date, YYYY-MM-DD (default: end of the last quarter)")
    parser.add_argument("--all", action="store_true", help="every trip the search returns, whatever its departure date (no date filter)")
    parser.add_argument("--statuses", default="Arrived,InTransit", help="comma separated (default Arrived,InTransit)")
    parser.add_argument("--limit", type=int, default=0, help="stop after this many detail calls (default: all)")
    parser.add_argument("--delay", type=float, default=3.1, help="pause after each call, seconds (the API allows 20 calls a minute)")
    parser.add_argument("--out", default="swp_timing_output", help="folder to write into")
    parser.add_argument("--no-raw", action="store_true", help="do not save the raw JSON of each trip")
    parser.add_argument("--add-limits", metavar="FILE", help="add the Timing & rate limits tab to a workbook from an earlier run and exit")
    args = parser.parse_args()
    if args.add_limits:
        add_to_existing(Path(args.add_limits), args.delay)
        return

    load_env()
    missing = [k for k in REQUIRED if not os.getenv(k)]
    program = args.program or os.getenv("SWP_PROGRAM_ID", "")
    if not program:
        missing.append("SWP_PROGRAM_ID")
    if missing:
        sys.exit("Set in backend/.env: " + ", ".join(missing))
    start, end = (date.fromisoformat(args.start), date.fromisoformat(args.end)) if args.start and args.end else last_quarter(date.today())
    period = "all dates" if args.all else f"{start} to {end}"
    statuses = [s.strip() for s in args.statuses.split(",") if s.strip()]
    wanted = {s.replace(" ", "").lower() for s in statuses}
    print(f"Program {program}; trips departing {period}; statuses {', '.join(statuses)}")

    timer = Timer(os.environ["SWP_BASE_URL"].rstrip("/"), args.delay)
    wall = time.perf_counter()

    # token
    data, row = timer.call("token", "token", "POST", TOKEN_PATH, os.environ["SWP_SECURITY_KEY"], data={
        "grant_type": "password", "client_id": os.getenv("SWP_CLIENT_ID", "common_client_jwt"),
        "client_secret": os.getenv("SWP_CLIENT_SECRET", "secret"), "scope": "rtweb.api offline_access",
        "username": os.environ["SWP_USER"], "password": os.environ["SWP_PASS"]})
    if not data:
        sys.exit("Could not get a token.")
    token = data["access_token"]
    print(f"token: {row['seconds']} s")

    # call 2: search, every page of every status
    found: dict[str, dict] = {}
    for status in statuses:
        page = 0
        while True:
            body, row = timer.call("search", f"{status}, page {page}", "POST", SEARCH_PATH.format(program=program),
                                   os.environ["SWP_TRIP_KEY"], token, json={"keyword": status, "from": page})
            records = (body or {}).get("records") or []
            for record in records:
                if str(record.get("tripStatus", "")).replace(" ", "").lower() in wanted:
                    found[record["tripID"]] = record
            row["records"] = len(records)
            print(f"search {status} page {page}: {len(records)} records, {row['seconds']} s, {row['kb']} KB")
            total = (body or {}).get("overallTotal", 0)
            if not records or (page + 1) * 50 >= total:
                break
            page += 1

    # keep the quarter
    chosen, no_departure = [], 0
    for record in found.values():
        departed = departure_of(record)
        if departed is None:
            no_departure += 1
        if args.all or (departed is not None and start <= departed.date() <= end):
            chosen.append((departed, record))
    chosen.sort(key=lambda item: item[0] or datetime.min.replace(tzinfo=timezone.utc))
    kept = "taking every one" if args.all else f"{len(chosen)} departed in {start} to {end}"
    print(f"{len(found)} trips with those statuses; {kept}; {no_departure} without a departure date")
    if args.limit:
        chosen = chosen[: args.limit]

    # call 4: detail, one per trip
    out = Path(args.out)
    if not args.no_raw:
        (out / "raw").mkdir(parents=True, exist_ok=True)
    detail_rows: list[dict] = []
    for index, (departed, record) in enumerate(chosen, 1):
        trip_id = record["tripID"]
        detail, row = timer.call("detail", trip_id, "GET", DETAIL_PATH.format(program=program, trip=trip_id), os.environ["SWP_TRIP_KEY"], token)
        row.update(status=record.get("tripStatus"), departure=departed.strftime("%Y-%m-%d %H:%M") if departed else "", readings=readings_in(detail) if detail else "")
        detail_rows.append(row)
        print(f"[{index}/{len(chosen)}] detail {trip_id} {record.get('tripStatus')}: {row['seconds']} s, {row['kb']} KB, {row['readings']} readings")
        if detail and not args.no_raw:
            (out / "raw" / f"{trip_id}.json").write_text(json.dumps({"tripID": trip_id, "record": record, "detail": detail}), encoding="utf-8")

    # results
    elapsed = time.perf_counter() - wall
    search_rows = [r for r in timer.rows if r["kind"] == "search"]
    s2, s4 = summarize(search_rows), summarize(detail_rows)
    by_status = {st: summarize([r for r in detail_rows if r.get("status") == st]) for st in sorted({r.get("status") for r in detail_rows})}
    summary: list[list] = [
        ["Program", program], ["Departure from / to", "all dates" if args.all else f"{start} / {end}"], ["Statuses", ", ".join(statuses)],
        ["Trips found with those statuses", len(found)], ["Trips taken for the detail call", len(chosen)],
        ["Trips without a departure date", no_departure], [],
        ["CALL 2, trip search"] + [""], *([[k, v] for k, v in s2.items()]), [],
        ["CALL 4, trip detail (all)"] + [""], *([[k, v] for k, v in s4.items()]),
    ]
    for status, stats in by_status.items():
        summary += [[], [f"CALL 4, trip detail ({status})", ""], *([[k, v] for k, v in stats.items()])]
    api_seconds = sum(r["seconds"] for r in timer.rows)
    summary += [[], ["Time inside the API calls, seconds", round(api_seconds, 1)], ["Pauses between calls, seconds", round(timer.slept, 1)],
                ["Wall-clock total, seconds", round(elapsed, 1)]]
    out.mkdir(parents=True, exist_ok=True)
    path = out / ("swp_timing_all_trips.xlsx" if args.all else f"swp_timing_{start}_{end}.xlsx")
    by_found = collections.Counter(str(r.get("tripStatus", "")).replace(" ", "") for r in found.values())
    write_workbook(path, summary, search_rows, detail_rows,
                   {"total": len(found), "detail": ", ".join(f"{k}: {v}" for k, v in sorted(by_found.items()))}, args.delay)

    print("\n=== Timing ===")
    print("call 2 (search):", s2)
    print("call 4 (detail):", s4)
    for status, stats in by_status.items():
        print(f"  detail, {status}:", stats)
    print(f"inside the API: {api_seconds:.0f} s; pauses: {timer.slept:.0f} s; wall clock: {elapsed:.0f} s")
    print("written:", path)


if __name__ == "__main__":
    main()
