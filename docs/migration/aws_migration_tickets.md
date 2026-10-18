# AWS Migration Backlog

67 tickets, 217 subtasks, about 256 person-days (rough estimates, excludes review and waiting time).

Import `asana_import.csv`: rows with an empty 'Parent' are tickets, others are subtasks.

## A. Remove Sample / Demo Dependencies

The code only works because sample data, sample domains and one developer's laptop paths are baked in. Evidence: SQL strings in aibi/semantic_executor.py hardcode the table name KPI_data and its columns; aibi/kpi_data.py falls back to C:\Users\BharadNa\Downloads; llmkg/engine.py defaults to domain generic_cube; frontend/app/services/backend.py defaults to service_ops; there is no .gitignore.

### A1. Remove hardcoded KPI_data table and column coupling
**Priority:** High | **Estimate:** 6 days | **Depends on:** -

- [ ] Grep and list every hardcoded table/column name (KPI_data, ACTUAL_COL, FORECAST_COL, BU_COL, QUARTER_COL) in semantic_executor.py, kpi_data.py, kpi_analytics.py, ask_service.py, llmkg/engine.py, llmkg/seed.py
- [ ] Move column mappings into config/data_products.yaml 'columns' (the schema already exists) and load them per data product
- [ ] Parameterise SQL builders in semantic_executor.py (about 12 f-strings) by data product id instead of the literal KPI_data
- [ ] Delete default_kpi_path() fallbacks (Downloads folder, nl2sql_root)
- [ ] Remove the 'KPI_data' defaults in ask_service.py:50, llmkg/engine.py:384 and llmkg/seed.py:110
- [ ] Remove KPI_data wording from frontend/app/main.py UI text
- [ ] Add a test that runs the same questions against a second, differently-named product to prove nothing is hardcoded

### A2. Remove sample data and fixtures from the product
**Priority:** High | **Estimate:** 4 days | **Depends on:** -

- [ ] Classify data/purchase_details.csv (real PO numbers, buyer names, vendor ids): confirm whether it is real company data
- [ ] If real or sensitive: remove from the repo and from git history (git filter-repo), and report to data owner
- [ ] Delete local_data/fixtures/KPI_data.parquet and service_ops/*.csv from the app; recreate tiny synthetic fixtures under tests/fixtures/ only (no real emails)
- [ ] Delete local_data/cache and data/README.md guidance about laptop datasets
- [ ] Delete Created/ (Invoice_Processing_SOP.docx, Traditional_ML_Status_Text.pdf): unrelated to the product
- [ ] Point config/data_products.yaml at S3/DB locations via environment config; no relative local paths

### A3. Remove sample domains and make domain an explicit input
**Priority:** High | **Estimate:** 4 days | **Depends on:** -

- [ ] Decide with owners which domains are real (service_ops? generic_cube? kpi_productivity?) and which are samples
- [ ] Move sample domains (onboarding/domains/generic_cube, service_ops; semantic/business_units/example_bu.yaml) to examples/ or tests/fixtures/
- [ ] Remove default domain arguments: llmkg/engine.py:39 (generic_cube), run_onboard.py:32 (service_ops), frontend/app/services/backend.py:117 (service_ops); make domain required
- [ ] Move semantic/domains/_template_domain.yaml and onboarding/templates/contract.yaml into docs/templates
- [ ] Update config/platform.yaml, dashboard.yaml and visual_templates.yaml so they hold no sample names

### A4. Replace demo users and local auth
**Priority:** High | **Estimate:** 3 days | **Depends on:** -

- [ ] Delete config/local_users.yaml (local.cross_bu, local.analyst 'Climate Solutions Americas', local.steward)
- [ ] Refactor aibi/auth.py to take identity and BU scope from a verified token, behind an interface
- [ ] Keep a test-only fake identity provider under tests/

### A5. Separate sample evaluation from real evaluation
**Priority:** Medium | **Estimate:** 3 days | **Depends on:** A3

- [ ] Move evaluation/excel_escape/service_ops.yaml to tests/ as a regression sample
- [ ] Define the real Excel Escape question set per real domain with business owners and expected values
- [ ] Make eval.py (aibi/experience/eval.py) read from a configurable location (S3 or repo path)

### A6. Remove machine-specific paths and personal references
**Priority:** High | **Estimate:** 2 days | **Depends on:** -

- [ ] Replace C:\Users\BharadNa paths in aibi/settings.py, config/settings.yaml, .env.example, README.md, run_dashboard.bat/.ps1 and docs
- [ ] Introduce environment-variable driven settings (12-factor); delete AI_BI_NL2SQL_ROOT
- [ ] Delete Windows-only launch scripts or replace with a cross-platform Makefile/docker compose

### A7. Rewrite docs that describe the sample/local/Dataiku setup
**Priority:** Medium | **Estimate:** 3 days | **Depends on:** A1,A3,A6

- [ ] Review all 14 docs in docs/ and mark keep / rewrite / delete
- [ ] Delete docs/dataiku_flow.md, docs/dss_kpi_cube_recipe.md, docs/local_hosting.md, docs/local_project_layout.md
- [ ] Write a new README and an architecture doc for the AWS design

## B. Remove Dataiku Dependency

Dataiku is used in 3 ways: (1) LLM access (llmkg/llm.py _dss_llm, ask_service._require_mesh_in_dss), (2) dataset I/O and 6 recipes, (3) an external NL-to-SQL repo (nlq.*) that this project imports from outside itself. Warning: recipes such as aibi_semantic_validation (667 lines), aibi_semantic_evaluation (566) and aibi_batch_ask (476) contain logic that does not exist in aibi/. It must be extracted before the folder is deleted.

### B1. Inventory and classify every Dataiku touchpoint
**Priority:** High | **Estimate:** 1 days | **Depends on:** -

- [ ] List imports of dataiku, nlq.dataiku_adapters, flask-in-DSS across the repo
- [ ] For each, label: LLM / dataset I/O / config / webapp / test / doc
- [ ] Produce the replacement for each (owner ticket)

### B2. Replace the LLM access layer
**Priority:** High | **Estimate:** 5 days | **Depends on:** B1

- [ ] Define an LLMClient interface (complete text, complete JSON, token usage)
- [ ] Implement a Bedrock client with retry, timeout and error mapping
- [ ] Rewrite llmkg/llm.py to use the interface; delete _dss_llm
- [ ] Remove _require_mesh_in_dss from ask_service.py and the Mesh connection id from settings
- [ ] Add a fake LLM for tests
- [ ] Check prompt behaviour on the new model: re-run the eval set and compare

### B3. Eliminate the external 'nlq' package dependency
**Priority:** High | **Estimate:** 6 days | **Depends on:** B1

- [ ] Trace exactly which nlq modules are used (nlq.graph.runner, nlq.config.settings, notebook_runner)
- [ ] Check licence and ownership of the dataiku-langgraph-nlq repo
- [ ] Vendor the required modules in as an internal package, or publish it as a versioned internal library
- [ ] Delete nlq.dataiku_adapters and python/nl_to_sql/bridge.py
- [ ] Add missing deps (langgraph etc.) to requirements
- [ ] Run the old and new path on the same questions to confirm parity

### B4. Extract logic from recipes before deleting them
**Priority:** High | **Estimate:** 6 days | **Depends on:** B1

- [ ] Read the 6 recipes and list logic that is not in aibi/ (validation rules, summaries, evaluation scoring)
- [ ] Move that logic into aibi modules with unit tests
- [ ] Rewrite each recipe as a plain CLI entrypoint with S3/DB input and output
- [ ] Package the CLIs as SageMaker Processing / Step Functions jobs (see G4)

### B5. Extract logic from the DSS webapp backend
**Priority:** Medium | **Estimate:** 4 days | **Depends on:** B1

- [ ] Catalog its routes: summary, catalog, SQL execution, LLM routes
- [ ] Map each to a new API endpoint (see F1)
- [ ] Port the select-only SQL guard (_is_select_only) and keep its tests
- [ ] Port or retire the bundled body.html / app.js / style.css (replaced by the new frontend)

### B6. Delete Dataiku code and fix tests
**Priority:** Medium | **Estimate:** 1 days | **Depends on:** B2,B3,B4,B5

- [ ] Delete dataiku/ and tests/factory/test_dss_recipe_io.py
- [ ] Confirm: grep for 'dataiku' and 'dss' returns nothing outside git history

## C. Service Separation (hardest part)

Facts from the code: aibi.settings is imported by about 20 modules and reads files from a global PROJECT_ROOT; frontend/app/services/backend.py imports aibi.* directly, so UI and backend are one process; ask_service.py (421 lines) orchestrates three engines; engines read YAML and data files straight from disk; llmkg writes knowledge_graph/*.json locally; aibi/factory/grounding.py and aibi/llmkg/grounding.py are identical 1563-line files. Recommendation: first enforce boundaries inside one codebase (C1-C7), then deploy separately only the pieces that need it (C8-C11). Splitting everything into network services at once is the highest-risk path.

### C1. Map the real dependency graph and set boundaries
**Priority:** High | **Estimate:** 3 days | **Depends on:** A1

- [ ] Generate the module import graph (pydeps or import-linter) and commit it
- [ ] Mark shared code vs service-specific code
- [ ] Draft the target services: ask-api (orchestration, auth, audit), semantic-catalog (factory loader/catalog/glossary/validate/compile), query-execution (catalog_executor, semantic_executor, tabular), llm-gateway, knowledge-graph store, batch jobs (onboarding, evaluation), frontend, shared lib
- [ ] Decide modular monolith first vs separate network services per boundary (ADR)
- [ ] Review with the team and freeze the boundaries

### C2. Resolve duplicated and overlapping engines
**Priority:** High | **Estimate:** 5 days | **Depends on:** C1

- [ ] Delete the identical copy of grounding.py (keep one in a shared module)
- [ ] Compare the three engines (llmkg, semantic_executor, factory/catalog_executor) on the eval set; document which questions each handles
- [ ] Choose routing rules or a single engine; retire dead code
- [ ] Resolve overlap of kpi_analytics.py with semantic_executor.py

### C3. Extract the shared library
**Priority:** High | **Estimate:** 4 days | **Depends on:** C1

- [ ] Move models, security_tags, auth interface, audit and logging into a shared package
- [ ] Replace the global settings/PROJECT_ROOT with injected configuration objects
- [ ] Remove direct file path access from shared code

### C4. Define interfaces between components
**Priority:** High | **Estimate:** 4 days | **Depends on:** C3

- [ ] Write protocols: LLMClient, DataSource, ProductRegistry, CatalogResolver, QueryExecutor, KnowledgeGraphStore, AuditSink, IdentityProvider
- [ ] Provide local/file and AWS implementations of each
- [ ] Make engines depend on these interfaces only

### C5. Break up ask_service.py into router and handlers
**Priority:** High | **Estimate:** 5 days | **Depends on:** C4

- [ ] Separate: identity/scope, routing (semantic vs catalog vs llmkg vs NL-to-SQL), execution, audit, response shaping
- [ ] Remove module-level state and implicit file reads
- [ ] Add unit tests per handler before moving code

### C6. Refactor semantic_executor.py (619 lines)
**Priority:** High | **Estimate:** 5 days | **Depends on:** A1,C4

- [ ] Split SQL building, execution and response formatting
- [ ] Drive it from the semantic model, not constants

### C7. Enforce boundaries in CI
**Priority:** Medium | **Estimate:** 2 days | **Depends on:** C4

- [ ] Add import-linter rules so a service cannot import another's internals
- [ ] Fail the build on circular imports

### C8. Semantic catalog service
**Priority:** Medium | **Estimate:** 5 days | **Depends on:** C5

- [ ] Load semantic and onboarding artifacts from versioned S3 instead of local YAML
- [ ] Add in-memory cache with version invalidation
- [ ] Expose read endpoints: domains, metrics, glossary, versions

### C9. Knowledge graph store
**Priority:** High | **Estimate:** 5 days | **Depends on:** C4

- [ ] Replace local JSON writes with a store (S3/DynamoDB)
- [ ] Handle concurrent writers (optimistic locking or append-only events)
- [ ] Backfill or reseed existing graphs; decide retention

### C10. Decouple the frontend from in-process imports
**Priority:** High | **Estimate:** 4 days | **Depends on:** F1

- [ ] Replace frontend/app/services/backend.py (imports aibi.* directly) with an HTTP client
- [ ] Remove aibi from the frontend's dependencies

### C11. Inter-service concerns
**Priority:** Medium | **Estimate:** 4 days | **Depends on:** C8,C9

- [ ] Define timeouts, retries and error mapping between services
- [ ] Propagate correlation ids across calls and logs
- [ ] Add contract tests for every service boundary
- [ ] Per-service Dockerfile, requirements and health check

### C12. Parity check and cutover from the old structure
**Priority:** High | **Estimate:** 3 days | **Depends on:** C5,C6,C11

- [ ] Run the eval set on old and new; any diff must be explained
- [ ] Remove old entrypoints (run_cli.py, run_onboard.py wrappers) once covered

## D. Repo Cleanup

Items not covered above.

### D1. Repo hygiene
**Priority:** Medium | **Estimate:** 2 days | **Depends on:** -

- [ ] Add .gitignore (none exists): caches, local_data, .env, knowledge_graph output
- [ ] Add secret scanning and pre-commit
- [ ] Delete python/ alias layout (python/nl_to_sql, notebooks) if unused
- [ ] Consolidate semantic/ vs onboarding/ vs metadata/ definitions into one source of truth with a written rule
- [ ] Delete empty folders (frontend/app/chatbot, components, dashboard stubs) or implement them

### D2. Packaging
**Priority:** Medium | **Estimate:** 2 days | **Depends on:** C1

- [ ] requirements.txt lacks LLM, AWS and NL-to-SQL deps: create pyproject and pinned per-service requirements
- [ ] Add lockfiles and a reproducible build

## E. Engine Correctness Defects

Found by probing: multi-metric compare returns one metric; unknown scopes (AMER, North America) silently return the global value; time and status filters ignored; no group-by; no count metrics.

### E1. Multi-metric and comparison questions
**Priority:** High | **Estimate:** 3 days | **Depends on:** C5

- [ ] resolve_metric to return a list
- [ ] Executor returns one row per metric
- [ ] Eval asserts all metric ids

### E2. Unknown scope must clarify or refuse
**Priority:** High | **Estimate:** 2 days | **Depends on:** -

- [ ] Detect unrecognised region tokens
- [ ] Return a clarification instead of the default metric
- [ ] Add AMER to the catalog if intended

### E3. Time and status filters
**Priority:** High | **Estimate:** 5 days | **Depends on:** -

- [ ] Parse date phrases
- [ ] Apply to compute filter
- [ ] Warn when a filter cannot be applied

### E4. Group-by and ranking
**Priority:** Medium | **Estimate:** 4 days | **Depends on:** -

- [ ] Detect 'which/by region' intent
- [ ] Group in executor
- [ ] Return a table

### E5. Count metrics for service_ops
**Priority:** Medium | **Estimate:** 2 days | **Depends on:** -

- [ ] Define case_count and open_cases in dictionary.yaml
- [ ] Recompile metrics.yaml

### E6. Strengthen the evaluation gate
**Priority:** High | **Estimate:** 2 days | **Depends on:** A5

- [ ] Compare test must assert both metrics
- [ ] Add a case per defect above
- [ ] Run in CI as a blocking gate

## F. Backend API and Upload

### F1. API contract (OpenAPI)
**Priority:** High | **Estimate:** 3 days | **Depends on:** C1

- [ ] Endpoints: POST /v1/ask, POST /v1/ask/stream, GET /v1/domains, GET /v1/metrics, POST /v1/drill, GET /v1/explain/{id}, POST /v1/uploads, GET /v1/uploads/{id}, POST /v1/onboarding/validate, GET /v1/eval/{domain}, GET /health
- [ ] Request/response schemas, error model, pagination, versioning
- [ ] Review with frontend and freeze

### F2. Implement the API service
**Priority:** High | **Estimate:** 6 days | **Depends on:** F1,C5

- [ ] FastAPI app and routers
- [ ] Dependency injection of LLM, data, KG
- [ ] Structured errors and logging

### F3. Upload feature
**Priority:** High | **Estimate:** 8 days | **Depends on:** F1,A2

- [ ] Presigned S3 upload URL endpoint
- [ ] Limits: file types, size, row count
- [ ] Validate against the onboarding contract (schema, types, keys)
- [ ] PII / restricted column detection (security_tags)
- [ ] Virus scan
- [ ] Register as a data product and trigger onboarding validation as a job
- [ ] Status endpoint and failure messages
- [ ] Delete/replace uploaded dataset

### F4. Authentication and row-level security
**Priority:** High | **Estimate:** 4 days | **Depends on:** A4

- [ ] Validate JWT
- [ ] Map claims to authorised BU codes
- [ ] Enforce in every executor
- [ ] Tests that BU A cannot read BU B

### F5. SageMaker inference adapter
**Priority:** High | **Estimate:** 3 days | **Depends on:** F2

- [ ] /ping and /invocations wrapper
- [ ] Payload size limits
- [ ] Sync vs async decision for slow LLM calls

### F6. Hardening
**Priority:** Medium | **Estimate:** 2 days | **Depends on:** F2

- [ ] Rate limiting
- [ ] CORS
- [ ] Request validation
- [ ] 29-second API Gateway limit: streaming or async job pattern

## G. SageMaker

### G1. Container image
**Priority:** High | **Estimate:** 3 days | **Depends on:** D2

- [ ] Dockerfile per deployable
- [ ] Push to ECR
- [ ] Vulnerability scan
- [ ] Non-root user

### G2. Run locally in SageMaker local mode
**Priority:** High | **Estimate:** 3 days | **Depends on:** G1,F5

- [ ] Verify /ping and /invocations
- [ ] Verify Bedrock and S3 access with dev credentials

### G3. Dev endpoint
**Priority:** High | **Estimate:** 4 days | **Depends on:** G2

- [ ] Choose real-time vs async vs serverless
- [ ] Instance sizing and autoscaling
- [ ] VPC, security groups, VPC endpoints
- [ ] Least-privilege IAM role and KMS

### G4. Batch jobs
**Priority:** Medium | **Estimate:** 4 days | **Depends on:** B4

- [ ] Onboarding/validation, metric compile, evaluation as Processing jobs
- [ ] Step Functions orchestration
- [ ] Failure alerts

### G5. Artifact versioning
**Priority:** Medium | **Estimate:** 2 days | **Depends on:** C8

- [ ] S3 versioning for semantic/onboarding files
- [ ] Dev to prod promotion and rollback

### G6. Load and latency tests
**Priority:** Medium | **Estimate:** 3 days | **Depends on:** G3

- [ ] Set SLOs
- [ ] Concurrent user test
- [ ] Tune timeouts and instance count

### G7. Full functional test on SageMaker
**Priority:** High | **Estimate:** 3 days | **Depends on:** G3

- [ ] Run whole eval set
- [ ] Test every endpoint and the upload flow
- [ ] Sign-off report

## H. Frontend

Existing frontend is a 502-line Streamlit file whose chatbot, components and dashboard folders are empty.

### H1. Choose framework
**Priority:** High | **Estimate:** 1 days | **Depends on:** -

- [ ] Streamlit vs React/Next.js
- [ ] Decision on hosting and auth integration

### H2. UX design
**Priority:** High | **Estimate:** 6 days | **Depends on:** H1

- [ ] User personas and top journeys
- [ ] Wireframes: chat, dashboard, upload, drill, explain
- [ ] States: loading, empty, error, clarification
- [ ] Stakeholder review

### H3. App shell and login
**Priority:** High | **Estimate:** 4 days | **Depends on:** H2

- [ ] SSO / Cognito flow
- [ ] Token storage and refresh
- [ ] Layout and navigation

### H4. Chat UI
**Priority:** High | **Estimate:** 6 days | **Depends on:** H3

- [ ] Streaming answers
- [ ] Clarification prompts
- [ ] Show metric, version, SQL, provenance
- [ ] History

### H5. Dashboard
**Priority:** Medium | **Estimate:** 6 days | **Depends on:** H3

- [ ] KPI tiles and charts from visual_templates.yaml
- [ ] BU/region filters

### H6. Upload UI
**Priority:** High | **Estimate:** 4 days | **Depends on:** H3,F3

- [ ] Drag and drop
- [ ] Progress and validation errors
- [ ] Uploaded products list

### H7. Drill and explain views
**Priority:** Medium | **Estimate:** 4 days | **Depends on:** H3

- [ ] Consume /drill and /explain

### H8. Quality and hosting
**Priority:** Medium | **Estimate:** 6 days | **Depends on:** H4

- [ ] Accessibility and responsive checks
- [ ] Static hosting (S3 + CloudFront) with WAF and TLS

## I. Frontend-Backend Connection

### I1. Typed API client
**Priority:** Medium | **Estimate:** 1 days | **Depends on:** F1

- [ ] Generate client from OpenAPI

### I2. Connect to dev backend
**Priority:** High | **Estimate:** 4 days | **Depends on:** G3,I1,C10

- [ ] Per-environment config
- [ ] CORS
- [ ] Token forwarding
- [ ] Error mapping

### I3. Contract and end-to-end tests
**Priority:** High | **Estimate:** 6 days | **Depends on:** I2

- [ ] Schemathesis/Pact in CI
- [ ] Playwright: login, upload, ask, drill, explain
- [ ] Negative paths

## J. Infrastructure and Operations

### J1. Infrastructure as code
**Priority:** High | **Estimate:** 8 days | **Depends on:** G1

- [ ] VPC and endpoints
- [ ] S3, ECR, SageMaker, API Gateway, Cognito, CloudFront, IAM
- [ ] Dev/test/prod stacks

### J2. CI/CD
**Priority:** High | **Estimate:** 5 days | **Depends on:** J1

- [ ] Lint, tests, eval gate
- [ ] Image build and deploy with approvals
- [ ] Rollback

### J3. Monitoring and cost
**Priority:** Medium | **Estimate:** 4 days | **Depends on:** G3

- [ ] Latency, errors, LLM tokens/cost
- [ ] Alarms and dashboards
- [ ] Budgets and tags

## K. Testing and Security

### K1. Port existing unit tests
**Priority:** High | **Estimate:** 3 days | **Depends on:** C12

- [ ] Fix tests broken by moves
- [ ] Add tests for new interfaces

### K2. Security review
**Priority:** High | **Estimate:** 5 days | **Depends on:** F2

- [ ] Prompt injection
- [ ] SQL injection in generated SQL
- [ ] Upload abuse
- [ ] Authorisation bypass
- [ ] Secrets

### K3. PII review
**Priority:** High | **Estimate:** 2 days | **Depends on:** F3

- [ ] Confirm restricted columns (for example contact_email) never reach LLM prompts or UI

### K4. User acceptance testing
**Priority:** High | **Estimate:** 5 days | **Depends on:** I2

- [ ] Business owners run their real questions
- [ ] Triage and fix failures

## L. Go-Live

### L1. Operations readiness
**Priority:** High | **Estimate:** 3 days | **Depends on:** J3

- [ ] Runbook
- [ ] On-call
- [ ] Rollback plan

### L2. Documentation and training
**Priority:** Medium | **Estimate:** 3 days | **Depends on:** A7

- [ ] How to onboard a new domain
- [ ] API docs
- [ ] User guide

### L3. Cutover and hypercare
**Priority:** High | **Estimate:** 3 days | **Depends on:** K4,L1

- [ ] Production deploy
- [ ] Monitor closely for two weeks
