# Dashboard components map

Local app root: `C:\Users\BharadNa\enterprise-ai-for-bi`

## UI layout (what you see)

| Area | What it does | Code |
|------|----------------|------|
| **Theme / CSS** | Light gradient background, white cards, teal accents | `frontend/app/main.py` → `inject_css()` |
| **Hero banner** | Title, semantic version pills, row count | `main.py` hero HTML |
| **Sidebar → Session** | Pick local user (BU analyst / cross-BU / steward) | `main.py` + `aibi/auth.py` + `config/local_users.yaml` |
| **Sidebar → Global filters** | BU, pillar, year, quarter, month, region, category | Filter options from live KPI cube + `config/dashboard.yaml` |
| **Sidebar → Display** | View mode, chart type, currency, unit, target overlay, freshness | `main.py` |
| **Tab: Executive overview** | Live KPI cards + quarterly trend chart + freshness chips | `backend.get_dashboard()` → `aibi/kpi_analytics.py` |
| **Tab: Explore & compare** | Pillar bars, actual vs target, BU ranking, region bars | same live payload |
| **Tab: Ask Business Data** | Suggested questions, ask box, answer/table/SQL/plan | `backend.ask()` → `aibi/ask_service.py` |
| **Tab: Metric definitions** | Certified metric text + live value + dimensions | semantic YAML + cards |

## Backend stack (behind the UI)

```
Streamlit main.py
    → frontend/app/services/backend.py
        → aibi/kpi_analytics.py + aibi/kpi_data.py     (dashboard numbers)
        → aibi/ask_service.py
            → aibi/auth.py                             (local user / BU RLS)
            → aibi/query_plan.py                       (semantic plan)
            → aibi/semantic_executor.py                (deterministic KPI answers)
            → optional NL-to-SQL via AI_BI_NL2SQL_ROOT
        → aibi/semantic_service.py                     (load YAML metrics/cards)
        → semantic/domains/kpi_productivity.yaml       (certified semantic core)
```

## Run scripts

| Script | Purpose |
|--------|---------|
| `run_dashboard.ps1` | Sets env vars + starts Streamlit on :8501 |
| `run_dashboard.bat` | Windows batch wrapper |
| `run_cli.py` | Ask from command line without UI |

## Data

| File | Purpose |
|------|---------|
| `local_data/fixtures/KPI_data.parquet` | Curated KPI cube (not in zip if large; copy separately) |
| `config/dashboard.yaml` | Which KPI cards appear |
| `config/local_users.yaml` | Demo users and BU scopes |
