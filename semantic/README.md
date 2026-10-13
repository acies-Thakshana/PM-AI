# Semantic layer — how it is built (reusable)

This project’s semantic layer is **generic**: metrics and dimensions are declared in YAML; physical files are registered separately. KPI_data is one domain pack, not the whole design.

## Architecture

```
semantic/
  enterprise/enterprise_semantic_model.yaml   # shared enterprise template
  domains/kpi_productivity.yaml               # domain pack (productivity KPIs)
  domains/<your_domain>.yaml                  # add more domain packs
  business_units/<bu>.yaml                    # optional BU-owned products
  schemas/semantic_model.schema.json

config/
  data_products.yaml                          # binds data_product ids → local files
  local_users.yaml                            # BU RLS / cross-BU users

aibi/
  semantic_merge.py           # merge core + domains + BU extensions
  semantic_service.py         # load model, authorize metrics, synonym match
  data_product_registry.py    # load any registered dataset by product id
  semantic_executor.py        # deterministic Q→intent→metric→aggregate
  query_plan.py               # semantic plan before execution / NL2SQL
  ask_service.py              # orchestration + NL-to-SQL fallback
```

## How a question is answered (semantic first, LLM second)

1. Authenticate user (`local.cross_bu` = all BUs; `local.analyst` = CSA only).
2. Build a semantic query plan (metrics, security, products).
3. **Stage 1 — Semantic executor (deterministic / primary):** resolve intent + filters; load registered data product; aggregate certified measures. Response `answer_path=semantic` (or `clarify` / `refuse`).
4. **Stage 2 — LLM NL-to-SQL (secondary only):** runs only when stage 1 sets `delegate_to_llm` (no certified intent). Still restricted to allowlisted curated products. Response `answer_path=llm_nl2sql`.
5. Disable stage 2 with `AIBI_ENABLE_LLM_FALLBACK=false` (semantic-only mode for strict BI templates).

This is **not** LLM-only. Certified KPI / golden questions should hit stage 1.

## BU scope rules (important)

| User | Ask behavior |
|------|----------------|
| `local.cross_bu` / `local.steward` | All BUs unless the question names one (e.g. “CSA”, “Climate Solutions Europe”) |
| `local.analyst` | Forced to Climate Solutions Americas (RLS demo) |

Dashboard sidebar filters affect **charts only**. In Ask, enable “Apply dashboard filters to Ask” only when you want the current sidebar selection applied.

## Add another dataset / dashboard domain

1. Put the curated file under `local_data/fixtures/` (parquet or csv).
2. Register it in `config/data_products.yaml`:

```yaml
  - id: dp.bu.finance.ledger
    physical_dataset: finance_ledger
    path: local_data/fixtures/finance_ledger.parquet
    bu_column: business_unit
    columns:
      actual: amount
      forecast: budget_amount
```

3. Create `semantic/domains/finance_ledger.yaml` with:
   - `data_products:` entry matching that id
   - `metrics:` with `data_product_ids: [dp.bu.finance.ledger]`
   - `dimensions:`, `synonyms:`, `security.roles`, `sample_questions`
4. Optionally add a BU extension under `semantic/business_units/`.
5. Restart the dashboard. Ask + NL2SQL will pick up the new product automatically.

## Key code files to review / download

| File | Role |
|------|------|
| `semantic/domains/kpi_productivity.yaml` | Certified productivity metrics & synonyms |
| `config/data_products.yaml` | Multi-dataset registry |
| `aibi/semantic_merge.py` | Model merge |
| `aibi/data_product_registry.py` | Dataset loader |
| `aibi/semantic_executor.py` | Rule engine |
| `aibi/semantic_service.py` | Metric authorization / synonym resolve |
| `aibi/ask_service.py` | Ask API + NL2SQL wiring |
| `docs/semantic_layer.md` | Design narrative |

## Local NL-to-SQL bridge

`AI_BI_NL2SQL_ROOT` → `C:\Users\BharadNa\dataiku-langgraph-nlq`  
Ask sets `NLQ_SEMANTIC_CORE`, `NLQ_DATA_PATHS` (all registered products), and BU auth env vars.
