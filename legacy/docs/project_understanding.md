# Project understanding

## Objective

AI4BI answers business questions over arbitrary tabular datasets while keeping
the application portable. The core must run without Dataiku, but Dataiku can
supply datasets and an LLM through a thin adapter. A future platform adapter
can implement the same data, model, and persistence contracts.

New datasets must not require changes to Python recipes or semantic YAML.
Instead, onboarding observes the connected schema, safely profiles values,
uses the configured LLM to propose semantics, validates those proposals, and
persists a versioned semantic registry, catalog, and knowledge graph.

## What is learned automatically

- Dataset/entity purpose, grain, and column descriptions.
- Keys, measures, dimensions, timestamps, and restricted fields.
- KPI names, business definitions, aggregations, formulas, units, and synonyms.
- Join candidates and their observed cardinality.
- Glossary terms and calculation/business rules.
- Knowledge-graph entities, relationships, SQL patterns, and prior Q&A episodes.

The knowledge graph is first generated from the dynamically learned semantic
layer, then enriched with each executed question, with successful queries
added as reusable SQL patterns.

## What “automatic” means

Every proposal is persisted, but only a proposal that passes deterministic
checks becomes active. This is necessary because an LLM cannot establish data
truth by language alone.

- Active artifacts are immediately available to the ask pipeline.
- Draft artifacts remain visible in `semantic_registry` and
  `onboarding_audit`, with the reason they failed activation.
- An unchanged input fingerprint does not invoke the LLM again.
- A changed schema creates a new semantic version and retains history.

## Portability boundary

The `ai4bi` package has no Dataiku import. It owns models, profiling,
onboarding, validation, registry logic, SQL, answers, visualization, and tests.

The `ai4bi_dataiku` package owns Flow dataset I/O, project variables, LLM Mesh,
and recipe orchestration. Recipe files do not contain business logic.

The local CLI uses JSON/JSONL storage. Dataiku uses tabular datasets containing
the same records. Future adapters can use object storage or a database without
changing the semantic or question pipelines.
