# Running locally

```powershell
.\run_local.ps1
```

Open **http://127.0.0.1:8000/app/** (API docs: http://127.0.0.1:8000/docs).

* `backend/` is the FastAPI service (from `aibi_v2`). `frontend/` is the dashboard, served by the backend at `/app/`.
* Everything is local: data under `backend/data/local/`, no login, no model. Answers come from the deterministic planner.
* **Upload data** in the UI sends files to `POST /api/domains/{domain}/datasets`; **Run onboarding** starts
  `POST /api/domains/{domain}/onboard` and polls `GET /api/jobs/{id}`.
* To host the frontend elsewhere, set `window.AI4BI_API_BASE` in `frontend/config.js`.

## AWS code is switched off, not removed

Every AWS dependency (S3, DynamoDB, Bedrock, Entra ID, `boto3`, `PyJWT`) is commented out and tagged
`AWS-DISABLED`. To bring AWS back, search for that tag and restore the lines:

```powershell
git grep -n "AWS-DISABLED"
```

The AWS modules themselves (`aws_clients.py`, `dynamo.py`, `s3_source.py`, `entra.py`) are untouched but no longer imported.
`tests/test_aws.py` and `tests/test_auth.py` are skipped via `collect_ignore` in `tests/conftest.py`.
