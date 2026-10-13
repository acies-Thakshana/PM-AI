# Local hosting guide

Host and exercise this project entirely on your machine. Dataiku API Designer, Kubernetes, and cloud hosting are **not** required.

## 1. Prerequisites

- Windows 10/11 (PowerShell) or equivalent
- Python 3.9+ (`py -3` on Windows)
- Git
- Optional: Jupyter for `notebooks/`
- Optional: local curated parquet/SQL fixtures under `data/` or `local_data/`

## 2. One-time setup

This project is standalone. Point at your existing NL-to-SQL engine:

```powershell
$env:AI_BI_NL2SQL_ROOT = "C:\Users\BharadNa\dataiku-langgraph-nlq"
```

See also `docs/NL_TO_SQL_INTEGRATION.md`.

## 2b. Project setup

```powershell
cd C:\Users\BharadNa\enterprise-ai-for-bi

py -3 -m pip install -e ".[dev]"
copy .env.example .env
$env:PYTHONPATH = "src"
```

Edit `.env` and `config/settings.yaml` for:

- LLM mode (`auto` / local fallback)
- Allowed curated datasets
- Execution backend (`local` for laptop hosting)

## 3. Run the existing NL-to-SQL chatbot (CLI)

```powershell
$env:PYTHONPATH = "src"
py -3 run.py
```

One-shot:

```powershell
py -3 run.py "How many cases were opened last month?"
```

Developer trace:

```powershell
py -3 run.py --trace
py -3 run.py --verbose
```

## 4. Notebooks

```powershell
$env:PYTHONPATH = "src"
jupyter notebook notebooks\dynamic_nlq_demo.ipynb
```

Prefer:

```python
from nlq.notebook_runner import ask_nlq
print(ask_nlq("Your business question"))
```

Packaging-facing import (same engine):

```python
from python.nl_to_sql.bridge import ask
print(ask("Your business question"))
```

## 5. Semantic layer (local files)

| File | Purpose |
|---|---|
| `semantic/enterprise/enterprise_semantic_model.yaml` | Enterprise template (placeholders) |
| `semantic/business_units/example_bu.yaml` | BU extension template |
| `semantic/schemas/semantic_model.schema.json` | Validation contract |
| `semantic/domains/*.yaml` | Optional certified domain cores |

Do not point NLQ at raw extracts. Use curated products / approved fixtures only.

## 6. Frontend (local dashboard + chatbot)

The `frontend/` folder is the **host surface** for:

- Enterprise / BU KPI dashboard
- “Ask Business Data” chatbot (dashboard-independent)

Streamlit (or chosen framework) app code is intentionally stubbed until the FE implementation phase. See `frontend/README.md`.

When implemented, expected local command pattern:

```powershell
# Example only — enable after FE implementation
py -3 -m streamlit run frontend/app/main.py
```

## 7. Tests (local)

```powershell
$env:PYTHONPATH = "src"
py -3 -m pytest tests/unit tests/contract -q
```

## 8. Local ports / processes (typical)

| Process | Default | Notes |
|---|---|---|
| CLI chatbot | stdin/stdout | `run.py` |
| Jupyter | `8888` | notebooks |
| Streamlit dashboard (future) | `8501` | `frontend/app` |
| Optional local API (future) | `8000` | thin wrapper over `ask` |

## 9. What not to host as queryable data

- Raw / quality / standardization zone dumps
- Audit tables as NLQ sources
- Uncertified spreadsheets

## 10. Folder map

See [local_project_layout.md](local_project_layout.md) for the complete tree.
