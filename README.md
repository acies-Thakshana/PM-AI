# PM-AI

Program Manager AI — a cold chain program management PoC. Cold-chain PMs
currently build recurring shipment reports by hand from multiple export
sources, spending hours per cycle just triaging messy data before any real
analysis starts. This tool starts at that bottleneck: upload the raw
exports, and a data audit agent reviews them the way a data analyst would
before anything downstream trusts the numbers.

## Structure

```
backend/    FastAPI service: spreadsheet parsing + the data audit agent
frontend/   React (Vite + TS) upload UI, Carrier Global branded
```

## How it works

The frontend is a two-page flow:

1. **Upload** (`frontend/src/pages/UploadPage.tsx`, `/upload`) — four source slots, no audit UI:

   | Source | Required | Notes |
   | --- | --- | --- |
   | SensiWatch Export | Yes | Real-time shipment monitoring export |
   | ColdStream Export | No | Trip/sensor data from the ColdStream platform |
   | Threshold & Compliance Reference | No | Temperature/humidity thresholds and related docs |
   | Customer KPI Profile | No | Customer-specific KPI definitions |

2. **Review** (`frontend/src/pages/ReviewPage.tsx`, `/review`) — reached via "Upload &
   Continue" once the required file is present. Each **SensiWatch** or
   **ColdStream** file is sent to the backend's data audit agent
   (`backend/app/services/data_audit.py`), which runs a set of deterministic,
   schema-agnostic checks over the parsed spreadsheet:

   - fully-empty and mostly-empty columns
   - exact duplicate rows, and repeated entries for the same trip/sensor
   - logically inconsistent values (e.g. `Min Value > Max Value`, negative durations)
   - statistical outliers (IQR-based) in sensor/trip measurement columns
   - rows missing key identifying fields

   These checks are plain pandas — no LLM involved — so the findings and any
   remediation are deterministic and reliable. A Groq-backed narrative agent
   (`backend/app/services/audit_agent.py`) then writes a short, plain-English
   data-analyst summary of what was found (it never invents findings of its
   own; it only explains the numbers already computed).

   Findings that have a real remediation choice — e.g. "12 duplicate rows
   found" — pause for a **human-in-the-loop decision**: keep the data as-is,
   or apply the suggested fix. "Finish Review" stays blocked until every such
   finding has been resolved. State (selected files, audit results) lives in
   `App.tsx` and is shared between both pages, so navigating back to Upload
   doesn't lose anything already reviewed.

## Setup

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Runs at `http://localhost:5173`.

### Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # macOS/Linux: .venv/bin/pip
```

Copy `.env.example` to `.env` (already done in this repo) and paste a Groq
API key from [console.groq.com/keys](https://console.groq.com/keys) into
`GROQ_API_KEY`. **A key is required** — the data audit agent's narrative
summary always comes from Groq, with no fallback; if the key is missing or
the Groq call fails, `/api/audit/upload` returns a 502 explaining why.

```bash
.venv/Scripts/uvicorn app.main:app --reload --port 8000   # macOS/Linux: .venv/bin/uvicorn
```

Runs at `http://localhost:8000`. Interactive API docs at `/docs`.

Run both at once, then open `http://localhost:5173`.
