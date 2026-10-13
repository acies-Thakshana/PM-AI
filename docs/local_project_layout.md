# Local project layout (host on your machine)

This is the **complete folder format** for running the AI-for-BI project locally.

- **Existing NL-to-SQL** stays under `src/nlq/` (do not rewrite).
- **`python/`** is the packaging-facing alias layout for notebooks and future adapters.
- **`frontend/`** is the local dashboard + chatbot host surface (implementation fills these stubs later).
- **`semantic/`** is the governed semantic layer (enterprise + BU + schema).

---

## Complete folder tree

```text
dataiku-langgraph-nlq/                          # <PROJECT_ROOT> — clone / open this folder
│
├── README.md                                   # Project overview
├── docs/
│   ├── local_hosting.md                        # How to run locally
│   ├── local_project_layout.md                 # This file
│   ├── architecture.md
│   ├── semantic_layer.md
│   ├── discovery_questions.md
│   └── dataiku_flow.md
│
├── .env.example                                # Copy to .env for local secrets/config
├── .gitignore
├── pyproject.toml                              # Python package + deps
├── requirements.txt
├── run.py                                      # Local CLI chatbot entry (existing NL-to-SQL)
│
├── config/
│   ├── settings.yaml                           # Local runtime settings
│   └── settings.dss.yaml.example               # Future Dataiku overrides (not required locally)
│
├── python/                                     # Local packaging layout (points at existing NL-to-SQL)
│   ├── README.md
│   ├── notebooks/                              # Prefer project notebooks/ ; shim docs here
│   │   └── README.md
│   └── nl_to_sql/
│       ├── README.md                           # Integration boundary — do not rewrite engine
│       └── bridge.py                           # Thin import bridge → src/nlq
│
├── src/
│   └── nlq/                                    # *** EXISTING NL-to-SQL / LangGraph engine ***
│       ├── main.py
│       ├── notebook_runner.py
│       ├── graph/                              # LangGraph orchestration
│       ├── sql/                                # SQL generation helpers
│       ├── validation/                         # SQLGlot validation
│       ├── security/                           # Allowlists / guardrails
│       ├── execution/                          # Local / Dataiku executors
│       ├── semantic/                           # Semantic load / merge / resolve / RLS
│       ├── metadata/
│       ├── services/
│       ├── evaluation/
│       ├── visualization/
│       ├── logging/
│       └── dataiku_adapters/                   # LLM Mesh, SQLExecutor2 adapters
│
├── frontend/                                   # Local dashboard + “Ask Business Data” chatbot
│   ├── README.md
│   ├── app/
│   │   ├── README.md                           # App entry (Streamlit or chosen FE — later)
│   │   ├── dashboard/                          # KPI cards, trends, filters
│   │   │   └── .gitkeep
│   │   ├── chatbot/                            # Ask Business Data panel/page
│   │   │   └── .gitkeep
│   │   ├── components/                         # Shared UI pieces
│   │   │   └── .gitkeep
│   │   └── services/                           # Calls into semantic + NL-to-SQL APIs
│   │       └── .gitkeep
│   ├── assets/
│   │   └── .gitkeep
│   └── requirements-frontend.txt               # FE-only deps when implemented
│
├── semantic/                                   # Machine-readable semantic layer
│   ├── schemas/
│   │   └── semantic_model.schema.json
│   ├── enterprise/
│   │   └── enterprise_semantic_model.yaml      # Placeholder enterprise core
│   ├── business_units/
│   │   └── example_bu.yaml                     # BU extension template
│   └── domains/                                # Optional certified domain cores
│       └── kpi_productivity.yaml               # Domain specialization (if present)
│
├── metadata/                                   # Legacy/local catalog + glossary (still used by NL-to-SQL)
│   ├── dataset_catalog.json
│   ├── business_glossary.json
│   └── curated_schema_ddl.sql
│
├── prompts/                                    # Versioned LLM prompts
│   ├── intent_classification.txt
│   ├── sql_generation.txt
│   ├── sql_repair.txt
│   └── answer_generation.txt
│
├── notebooks/                                  # Local Jupyter demos
│   └── dynamic_nlq_demo.ipynb
│
├── data/                                       # Local curated / fixture data (gitignored as needed)
│   └── README.md
├── local_data/                                 # Optional local host mounts (parquet, caches)
│   └── README.md
│
├── logs/                                       # Local audit + execution traces
│   ├── nlq_query_audit.jsonl
│   └── nlq_execution.log
│
├── samples/
│   └── sample_queries.json
├── schemas/                                    # Response/state JSON schemas
├── reports/                                    # Eval reports
├── tests/
│   ├── unit/
│   ├── contract/                               # Semantic schema contracts
│   ├── integration/
│   └── evaluation/
│
├── scripts/                                    # Local helper scripts
├── dataiku/                                    # Future DSS assets (recipes, webapps, scenarios)
│   ├── recipes/
│   ├── webapps/
│   ├── notebooks/
│   └── scenarios/
│
└── build/                                      # Generated local/DSS prep artifacts (optional)
```

---

## What runs where (local host)

| Path | Role on local machine |
|---|---|
| `run.py` | Terminal chatbot against existing NL-to-SQL |
| `src/nlq/` | Engine (intent → SQL → validate → execute → answer) |
| `python/nl_to_sql/bridge.py` | Stable import path for FE / notebooks |
| `frontend/` | Future local dashboard + Ask Business Data UI |
| `semantic/` | Metrics, dims, joins, security, versions |
| `config/settings.yaml` | Local config (datasets, limits, LLM mode) |
| `logs/` | Audit and traces for support |
| `data/` + `local_data/` | Curated fixtures only — never raw ungoverned dumps for NLQ |
| `dataiku/` | Not required to host locally; used later for DSS promotion |

---

## Folder ownership

| Folder | Owner role (placeholder) | Change frequency |
|---|---|---|
| `src/nlq/` | NLQ engineering | Controlled; no rewrite for BU onboarding |
| `semantic/` | Semantic stewards | Per metric/BU certification |
| `frontend/` | FE / product | UI only; must call shared services |
| `python/` | Platform packaging | Thin bridges only |
| `docs/` | Architects | Design + hosting guides |
| `config/` | Platform | Environment pins |
