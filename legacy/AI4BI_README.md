# AI4BI

AI4BI is a reusable natural-language business intelligence engine. It runs
locally, in Dataiku, and behind future platform adapters without putting
business logic in a recipe.

The Dataiku LLM can dynamically build the semantic layer for newly connected
datasets. It discovers entities, descriptions, measures, KPI formulas,
synonyms, rules, and join candidates. Deterministic checks activate safe
artifacts; ambiguous artifacts remain versioned drafts with validation reasons.
No Python or YAML change is required when a new dataset is connected.

## Install locally

```powershell
cd C:\Users\BharadNa\Downloads\AWS_script
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Optional Excel and Parquet support:

```powershell
python -m pip install -r requirements-optional.txt
```

## Run locally

```powershell
# Discover configured domains
python -m local domains

# Dynamically build semantics, metadata, and the knowledge graph
python -m local onboard --domain generic_cube

# Ask one question
python -m local ask "What is total productivity?" --domain generic_cube

# Batch and evaluate
python -m local batch examples/questions_generic_cube.csv --domain generic_cube
python -m local evaluate examples/questions_generic_cube_results.csv --domain generic_cube

# Validate configured assets and certified SQL
python -m local validate

# Test
python -m pytest
```

Local mode needs no model or Dataiku installation. The deterministic planner
uses validated semantic definitions and safe fallbacks.

## Dynamic Dataiku onboarding

1. Put `lib/python` on the Dataiku project library path using
   `external-libraries.json`.
2. Configure project variables from
   `dataiku/project_variables.example.json`. Set `AIBI_LLM_CONNECTION` to the
   Dataiku LLM Mesh connection.
3. Create a Python recipe from
   `dataiku/recipes/ai4bi_onboarding_recipe.py`.
4. Connect every fact/dimension dataset as an input.
5. Create outputs named `dataset_catalog`, `semantic_registry`, and optionally
   `knowledge_graph` and `onboarding_audit`.
6. The onboarding recipe reads the previous contents of its registry/graph
   outputs on later builds; no cyclic Flow connection is required.
7. Connect facts, questions, and the onboarding recipe's `semantic_registry`
   and `knowledge_graph` outputs to `ai4bi_ask_recipe.py`.

Adding another fact dataset only changes the Flow connection. On rebuild,
AI4BI fingerprints the current data/schema, learns the delta, versions the
registry, refreshes the catalog, and updates the graph. The ask recipe also
auto-onboards at runtime when `AIBI_AUTO_ONBOARD=true`.

## Persistence

- `semantic_registry`: versioned entities, metrics, joins, glossary, and rules.
- `dataset_catalog`: column profiles and descriptions for the current version.
- `knowledge_graph`: first generated from the dynamically learned semantic
  layer, then enriched with each executed question, with successful queries
  added as reusable SQL patterns.
- `onboarding_audit`: activation decisions and draft reasons.
- Local equivalents live under `storage/semantic_registry`,
  `storage/metadata`, `storage/knowledge_graph`, and `storage/history`.

Bundled YAML under `storage/semantic/domains` is an optional curated baseline,
not a requirement for new domains.

## Safety

- Restricted values are removed before LLM prompting and SQL execution.
- SQL is read-only and restricted to observed tables and columns.
- A join activates only when columns exist, types/data overlap, one side is
  unique, and confidence thresholds pass.
- A KPI activates only when its aggregate expression passes policy checks,
  executes, and returns a usable result.
- Failed or ambiguous proposals are retained as drafts and are not used by
  natural-language SQL unless `AIBI_INCLUDE_DRAFTS=true`.

## Project layout

- `lib/python/ai4bi/` — platform-independent core.
- `lib/python/ai4bi_dataiku/` — Dataiku-only adapter; the only package that
  imports `dataiku`.
- `dataiku/recipes/` — thin orchestration entry points.
- `local/` — local CLI entry points.
- `config/` — application and visualization configuration.
- `storage/` — semantic baselines, samples, registries, metadata, graph, history.
- `tests/unit/` and `tests/integration/` — offline and end-to-end tests.
- `docs/` — architecture, flows, understanding, and validation checklist.

See `docs/architecture.md` and `docs/flows.md` for the complete design.
