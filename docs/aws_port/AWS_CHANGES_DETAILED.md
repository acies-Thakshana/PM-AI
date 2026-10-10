# AWS / DynamoDB redesign: complete change list (to port to another branch)

Base commit: `030ba90` ("Added contents for DynamoDB"). Everything below is the difference between that
commit and the working tree: 27 files, 960 insertions, 257 deletions. Committed so far as `5692e68`; the
rest (single `COLUMNS` / `ISSUES` / `FEATURES` / `ANALYSES` items, two-text `BRIEF`, `planner_suggest`
details, batch-order fix) is uncommitted at the time of writing. `aws-redesign.patch` in this folder holds all
of it in one patch.

## 1. How to port it

**Option A: apply the patch (recommended).** From the repo root on the other branch:

```bash
git apply --check docs/aws_port/aws-redesign.patch      # dry run, changes nothing
git apply docs/aws_port/aws-redesign.patch              # applies it to the working tree
# if the other branch moved on and the check fails:
git apply --3way docs/aws_port/aws-redesign.patch       # leaves conflict markers where needed
```

It was verified to apply cleanly to a fresh checkout of `030ba90`, and both test scripts passed there.

**Option B: cherry-pick the commit, then the rest.** `git cherry-pick 5692e68`, then apply the remaining
uncommitted work with the patch (or commit it here first and cherry-pick that commit too).

**Option C: by hand.** Use section 4 below as the checklist; every file and what changed in it is listed.

**After applying:** run the checks in section 7, create the AWS resources in section 2, and set the
environment variables in section 3.

## 2. AWS resources the code now expects

Three DynamoDB tables (on-demand, point-in-time recovery on, deletion protection on, TTL attribute `ttl`):

| Table | Partition key | Sort key |
|---|---|---|
| `pmai-docs` | `session_id` (S) | `doc` (S) |
| `pmai-profiles` | `user_id` (S) | `profile` (S) |
| `pmai-audit-log` | `session_id` (S) | `ts_event` (S) |

`pmai-audit-log` global secondary indexes (both projection ALL):

| Index | Partition key | Sort key |
|---|---|---|
| `by-user` | `user_id` (S) | `ts_event` (S) |
| `by-target` | `target_key` (S) | `ts_event` (S) |

`pmai-sessions` is **no longer used**, and **S3 is no longer used at all** (section 3b).
The existing task-role policy (`table/pmai-*` and `table/pmai-*/index/*`) already covers the new index.

## 3. Configuration

| Item | Change |
|---|---|
| `DDB_SESSIONS` | **Removed** from `config.py`, `.env.example`, `deploy/taskdef.json`, `deploy/README.md` |
| `S3_BUCKET`, `PRESIGN_EXPIRY_SECONDS` | **Removed** (no S3) |
| `USE_AWS_STORAGE` | Now `bool(DDB_DOCS)` |
| `MEMORY_FRAME_SESSIONS` | **New**, optional, default 50: sessions' DataFrames one process keeps in memory |
| Required | `DDB_DOCS`, `DDB_PROFILES`, `DDB_AUDIT` |

## 3b. No S3: DataFrames in memory, uploads through the API

| Was | Now |
|---|---|
| DataFrames saved to `s3://<bucket>/frames/<session>/<name>.parquet` | Kept in the process's memory (`session_repo._mem_frames`), LRU-limited to `MEMORY_FRAME_SESSIONS`; copied on the way in and out. Frame reference in the header is `{"fmt": "memory", "rows": n}`. Local-file mode (no `DDB_DOCS`) unchanged. |
| A frame missing from memory | `session_repo.FramesUnavailable`; `main.py` turns it into **HTTP 410** "upload the file again" |
| `/upload-url` returned a presigned S3 URL, then `/upload/complete` read the file back | `/upload-url` always returns `{"mode": "direct"}` and the page posts the multipart form to `/upload` (the frontend already did that for `direct`); `/upload/complete`, `UploadCompleteRequest`, `_sanitize_filename` and the `uuid`/`aws_clients` imports in `audit.py` are removed |
| Items over ~300 KB overflowed to S3 (`s3_key`) | gzip-compressed into a binary attribute `gz` (`COMPRESS_OVER_BYTES` = 300 000, `MAX_ITEM_BYTES` = 380 000); `ValueError` with a clear message if still too large. `blob_get`, `blob_put` and `list_docs` read both `payload` and `gz`; the `s3_prefix` parameter is gone from `blob_get` / `blob_put` and their callers. |
| `aws_clients.s3()`, S3 statements in `deploy/iam/pmai-task-role.json`, `S3_BUCKET` in `deploy/taskdef.json`, `.env.example` and the README | Removed |

Operating consequences: **run one backend task** (or turn on ALB stickiness); a restart or deployment drops the
open sessions' DataFrames (their DynamoDB documents stay); budget about two copies of each active file in task memory;
behind API Gateway the upload body limit is 10 MB.

## 4. Documents in `pmai-docs` (sort key `doc`)

| `doc` | One item per | Holds | Replaces |
|---|---|---|---|
| `SESSIONS` | session | the session header: owner, filename, source, `row_count`, `column_count`, frame refs, selections, `audit_events`, `mutation_stack`, timestamps (**no longer** the issues) | the `pmai-sessions` item |
| `BRIEF` | session | `client_brief.raw_text`, `client_brief.understanding_text`, `files`, `created_at`, `session_id` (no language fields) | `BRIEF_META` |
| `COLUMNS` | session | `{"column_count", "columns": {name: profile}}` in file order | `COLUMN_META` |
| `PLAN#<nnn>` | recommendation | the AI proposal + `pm_decision`, `pm_notes`, `index`, `proposed_at`, `decided_at` | `PLANNER_SUGGEST` + `PLANNER_OUTPUT` |
| `ISSUES` | session | `{"issue_count", "issues": [finding + applied step]}` | the header's `issues` list |
| `OUTLIER` | session | outlier actions (detected / edit / review) | `OUTLIER_AUDIT` |
| `FEATURES` | session | `{"feature_count", "by_source", "updated_at", "features": [...]}`; each feature has `source`, `status`, definition, `persisted`, `created_at`, and `cache` (plan + final code) | `FEATURE_REPO` + `FCACHE#<id>` |
| `ANALYSES` | session | same shape with `analyses`, `analysis_count`; sources include `drilldown` | `ANALYSIS_REPO` + `ACACHE#<id>` |
| `PROPOSAL#<analysis id>#<nnn>` | drill-down suggestion | one guided proposal | `guided_proposals` inside `RESULT#` |
| `DRILL#<analysis id>#<path id>` | drill-down path | one path | the `PATHS` list |
| `RESULT#<analysis id>` | analysis run | run result (table, chart, interpretation, status), without proposals | unchanged name |
| `DRAFT#<token>` | feature draft | unchanged (2-day TTL) | unchanged |
| `OVERALL` | session | overall analysis | unchanged |

Feature / analysis `source` values: `predefined`, `planner`, `custom` (user defined), `ai_suggested`,
`drilldown` (analyses only). `status`: `pending` / `approved` / `rejected`, so an accepted AI suggestion is the
`ai_suggested` entry whose status is `approved`.

## 5. Events in `pmai-audit-log`

Attributes: `session_id`, `ts_event`, `event_id`, `user_id`, `event_type`, `category`, `step` (Number),
`step_name`, `target`, `target_key` (`<session_id>#<target>`, only when there is a target), `result`
(`ok` / `failed`), `summary`, `payload` (JSON text), `ttl`.

Steps: 1 Upload, 2 Planner, 3 Audit, 4 Features, 5 Analysis, 6 Report, 0 general. Callers still pass
`(session_id, user_id, event_type, payload)`; `category`, `step`, `target` and `summary` come from
`EVENT_CATALOG` in `audit_log.py`:

| event_type | category | step | target |
|---|---|---|---|
| `upload` | session | 1 | `SESSIONS` |
| `brief_finalize` | session | 1 | `BRIEF` |
| `planner_suggest`, `planner_save` | planner | 2 | none |
| `audit_run`, `download` | audit | 3 | `SESSIONS` |
| `decision`, `revert` | audit | 3 | `ISSUES#{issue_id}` |
| `edit`, `outlier_detected`, `outlier_edit`, `outlier_review` | outlier | 3 | `OUTLIER` |
| `feature_suggested`, `feature_draft`, `apply_features` | feature | 4 | none |
| `feature_custom_added`, `feature_accepted`, `feature_rejected` | feature | 4 | `FEATURES#{entry_id}` |
| `analysis_suggested` | analysis | 5 | none |
| `analysis_custom_added`, `analysis_accepted`, `analysis_rejected`, `analysis_run`, `drilldown_suggested`, `drilldown_proposed`, `drilldown_run` | analysis | 5 | `ANALYSES#{entry_id}` |
| `drilldown_path_accepted`, `drilldown_path_rejected` | analysis | 5 | `DRILL#{entry_id}#{path_id}` |
| `report_downloaded` | report | 6 | `OVERALL` |
| `llm_call` | ai | by call name (`CALL_STEPS`) | the call's `output_ref` |
| `code_attempt`, `code_run`, `code_fallback` | ai | 4 (feature) / 5 (analysis) | `FEATURES#` / `ANALYSES#` + `entry_id` |

## 6. File-by-file changes

### New files

| File | What it is |
|---|---|
| `backend/app/services/common/entry_store.py` | Generic "one JSON per session" store used for features and analyses: `EntryDoc` (`load_persisted`, `get_cache`, `add`, `update_persisted`, `sync`, `set_cache`, `drop_cache`), `public()`, `_merge_derived()`, and the two instances `FEATURES` and `ANALYSES`. Atomic read-modify-write through `doc_store.update`. Entries added in one call keep their order through `created_at = "<timestamp>#<nnn>"`. |
| `backend/app/services/common/column_meta.py` | `save(session_id, df)` writes the single `COLUMNS` item; `load(session_id)` returns `{session_id, row_count, column_count, columns}` (row count from the session header). |
| `backend/app/services/planner/planner_store.py` | `PLAN#<nnn>` documents: `load`, `save_suggestions(append=)`, `apply_decisions`, `accept`. First suggest replaces the list but keeps a decision already made on a recommendation with the same name; "more" appends. |
| `docs/DYNAMODB_REDESIGN_PLAN.md` | The design plan, kept current with the changes. |

### Modified files

| File | Changes |
|---|---|
| `backend/.env.example` | Storage comment: set `DDB_DOCS` (DataFrames then stay in memory, run one task); the `DDB_SESSIONS` and `S3_BUCKET` lines are removed. |
| `backend/app/config.py` | Removed `DDB_SESSIONS`, `S3_BUCKET`, `PRESIGN_EXPIRY_SECONDS`; `USE_AWS_STORAGE = bool(DDB_DOCS)`; new `MEMORY_FRAME_SESSIONS`; upload comment. |
| `backend/app/services/common/session_repo.py` | Header is read and written in `DDB_DOCS` at key `{session_id, doc: "SESSIONS"}` (helper `_header_key`, constant `HEADER_DOC`). Frames: in-memory registry in DynamoDB mode (`_mem_put/_mem_get/_mem_delete`, `FramesUnavailable`), files in local mode; `_frame_key` and all S3 calls removed; docstring rewritten. Local-mode file name `session.json` unchanged. |
| `backend/app/services/common/doc_store.py` | `_safe_doc` adds a short hash when a character had to be replaced (so `Temp (C)` and `Temp_C_` do not share a local file); local wrapper files now store the real doc name and `list_docs` returns it; new `delete_prefix()`; new `put_many()` (parallel writes on AWS, one `request_context.wrap` per task so the user is stamped); large items are gzip-compressed (`gz`) instead of overflowing to S3 (`COMPRESS_OVER_BYTES`, `MAX_ITEM_BYTES`, `s3_prefix` parameter and `_s3_prefix` removed); docstring example names updated; `import hashlib`, `import gzip`. |
| `backend/app/services/common/audit_log.py` | Rewritten: `STEPS`, `EventSpec`, `EVENT_CATALOG`, `CALL_STEPS`, `classify()`, `_fill()`, `_result_of()`; `log_event(..., *, target=None, result=None)` stores `event_id`, `category`, `step`, `step_name`, `target`, `target_key`, `result`, `summary`; `_decode` returns the new fields; new `events_for_target()` (uses `by-target`). |
| `backend/app/services/common/code_run_log.py` | `code_attempt` payload is now only `kind, entry_id, entry_name, path, attempt, status, stage` (no code, error or validation text); docstring updated. Unused parameters stay in the signature. |
| `backend/app/services/common/token_usage.py` | `_OUTPUT_REFS` use the new targets: `FEATURES#{e}`, `ANALYSES#{e}`, `RESULT#{e}`, `DRILL#{e}`, `PLAN`, `FEATURES`, `ANALYSES`, `OVERALL`, `SESSIONS`. |
| `backend/app/services/common/selections.py` | Planner decisions come from `planner_store.load`; outlier summary from doc `OUTLIER`. |
| `backend/app/services/audit/audit_store.py` | `AuditSession` gets `row_count`, `column_count` (set from the dataframe, saved in the header); header no longer contains `issues`; issues are the single `ISSUES` doc (`ISSUES_DOC`, `_issue_entry()` adds the `applied` step from `audit_events`; written only when changed; `_issues_doc` snapshot); old sessions whose issues are still in the header load from there; drill-down proposals live in `PROPOSAL#<analysis>#<nnn>` (`_group_proposals`, `_proposal_doc_name`, `_proposal_docs` snapshot; results are saved without `guided_proposals`, proposals re-attached on load, extras deleted when the list shrinks); module docstring updated. |
| `backend/app/services/audit/outlier_audit.py` | `DOC = "OUTLIER"` (was `OUTLIER_AUDIT`) and docstring. |
| `backend/app/routers/audit.py` | Upload stores column metadata with `column_meta.save(...)` instead of building `COLUMN_META`; imports now `column_meta` (not `doc_store`) and no `profile_dataframe`. |
| `backend/app/routers/brief.py` | Writes doc `BRIEF`; `client_brief` is `{raw_text, understanding_text}` where `understanding_text` = translated text, else final text, else raw text; language fields are accepted by the request model but not stored. |
| `backend/app/routers/planner.py` | `/suggest` logs `planner_suggest` with `more`, `request`, `count`, `by_type`, `names`; `/save` writes decisions through `planner_store.apply_decisions`, then refreshes the feature/analysis planner snapshots (`feature_repository.sync`, `analysis_repository.sync`, failures only logged); removed the `PLANNER_SUGGEST` / `PLANNER_OUTPUT` handling and unused imports. |
| `backend/app/routers/analysis_paths.py` | `drilldown_path_accepted` / `_rejected` events include `entry_id` (the path's `root_id`) so the `DRILL#` target can be built. |
| `backend/app/services/planner/planner.py` | Reads `column_meta.load` and the `BRIEF` doc (prefers `understanding_text`, falls back to `translated_text` / `final_text` / `raw_text` for old briefs); stores recommendations with `planner_store.save_suggestions(..., append=bool(additional_context.strip()))`; error messages and docstring updated; imports. |
| `backend/app/services/features/feature_repository.py` | Planner entries read from `planner_store`; persisted entries live in the `FEATURES` doc through `entry_store.FEATURES` (`_derived`, `_load_persisted`, `sync`, `add_custom_entry`, `add_ai_suggested_entries` (one write for the batch), `set_entry_status`); `REPO_DOC`, `PLANNER_OUTPUT_DOC` and the per-item helpers removed; docstring updated. |
| `backend/app/services/features/feature_cache.py` | Cache stored in the feature's own record (`FEATURES.get_cache / set_cache / drop_cache`); same public functions `get`, `set`, `invalidate`; adds `cached_at`. |
| `backend/app/services/analysis/analysis_repository.py` | Same pattern with `ANALYSES`: `_derived`, `_load_persisted`, `sync`, `_store`, `update_entry`, `set_entry_status`; AI suggestions written as one batch; `REPO_DOC`, `PLANNER_DOC` removed. |
| `backend/app/services/analysis/analysis_cache.py` | Cache stored in the analysis record (`ANALYSES`); same public functions; adds `cached_at`. |
| `backend/app/services/analysis/analysis_dependencies.py` | Accepting a planner feature now calls `planner_store.accept(session_id, index, ("feature", "feature_and_analysis"))`. |
| `backend/app/services/analysis/analysis_paths.py` | Paths are `DRILL#<root_id>#<path_id>` documents: `load` (oldest first by `created_at`), `get`, `upsert` (put); the `PATHS` doc is gone. |
| `deploy/README.md` | Variables table: `DDB_DOCS`, `MEMORY_FRAME_SESSIONS`; resources paragraph lists the three tables and both indexes and says no S3 bucket is needed (run one task, restarts drop open sessions' data). |
| `deploy/taskdef.json` | Removed the `DDB_SESSIONS` and `S3_BUCKET` environment entries. |
| `deploy/iam/pmai-task-role.json` | Removed the `S3Data` and `S3List` statements. |
| `backend/app/services/common/aws_clients.py` | Removed `s3()`. |
| `backend/app/services/common/profile_store.py` | Dropped the `s3_prefix` argument from its `blob_get` / `blob_put` calls. |
| `backend/app/routers/audit.py` (S3 part) | `/upload-url` always returns `{mode: direct}`; `/upload/complete`, `UploadCompleteRequest`, `_sanitize_filename`, `uuid` and `aws_clients` imports removed; docstring updated. |
| `backend/app/main.py` | New exception handler: `session_repo.FramesUnavailable` -> HTTP 410. |

## 7. Behaviour changes to know about

- Planner "generate more suggestions" **appends** (before it overwrote the stored list with only the new batch).
- Re-suggesting keeps earlier decisions for recommendations with the same name.
- The Upload page's brief is saved on the **first** audited session of an upload only (unchanged behaviour).
- Predefined and planner entries are **snapshots** inside `FEATURES` / `ANALYSES`; reads still derive them fresh.
- `code_attempt` events no longer carry code or error text.
- Existing data written by the old layout (separate `pmai-sessions`, `COLUMN_META`, `FEATURE_REPO`, `ACACHE#`, ...)
  is not read by the new code. Use new sessions or delete the old test items.
- DataFrames live in memory only: run one task; a restart or deployment makes affected sessions answer HTTP 410 until the file is uploaded again.
- Not done: undo from stored before-values (the revert still replays from `audit_baseline`).

## 8. Checks to run on the other branch

The two scripts in `checks/` exercise the whole change (including the no-S3 behaviour). They are not part of the repo's test suite.

```bash
# from backend/, with the project's Python
python ../docs/aws_port/checks/smoke_local.py "$(pwd)"                     # local-file mode, LLM stubbed
pip install --target /tmp/moto_lib "moto[dynamodb]"                        # once, outside your venv
python ../docs/aws_port/checks/smoke_aws.py "$(pwd)" /tmp                  # mocked DynamoDB (expects /tmp/moto_lib)
```

Both end with `FAILURES: none` (local: 68 checks, AWS: 52 checks at the time of writing).
`smoke_aws.py` takes the folder that contains `moto_lib` as its second argument.
