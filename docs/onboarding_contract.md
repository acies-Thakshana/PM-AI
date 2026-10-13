# AI4BI onboarding contract

A new domain is accepted only when this package is complete. The factory
does not bind to Salesforce objects. Custom objects are entity-registration
rows.

## Package layout

```
onboarding/domains/<domain>/
  contract.yaml      # extracts, history, master + transactional entities
  dictionary.yaml    # business definitions, KPIs, hierarchies, synonyms
  entities.yaml      # configuration-only entity registration
  joins.yaml         # data-team join + grain registry (never inferred)
  glossary.yaml      # populate-only terms
  pii_tags.yaml      # data-team sensitive field tags
  harvest.yaml       # metrics / questions / drills taken from existing BI
  metrics.yaml       # versioned KPI catalog (compiler output, steward-activated)
```

## Commands

```powershell
cd C:\Users\BharadNa\enterprise-ai-for-bi
py -3 run_onboard.py validate --domain service_ops
py -3 run_onboard.py compile --domain service_ops
py -3 run_onboard.py harvest --domain service_ops
py -3 run_onboard.py ask --domain service_ops --question "What is EMEA FRT?"
py -3 -m pytest tests/factory -q
```

## Rules

1. Joins come from `joins.yaml`. The LLM cannot invent one.
2. Dictionary KPI rows are hints. The LLM proposes the live calculation and
   writes it into the knowledge graph after each question.
3. Global / EMEA / APAC variants are scopes in metadata, not prompt forks.
4. Restricted columns never enter SQL or LLM context (platform tags).
5. Existing dashboards are harvested, not cloned.
6. Answers always come from the LLM path (`answer_path=llm_kg`).
