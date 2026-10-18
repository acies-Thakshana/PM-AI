# AI4BI backend

Ask business questions of your data in plain language. The service turns a question into a plan and a
read-only SQL query, runs it on the domain's data, and answers from the result, with the SQL, the
metric definitions and the warnings shown alongside. It runs on a laptop with no cloud account and on
AWS (S3, DynamoDB, Bedrock, Entra ID) without a code change.

This folder is the new FastAPI backend. The original code under `lib/`, `local/`, `sagemaker_app/` and
`storage/` is untouched; its question logic was ported here and checked against it (see Testing).

## Run it locally

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate        # source .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs. With nothing configured the service uses local files under
`data/local/`, has no login, and uses no model: answers come from the deterministic planner. Two sample
domains ship in `data/samples`: `service_ops` and `generic_cube`.

```bash
curl -X POST localhost:8000/api/ask -H "Content-Type: application/json" \
     -d '{"question": "What is EMEA FRT?", "domain": "service_ops"}'
```

## What it does

| Endpoint | Role | Purpose |
|---|---|---|
| `GET /health` | public | Liveness for the load balancer |
| `GET /api/info` | user | Version, storage backend, model mode, caller |
| `POST /api/ask` | user | Answer one question (`question`, optional `domain`, `session_id`) |
| `GET /api/domains`, `GET /api/domains/{d}` | user | Domains the caller may use; tables, columns, counts |
| `GET /api/domains/{d}/catalog` | user | Column metadata saved by onboarding (no values of restricted columns) |
| `GET /api/domains/{d}/checks` | user | Health checks, including stored validated queries |
| `POST /api/domains/{d}/batch`, `/evaluate` | user | Run (and score) a file of questions, at most 50 |
| `POST /api/domains/{d}/uploads` and `/uploads/complete` | steward | Presigned S3 upload (AWS) then verify |
| `POST /api/domains/{d}/datasets` | steward | Upload a file through the API (CSV, TSV, Excel, Parquet, JSON) |
| `POST /api/domains/{d}/onboard`, `GET /api/jobs/{id}` | steward / owner | Learn semantics as a background job; poll for the result |
| `GET/POST /api/domains/{d}/registry/...` | steward | Review drafts; approve, deprecate; add glossary terms, validated SQL, joins |

Uploading files to a new domain id creates that domain. Onboarding then reads the data, asks the model
(or the local heuristics when none is configured) to propose metrics, joins, glossary terms and rules,
and **activates only what passes deterministic checks**: a metric expression must run and return a value,
a join must overlap on real values. Everything else stays a draft for a steward to approve.

## Layout

```
app/
  main.py            app factory: middleware, error mapping, routers, startup validation
  config.py          Settings (env + config/settings.yaml), fail-fast validate()
  schemas.py         request and response models
  routers/           thin HTTP layer: deps.py (auth, roles, domain access), one module per area
  services/
    ask/             the question pipeline, domain view, batch, checks
    sql/             planner, SQL generator, grounding, validator, executor, repair
    semantic/        package loading, registry (append-only) and its stores, PII detection
    knowledge/       knowledge graph, retrieval, history and their stores
    onboarding/      semantic onboarding, stewardship, jobs, catalog store
    data/            sources (local, S3), versioned cache, uploads
    output/          answers, follow-ups, chart choice
    guardrails/      question checks, SQL policy
    common/          LLM client, prompts, AWS clients, DynamoDB helpers, Entra, audit, logging context
    context.py       builds everything once; picks local or AWS implementations
prompts/             one system prompt per model call (editable without touching code)
config/              tuning defaults and chart templates
data/                bundled sample data and baseline semantic packages (read-only)
scripts/             create_tables.py: DynamoDB tables and S3 bucket for a dev account
```

Every external dependency sits behind a small interface (`DatasetSource`, `RegistryStore`, `GraphStore`,
`HistoryStore`, `CatalogStore`, `JobStore`, `LlmClient`) with a local and an AWS implementation.

## Configuration

All settings are environment variables; `.env.example` lists them with comments. Three switches matter:

* **Storage.** Set `S3_BUCKET` and all five `DDB_*` tables to use AWS; set none to stay local. Setting
  only some is an error at startup.
* **Sign-in.** Set `ENTRA_TENANT_ID` and `ENTRA_CLIENT_ID` to require a Microsoft Entra ID token. AWS storage
  without sign-in refuses to start unless `ALLOW_ANON=1` is set deliberately.
* **Model.** Set `BEDROCK_DEFAULT_MODEL` (and optionally `BEDROCK_STRONG_MODEL` for planning, SQL and
  onboarding, `BEDROCK_CHEAP_MODEL` for answer text). Without it no model is called.

Prompts live in `prompts/<call>.txt`. `BEDROCK_PROMPT_IDS` can point a call at Bedrock Prompt Management
instead; if Bedrock cannot be reached the file is used.

## Deploying to AWS

1. **Resources.** An S3 bucket (private) and five on-demand DynamoDB tables. For a development account
   run `python -m scripts.create_tables` with the `S3_BUCKET` / `DDB_*` variables set. For production
   create the same with infrastructure-as-code from `app/services/common/dynamo_tables.py`:

   | Table | Partition key | Sort key | TTL |
   |---|---|---|---|
   | registry | `domain` | `sort_key` | none |
   | knowledge graph | `domain` | `sort_key` | `expires_at` (episodes) |
   | history | `session_key` | `sort_key` | `expires_at` |
   | jobs | `job_id` | none | `expires_at` |
   | audit | `session_id` | `ts_event` (+ `by_user` index on `user_id`, `ts_event`) | `expires_at` |

2. **Bucket CORS** for browser uploads (presigned POST), with your frontend origin:
   `[{"AllowedMethods": ["POST"], "AllowedOrigins": ["https://app.example.com"], "AllowedHeaders": ["*"]}]`

3. **Task role** (ECS) needs: `s3:GetObject`, `PutObject`, `DeleteObject`, `ListBucket` on the bucket;
   `dynamodb:GetItem`, `PutItem`, `UpdateItem`, `Query`, `BatchWriteItem` on the tables;
   `bedrock:InvokeModel` on the chosen models (and `bedrock:GetPrompt` if Prompt Management is used).
   No access keys are used anywhere.

4. **Entra ID.** Register the API with a scope `access_as_user`, app roles `AI4BI.User` and
   `AI4BI.Steward`, and (to restrict domains) the `groups` claim; map groups to domains with
   `DOMAIN_GROUPS='{"finance": ["<group object id>"]}'`.

5. **Run.** Build the `Dockerfile` (non-root, port 8000), point the load balancer health check at
   `/health`, and set the environment variables. Questions make three to six model calls, so keep the
   load balancer idle timeout above 60 seconds; API Gateway's 29-second limit is too short for `/api/ask`.

## Behaviours worth knowing

* The response says whether a model took part: `answer_path` is `llm` or `deterministic`, `llm` lists
  the provider per step, `confidence` is `null` unless the model supplied it, and a warning
  `llm_fallback_used` appears when a model is configured but a step fell back.
* Restricted (personal-data) columns, tagged by a steward or detected by name (email, phone, dob, ...),
  never reach a prompt, a SQL result or the catalog's sample values.
* Generated SQL is validated (one read-only statement, known tables, registered joins only) and runs in an
  in-memory SQLite copy of the data with a row limit and a step budget.
* Registry changes are append-only; every version, with who made it, is kept.
* The schema fingerprint ignores row counts, so loading more rows does not trigger re-onboarding.

## Testing

```bash
pip install -r requirements-dev.txt
ruff check . && ruff format --check .
pytest
```

The suite covers the sample-domain answers (the figures match the original implementation), the HTTP
flows, the AWS path against moto (S3 and DynamoDB are real moto resources; only Bedrock is faked), Entra
token validation, domain groups and fail-closed configuration.

## Known limits

* Each question loads the domain's tables into an in-memory SQLite database. Cached frames avoid re-reading
  and re-profiling, but very large tables cost memory and time per question.
* Onboarding jobs run on threads inside the API process. A task that stops mid-job leaves it `running`
  until it expires; start it again (onboarding is idempotent).
* The semantic registry and the knowledge graph are read from DynamoDB on every question; the graph grows
  with each distinct question until its items expire.
* Tested against moto and a fake Bedrock, not against a live AWS account or real models. The first real
  Bedrock run may need prompt tuning for the chosen model.
* If a user belongs to more than about 200 groups, Entra omits the `groups` claim and domain-group checks
  will deny that user.
