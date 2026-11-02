"""Hardening checks: no raw error text, API docs hidden when deployed, tight CORS, non-root container."""
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import deps, planner

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(deps, "AUTH_ENABLED", False)
    monkeypatch.setattr(deps, "USE_AWS_STORAGE", False)
    monkeypatch.setattr(planner, "get_or_404", lambda sid: SimpleNamespace(user_id="local"))
    monkeypatch.setattr(planner.planner_store, "load", lambda sid: [])
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("error, status", [
    (RuntimeError("could not reach db.internal.example:5432 as admin"), 503),
    (ValueError("AccessDeniedException arn:aws:bedrock:eu-north-1:123456789012:model/x"), 502),
    (FileNotFoundError("/app/data/sessions/s1/frames.parquet"), 404),
])
def test_planner_errors_do_not_show_the_exception_text(client, monkeypatch, error, status):
    """TC-SEC-050: the caller gets a short message; host names, ARNs and paths stay in the server log."""

    def boom(*a, **k):
        raise error

    monkeypatch.setattr(planner.planner_service, "suggest", boom)
    r = client.post("/api/planner/suggest", json={"session_id": "s1"})
    assert r.status_code == status
    detail = r.json()["detail"]
    for secret in ("db.internal", "arn:aws", "/app/data", "AccessDenied", "admin"):
        assert secret not in detail


def _app_env(**env):
    code = "from app.main import app; print(app.docs_url, app.redoc_url, app.openapi_url)"
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True,
                         env={**__import__("os").environ, "ENTRA_TENANT_ID": "", "ENTRA_CLIENT_ID": "", "DDB_DOCS": "", **env})
    assert out.returncode == 0, out.stderr[-500:]
    return out.stdout.split()


def test_api_docs_hidden_when_sign_in_is_on():
    """TC-SEC-051: with Entra configured, /docs, /redoc and /openapi.json do not exist."""
    assert _app_env(ENTRA_TENANT_ID="t", ENTRA_CLIENT_ID="c") == ["None", "None", "None"]


def test_api_docs_hidden_when_aws_storage_is_on():
    """TC-SEC-051: the same when the deployed storage is on."""
    assert _app_env(DDB_DOCS="docs-table") == ["None", "None", "None"]


def test_api_docs_available_in_local_development():
    """Local mode keeps /docs for manual testing."""
    assert _app_env() == ["/docs", "/redoc", "/openapi.json"]


def test_api_docs_can_be_forced_off_locally():
    assert _app_env(ENABLE_API_DOCS="0") == ["None", "None", "None"]


def test_deployed_container_turns_localhost_cors_off():
    """The container env sets CORS_ALLOW_LOCALHOST=0, so a deployed API only trusts its own frontend's origin."""
    tf = (ROOT / "infra/modules/compute/main.tf").read_text(encoding="utf-8")
    assert 'name = "CORS_ALLOW_LOCALHOST", value = "0"' in tf


def test_no_wildcard_origin_in_any_environment():
    """No environment lists '*' as an allowed browser origin."""
    for env in ("dev", "uat", "prod"):
        line = [l for l in (ROOT / f"infra/envs/{env}/terraform.tfvars").read_text(encoding="utf-8").splitlines()
                if l.startswith("extra_cors_origins")][0].split("#")[0]
        assert '"*"' not in line and "localhost" not in line


def test_container_does_not_run_as_root():
    """The Dockerfile switches to a normal user before starting the app."""
    lines = [l.strip() for l in (BACKEND / "Dockerfile").read_text(encoding="utf-8").splitlines()]
    assert any(l.startswith("USER ") and l != "USER root" for l in lines)
    assert lines.index(next(l for l in lines if l.startswith("USER "))) < lines.index(next(l for l in lines if l.startswith("CMD")))
