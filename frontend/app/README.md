# frontend/app

Place the local app entry here (for example `main.py` for Streamlit).

Suggested modules:

| Path | Responsibility |
|---|---|
| `dashboard/` | Enterprise/BU overview, KPI cards, charts, filters |
| `chatbot/` | Ask Business Data input, clarifications, answer/table/chart |
| `components/` | Shared controls (freshness badge, metric tooltip, export) |
| `services/` | HTTP/local calls to semantic planner + `python.nl_to_sql.bridge` |

Do not embed KPI formulas in the UI. Read definitions from the semantic layer.
