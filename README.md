# Enterprise AI for BI (Local)

Standalone local project. No GitHub remote required.

## Folder

`C:\Users\BharadNa\enterprise-ai-for-bi`

## What you get

- **LLM-first engine** (`aibi/llmkg/`) — intent, SQL, metrics, calculations, answers
- **Living knowledge graph** (`knowledge_graph/<domain>.json`) updated after every question
- Onboarding contract (`onboarding/domains/`) — schema, joins, dictionary, glossary, PII
- Hybrid experience (dashboard / copilot / drill / visuals)
- Dataiku recipe: `dataiku/recipes/aibi_llmkg_ask_recipe.py`

## Setup (once)

```powershell
cd C:\Users\BharadNa\enterprise-ai-for-bi
py -3 -m pip install -r requirements.txt
# also install the NL-to-SQL engine deps if not already:
py -3 -m pip install -e "C:\Users\BharadNa\dataiku-langgraph-nlq[dev]"
```

## Run dashboard + chatbot

```powershell
cd C:\Users\BharadNa\enterprise-ai-for-bi
.\run_dashboard.ps1
```

Open http://localhost:8501

## Run CLI ask

```powershell
cd C:\Users\BharadNa\enterprise-ai-for-bi
$env:AI_BI_NL2SQL_ROOT="C:\Users\BharadNa\dataiku-langgraph-nlq"
$env:PYTHONPATH="C:\Users\BharadNa\enterprise-ai-for-bi;C:\Users\BharadNa\dataiku-langgraph-nlq\src"
py -3 run_cli.py "What is the total productivity achieved so far?"
py -3 run_cli.py "How are we performing?"
```

## Onboarding factory (source-agnostic)

A new domain is metadata, not a new agent. Package lives under
`onboarding/domains/<domain>/`. First worked example: `service_ops`
(Salesforce Case + custom object `Case_Extension__c`, but the factory
never names those objects in code).

```powershell
cd C:\Users\BharadNa\enterprise-ai-for-bi
py -3 run_onboard.py validate --domain service_ops
py -3 run_onboard.py compile --domain service_ops
py -3 run_onboard.py ask --domain service_ops --question "What is EMEA FRT?"
py -3 -m pytest tests/factory tests/llmkg -q
```

See `docs/onboarding_contract.md`.

## Experience layer (hybrid, reusable)

Dashboard + copilot + drill + visuals. Six frozen templates. Excel Escape
is the primary regression library.

```powershell
py -3 run_onboard.py experience --domain service_ops
py -3 run_onboard.py eval --domain service_ops
```

See `docs/experience.md` and `config/platform.yaml`.

## Dataiku KPI validation recipe (LLM + knowledge graph)

Inputs: `KPI_data` + `kpi_cube_validation`.
Output: `kpi_cube_validation_llm_results`.
Optional output: `knowledge_graph`.

Paste `dataiku/recipes/aibi_llmkg_ask_recipe.py`.
See `docs/llm_knowledge_graph.md`.

## Docs

- `docs/architecture.md`
- `docs/semantic_layer.md`
- `docs/onboarding_contract.md`
- `docs/local_hosting.md`
- `docs/NL_TO_SQL_INTEGRATION.md`
