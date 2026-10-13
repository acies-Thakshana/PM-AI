# LLM-first AI4BI with a living knowledge graph

Answers, intent, SQL, metrics, and calculations are produced by the LLM.
Onboarding YAML is grounding only: schema, registered joins, dictionary hints,
glossary, and PII tags. It is not a rigid compiler.

## Stable (do not fork per project)

- Planner / orchestration (`aibi/llmkg/engine.py`)
- Knowledge-graph store and retrieval
- NL-to-SQL prompt + join/PII guards
- Explainability payload
- Evaluation recipe
- Visualization templates

## Configurable (change per project)

- Schema / entity registration
- Join registry (data team; never inferred)
- Data dictionary and KPI *hints*
- Glossary
- PII tags
- Domain prompt extras
- Excel Escape question library

## Pipeline per question

1. Load onboarding + retrieve a graph slice (RAG).
2. **LLM** — intent, entities, metrics, calculations, new terms.
3. **LLM** — SQL using only registered datasets/joins.
4. Platform — execute SQL, enforce SELECT-only, PII deny, registered joins.
5. **LLM** — business answer from the result rows only.
6. Update the knowledge graph (question, metrics, SQL pattern, new terms).
7. Persist `knowledge_graph/<domain>.json`.

New questions do not require code changes. They make the graph richer.

## Commands

```powershell
cd C:\Users\BharadNa\enterprise-ai-for-bi
$env:AIBI_LLM_MODE="local"   # structured fallback when Mesh is absent
py -3 run_onboard.py ask --domain service_ops --question "What is EMEA FRT?"
py -3 -m pytest tests/llmkg -q
```

In Dataiku, paste `dataiku/recipes/aibi_llmkg_ask_recipe.py`.
The graph is updated after every validation question in that run.
