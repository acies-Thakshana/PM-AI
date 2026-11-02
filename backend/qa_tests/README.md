# QA tests

Tests written by QA. They do not change application code.

Setup (once, from `backend`):
    venv\Scripts\python.exe -m pip install -r qa_tests\requirements-test.txt

Run:
    venv\Scripts\python.exe -m pytest qa_tests -v

Files:
- `conftest.py`          shared fixtures: fake Microsoft signing keys, token maker
- `test_entra_token.py`  unit tests of `deps.validate_token`
- `test_entra_api.py`    real app through TestClient: no token, bad headers, identity, ownership
- `test_file_store_s3.py` per-user S3 file storage against moto (fake AWS)

Each test's docstring names the case ID from docs/PM-AI_Test_Cases_API_Sections.xlsx.
