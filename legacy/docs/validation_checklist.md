# Validation checklist

## Local installation

- [ ] `python -m pip install -r requirements-dev.txt` succeeds.
- [ ] `python -m local domains` lists sample domains.
- [ ] `python -m local validate` reports only PASS.
- [ ] `python -m pytest` passes.

## Dynamic onboarding

- [ ] An unknown domain with only CSV inputs can be onboarded without YAML.
- [ ] `semantic_registry` contains entities and active measures.
- [ ] A repeated unchanged run reports `changed=false` and does not call the LLM.
- [ ] Adding a column or dataset creates a new semantic version.
- [ ] Metadata catalog rows contain the current semantic version.
- [ ] Knowledge graph contains nodes for active learned artifacts.
- [ ] Validation audit explains every draft.

## Privacy and security

- [ ] Email, phone, SSN, DOB, address, and curated restricted fields have no
  sample values in LLM prompts or metadata records.
- [ ] Restricted-column questions return `refuse_unauthorized`.
- [ ] DML/DDL and multi-statement SQL are rejected.
- [ ] Unknown tables and unregistered join keys are rejected.
- [ ] `AIBI_INCLUDE_DRAFTS` is false in production.

## KPI activation

- [ ] Formula references an observed data product.
- [ ] Formula is an aggregate expression, not a statement.
- [ ] Formula passes SQL policy validation.
- [ ] Formula executes within the configured budget.
- [ ] Result is not empty or all-null.
- [ ] Confidence meets the activation threshold.

## Join activation

- [ ] Both datasets and columns exist.
- [ ] Key value overlap meets the configured threshold.
- [ ] At least one side is unique.
- [ ] Cardinality recorded by onboarding matches observed data.
- [ ] Active join passes the normal SQL validator.
- [ ] Many-to-many or low-overlap candidates remain drafts.

## Dataiku Flow

- [ ] `AIBI_LLM_CONNECTION` identifies the intended LLM Mesh connection.
- [ ] Onboarding inputs contain all fact/dimension datasets.
- [ ] Outputs include `dataset_catalog` and `semantic_registry`.
- [ ] Registry and graph outputs retain prior rows and are read on later builds.
- [ ] Ask inputs contain facts, questions, registry, and graph.
- [ ] Adding a dataset requires only a Flow connection, not a recipe edit.
- [ ] Recipe code contains orchestration only.

## Portability

- [ ] No file under `lib/python/ai4bi` imports `dataiku`.
- [ ] Core tests pass without Dataiku installed.
- [ ] Storage records serialize as JSON-compatible dictionaries.
- [ ] No AWS-specific deployment dependency exists in the core.
