# Running locally

Two terminals. No AWS account or model is needed.

**Terminal 1: backend** (from the repo root)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

API on http://127.0.0.1:8000 (docs at /docs).

**Terminal 2: frontend**

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Vite proxies `/api` to the backend (see `frontend/vite.config.js`).
If the backend is elsewhere, set `VITE_BACKEND_URL` (dev proxy) or `VITE_API_BASE` (direct calls).

* Everything is local: data under `backend/data/local/`, no login, no model. Answers come from the deterministic planner.
* **Upload data** in the UI sends files to `POST /api/domains/{domain}/datasets`; **Run onboarding** starts
  `POST /api/domains/{domain}/onboard` and polls `GET /api/jobs/{id}`.

## AWS code is switched off, not removed

Every AWS dependency (S3, DynamoDB, Bedrock, Entra ID, `boto3`, `PyJWT`) is commented out and tagged
`AWS-DISABLED`. To bring AWS back, search for that tag and restore the lines:

```bash
git grep -n "AWS-DISABLED"
```

The AWS modules themselves (`aws_clients.py`, `dynamo.py`, `s3_source.py`, `entra.py`) are untouched but no longer imported.
`tests/test_aws.py` and `tests/test_auth.py` are skipped via `collect_ignore` in `tests/conftest.py`.
