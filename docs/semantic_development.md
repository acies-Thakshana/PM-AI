# Semantic layer development guide

## Why answers used to stick to Climate Solutions Americas

Three causes (now fixed):

1. Default user was `local.analyst` (authorized only for CSA).
2. Dashboard sidebar defaulted BU filter to the first BU (CSA) and Ask inherited those filters.
3. Semantic executor applied UI BU filters even when the question said nothing about a BU.

## Current behavior

- Default user: `local.cross_bu` (all BUs).
- Ask ignores dashboard filters unless “Apply dashboard filters to Ask” is checked.
- Question text can still name a BU (CSA, Climate Solutions Europe, …).
- `local.analyst` remains available to demo BU RLS.

## How we develop the semantic layer

### Layer 1 — Contracts (YAML)

- Domain pack: `semantic/domains/kpi_productivity.yaml`
- Template for new packs: `semantic/domains/_template_domain.yaml`
- Enterprise shell: `semantic/enterprise/enterprise_semantic_model.yaml`
- BU extensions: `semantic/business_units/*.yaml` (skip `example_*.yaml`)

Each metric declares `data_product_ids`, `measure.sql_expression`, synonyms, and security.

### Layer 2 — Physical binding (registry)

`config/data_products.yaml` maps `data_product` ids to local parquet/csv paths and BU column names.  
Any dashboard can register more products without changing executor code.

### Layer 3 — Runtime (Python)

| Module | Responsibility |
|--------|----------------|
| `aibi/semantic_merge.py` | Merge core + domain packs + BU extensions |
| `aibi/semantic_service.py` | Load, authorize, synonym-match metrics |
| `aibi/data_product_registry.py` | Load any registered dataset |
| `aibi/semantic_executor.py` | Deterministic intent → filters → aggregate |
| `aibi/query_plan.py` | Plan before execute / NL2SQL |
| `aibi/ask_service.py` | Orchestration; wires all datasets into NL2SQL |

### Layer 4 — NL-to-SQL fallback

Existing engine at `AI_BI_NL2SQL_ROOT` receives:

- `NLQ_SEMANTIC_CORE`
- `NLQ_DATA_PATHS` = all registered product files
- `NLQ_AUTHORIZED_BUS` / cross-BU flags from the local user

## Add a new BU dataset for another dashboard

1. Drop curated file in `local_data/fixtures/`.
2. Add entry to `config/data_products.yaml`.
3. Copy `_template_domain.yaml` → `semantic/domains/<name>.yaml` and fill metrics.
4. Restart Streamlit.

See also: `semantic/README.md`.
