# Cold Chain / Post-Harvest Assessment Reporting PoC

Proof-of-concept for automating C&I Program Management's Cold Chain / Post-Harvest
Assessment reporting: a live dashboard fed from structured + unstructured backend
data, and a "Generate PPT" action that produces a formatted, on-brand deck with
expert-level analytical narrative.

This responds directly to the failure mode of the earlier Copilot-Agent attempt:
generic summaries with no deductive reasoning, and broken template/rendering
fidelity from letting the LLM manipulate Excel/PPTX directly.

## Architecture

```
backend/app/data/
  cold_chain_metrics.xlsx        structured data: shipments, sensor readings,
                                  facilities, quality outcomes, KPI targets
  post_harvest_knowledge.md      unstructured domain knowledge: post-harvest
                                  physiology, failure modes, corrective actions

backend/app/services/            ALL deterministic logic (no LLM):
  data_loader.py                 loads/holds the Excel data in memory
  analytics.py                   compliance %, excursion detection, rankings
  knowledge_retriever.py         keyword retrieval over the knowledge doc
  live_feed.py                   simulates a live IoT feed for in-transit shipments
  report_template.py             the "gold standard" slide spec + brand styling

backend/app/agents/              THE ONLY TWO LLM AGENTS, each single-purpose:
  insight_agent.py    Agent 1    stats + domain knowledge -> expert narrative JSON
  pptx_tools.py                  deterministic python-pptx slide builders (tools)
  ppt_agent.py         Agent 2    calls pptx_tools in the fixed template order

backend/app/orchestrator.py      deterministic pipeline glue (not an agent):
                                  data -> analytics -> retrieval -> agent1 -> agent2
backend/app/routers/             FastAPI endpoints (dashboard reads, report jobs)

frontend/                        React (Vite + TS) dashboard, polls the API,
                                  "Generate PPT Report" button drives the pipeline
```

### Why exactly 2 agents

| Step | Who | Why |
|---|---|---|
| Parse Excel, compute stats | deterministic Python | never let an LLM touch raw numbers — this is where the original attempt hallucinated |
| Retrieve relevant knowledge passages | deterministic keyword retrieval | lookup problem, not a reasoning problem |
| Turn stats + knowledge into expert conclusions | **Agent 1 (Insight Analyst)** | the one step that genuinely needs judgment/deduction |
| Decide slide content + assemble the deck | **Agent 2 (Report Composer)** | calls deterministic `pptx_tools` functions as tools — never writes PPTX XML itself |
| Wire it together | deterministic orchestrator | glue code, not a decision |

## Setup

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/generate_sample_data.py
```

Copy `.env.example` to `.env` and add your Groq API key (get one at
https://console.groq.com/keys):

```bash
copy .env.example .env
```

```
GROQ_API_KEY=your_key_here
GROQ_MODEL=llama-3.3-70b-versatile
```

Run the API:

```bash
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 — the dashboard polls the FastAPI backend every ~15-20s
and renders everything (KPIs, charts, tables) from `cold_chain_metrics.xlsx` and the
live-feed simulator. Nothing is hardcoded in the frontend.

### 3. Generate a report

Click **Generate PPT Report**. You'll see the pipeline progress through both agents
(Insight Analyst → Report Composer), then a download link for the finished `.pptx`
in `backend/generated_reports/`.

## Regenerating sample data

`python scripts/generate_sample_data.py` rebuilds `cold_chain_metrics.xlsx` with a
fresh (seeded) dataset. Restart the backend afterwards so it reloads the file —
the API holds data in memory rather than re-reading the workbook on every request.

## Notes

- The "live" feed is a deterministic simulator (`app/services/live_feed.py`) that
  appends a new sensor reading every ~12s for shipments marked "In Transit" —
  it never touches the Excel file, only the in-memory view, so the workbook stays
  an immutable source-of-truth snapshot.
- Numeric slides (KPI cards, tables) are built from exact pre-computed values —
  Agent 2 is instructed to copy them verbatim, not regenerate them — so a fluent
  LLM sentence can never corrupt a data cell in the deck.
