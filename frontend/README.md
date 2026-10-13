# frontend/ — local dashboard + Ask Business Data

Local hosting surface for the AI-for-BI experience.

## Goals

- Enterprise and BU KPI dashboard (cards, trends, variance, targets, rankings, drill-downs)
- Filters: BU, fiscal period, date, currency, unit
- Freshness, metric definition tooltips, lineage
- Security-aware views + export/feedback where authorized
- **Ask Business Data** chatbot that works **even when the KPI is not on the dashboard**

## Folder format

```text
frontend/
├── README.md
├── requirements-frontend.txt
├── assets/
└── app/
    ├── README.md
    ├── dashboard/          # KPI cards, charts, filter panel
    ├── chatbot/            # Ask Business Data panel + standalone page
    ├── components/         # Shared widgets
    └── services/           # Clients for semantic + python.nl_to_sql.bridge
```

## Local host (after implementation)

```powershell
cd C:\Users\BharadNa\dataiku-langgraph-nlq
$env:PYTHONPATH = "src;."
py -3 -m pip install -r frontend/requirements-frontend.txt
py -3 -m streamlit run frontend/app/main.py
```

Default Streamlit URL: `http://localhost:8501`

## Rules

1. Frontend is not a security boundary — always send auth/BU/roles to backend services.
2. Dashboard card config ≠ semantic metric allowlist.
3. Chatbot must call the same semantic + NL-to-SQL path as any other client.
4. No answers from the LLM without validated execution results.
5. Do not import raw tables; use curated products only.

## Status

UI modules are stubbed for local folder hosting. Wire `app/main.py` in the frontend implementation phase using the contracts in `docs/architecture.md`.
