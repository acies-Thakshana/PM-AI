# Execution flows

## Dataiku onboarding

1. Connect any number of fact and dimension datasets to
   `ai4bi_onboarding_recipe.py`.
2. The adapter reads declared Flow inputs; dataset names become SQL table names.
3. The core infers a baseline package and marks likely PII before profiling.
4. If the fingerprint already exists, the latest registry overlay is reused.
5. Otherwise, the Dataiku LLM proposes descriptions, KPIs, joins, glossary,
   and rules in structured JSON.
6. Deterministic validators assign each proposal `active` or `draft`.
7. The recipe writes:
   - `dataset_catalog`
   - `semantic_registry`
   - optional `knowledge_graph`
   - optional `onboarding_audit`
8. On later builds the recipe reads its existing registry and graph outputs,
   so a cyclic Flow connection is not required.

No recipe source changes when another dataset is connected.

## Dataiku ask

1. Connect facts, a question dataset containing `input_question`, and optional
   prior `semantic_registry` and `knowledge_graph`.
2. The recipe auto-onboards the current fingerprint when enabled.
3. Active registry records overlay the inferred or curated package.
4. Restricted columns are removed.
5. Each question passes input guardrails.
6. The planner chooses certified/active metrics and registered joins.
7. Generated SQL is grounded, policy-validated, and executed read-only.
8. A result-grounded answer, table, chart, and follow-ups are generated.
9. The graph records the episode; results, graph, registry, and optional catalog
   are written when those outputs are declared.

## Local onboarding and ask

```powershell
python -m local onboard --domain my_domain
python -m local ask "What is total revenue?" --domain my_domain
```

Local source files are read from `storage/samples/my_domain`. Onboarding writes
the registry to `storage/semantic_registry/my_domain.json`, metadata to
`storage/metadata/my_domain/dataset_catalog.json`, and graph data to
`storage/knowledge_graph/my_domain.json`. Ask automatically loads this registry.

Use `--force` on onboarding to create a fresh version for the same fingerprint.

## Batch and evaluation

`python -m local batch` or the Dataiku ask recipe runs the same question
pipeline for every row. Expected SQL is optional. Evaluation compares query
results rather than SQL text, so equivalent SQL is accepted. Rows without
expected SQL are `not_scored`.

## Configuration

Base values are in `config/settings.yaml`. Local `.env` and Dataiku project
variables override them.

Important onboarding variables:

- `AIBI_AUTO_ONBOARD`
- `AIBI_INCLUDE_DRAFTS`
- `AIBI_JOIN_MIN_OVERLAP`
- `AIBI_ACTIVATION_CONFIDENCE`
- `AIBI_ONBOARDING_SAMPLE_VALUES`

Production should leave `AIBI_INCLUDE_DRAFTS=false`.

## Failure behavior

- Missing configuration/data raises a clear configuration error.
- Invalid model JSON falls back to deterministic schema semantics.
- Invalid KPI/join proposals are stored as drafts, not discarded.
- Unsafe SQL is rejected before execution.
- LLM answer figures not found in result rows produce warnings.
- One SQL repair is attempted before the deterministic local SQL fallback.
