"""API-level tests of Entra sign-in: the real FastAPI app, called through TestClient.

Covers the "who is calling" checks in docs/PM-AI_Test_Cases_API_Sections.xlsx
(TC-SEC-001, 002, 009, 011, 012, 075, 081, TC-UP-022, TC-UP-025 and the ownership rule).
"""
import asyncio

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import app
from app.routers import deps


@pytest.fixture
def client():
    # raise_server_exceptions=False: a crash shows up as a 500 we can assert on, not a Python traceback
    return TestClient(app, raise_server_exceptions=False)


def _api_calls():
    """Every (method, path) under /api, with {placeholders} filled in."""
    calls = []
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith("/api"):
            path = route.path
            for part in [p for p in path.split("/") if p.startswith("{")]:
                path = path.replace(part, "x")
            for method in route.methods - {"HEAD", "OPTIONS"}:
                calls.append((method, path))
    return sorted(calls)


# ---------------------------------------------------------------- no token

def test_every_api_route_rejects_a_missing_token(entra_on, client):
    """TC-SEC-001: all /api routes answer 401 with WWW-Authenticate: Bearer when there is no token."""
    calls = _api_calls()
    assert len(calls) > 30, "route list looks wrong"
    wrong = []
    for method, path in calls:
        r = client.request(method, path)
        if r.status_code != 401 or r.headers.get("www-authenticate") != "Bearer":
            wrong.append((method, path, r.status_code))
    assert wrong == []


def test_token_usage_route_needs_a_token(entra_on, client):
    """TC-SEC-001: /token-usage is not under /api but is protected too."""
    assert client.get("/token-usage").status_code == 401


def test_health_is_public(entra_on, client):
    """TC-SEC-011: /health is public by design."""
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("header", ["Basic dXNlcjpwYXNz", "Token abc", "bearer", "Bearerabc", ""])
def test_authorization_header_without_bearer_scheme(entra_on, client, header):
    """TC-SEC-002 (negative): wrong scheme or empty value gives 401 'Missing bearer token', never a 500."""
    r = client.get("/token-usage", headers={"Authorization": header})
    assert r.status_code == 401
    assert r.json()["detail"] == "Missing bearer token"


def test_bearer_with_empty_token(entra_on, client):
    """Boundary: the word Bearer followed by nothing is an invalid token, not a crash."""
    r = client.get("/token-usage", headers={"Authorization": "Bearer "})
    assert r.status_code == 401


def test_token_in_url_or_cookie_is_not_read(entra_on, client, make_token):
    """TC-SEC-075: only the Authorization header counts. Tokens in a URL would end up in logs."""
    token = make_token()
    assert client.get(f"/token-usage?access_token={token}").status_code == 401
    assert client.get("/token-usage", cookies={"token": token}).status_code == 401


# ---------------------------------------------------------------- with a token

def test_valid_token_is_let_in(entra_on, client, make_token):
    """Happy path (TC-UP-022 opposite): a good token reaches the route."""
    r = client.get("/token-usage", headers={"Authorization": f"Bearer {make_token()}"})
    assert r.status_code == 200
    assert set(r.json()) == {"summary_by_call", "records"}


def test_expired_token_over_http(entra_on, client, make_token):
    """TC-UP-023 / TC-SEC-072: expired token gives 401 'Token expired' through the real app."""
    import time

    r = client.get("/token-usage", headers={"Authorization": f"Bearer {make_token(exp=int(time.time()) - 10)}"})
    assert (r.status_code, r.json()["detail"]) == (401, "Token expired")


def test_wrong_scope_over_http(entra_on, client, make_token):
    """TC-UP-024: 403 through the real app."""
    r = client.get("/token-usage", headers={"Authorization": f"Bearer {make_token(scp='nothing')}"})
    assert r.status_code == 403


def test_token_without_user_id_is_rejected(entra_on, client, make_token):
    """TC-SEC-009: no oid and no sub means no user: 401 'Token has no user id'."""
    r = client.get("/token-usage", headers={"Authorization": f"Bearer {make_token(oid=None)}"})
    assert (r.status_code, r.json()["detail"]) == (401, "Token has no user id")


# ---------------------------------------------------------------- who the user is

def _user_for(token):
    return asyncio.run(deps.get_user(f"Bearer {token}"))


def test_user_comes_from_oid(entra_on, make_token):
    """Happy path: id is the Entra oid, name and email come from the token."""
    user = _user_for(make_token(oid="oid-1", sub="sub-1"))
    assert (user.id, user.name, user.email) == ("oid-1", "Ada Tester", "ada@example.com")


def test_user_falls_back_to_sub(entra_on, make_token):
    """Edge case: with no oid the sub claim is used."""
    assert _user_for(make_token(oid=None, sub="sub-9")).id == "sub-9"


def test_identity_headers_and_params_are_ignored(entra_on, make_token):
    """TC-SEC-081: X-User-Id, a query param and a form of impersonation must not change who the caller is."""
    mini = FastAPI()

    @mini.get("/whoami")
    async def whoami(user=Depends(deps.get_user)):
        return {"id": user.id}

    r = TestClient(mini).get(
        "/whoami?user_id=victim",
        headers={"Authorization": f"Bearer {make_token(oid='user-b')}", "X-User-Id": "victim", "X-Forwarded-User": "victim"},
    )
    assert r.json() == {"id": "user-b"}


# ---------------------------------------------------------------- sign-in switched off

def test_auth_off_everyone_is_local(monkeypatch):
    """Local development: no sign-in, one user called 'local'."""
    monkeypatch.setattr(deps, "AUTH_ENABLED", False)
    monkeypatch.setattr(deps, "USE_AWS_STORAGE", False)
    assert asyncio.run(deps.get_user(None)).id == "local"


def test_auth_off_with_aws_storage_fails_closed(monkeypatch):
    """TC-UP-025 / TC-SEC-012: shared storage with no sign-in would make everyone one user, so the server refuses (503)."""
    monkeypatch.setattr(deps, "AUTH_ENABLED", False)
    monkeypatch.setattr(deps, "USE_AWS_STORAGE", True)
    monkeypatch.setattr(deps, "ALLOW_ANON", False)
    with pytest.raises(HTTPException) as err:
        asyncio.run(deps.get_user(None))
    assert err.value.status_code == 503


def test_allow_anon_opens_it_up_on_purpose(monkeypatch):
    """TC-SEC-012: ALLOW_ANON=1 is the only way to run open with AWS storage. Production must not set it."""
    monkeypatch.setattr(deps, "AUTH_ENABLED", False)
    monkeypatch.setattr(deps, "USE_AWS_STORAGE", True)
    monkeypatch.setattr(deps, "ALLOW_ANON", True)
    assert asyncio.run(deps.get_user(None)).id == "local"


# ---------------------------------------------------------------- ownership (the other half of "who is calling")

class _FakeStore:
    def __init__(self, sessions):
        self.sessions = sessions

    def get(self, session_id):
        return self.sessions.get(session_id)

    def owner_of(self, session_id):
        s = self.sessions.get(session_id)
        return s.user_id if s else None


class _Session:
    def __init__(self, user_id):
        self.user_id = user_id


@pytest.fixture
def two_users_store(monkeypatch):
    monkeypatch.setattr(deps, "store", _FakeStore({"s-a": _Session("user-a")}))


def test_owner_gets_the_session(two_users_store):
    """Happy path: user A can open A's session."""
    assert deps.load_owned_session("s-a", deps.User(id="user-a")).user_id == "user-a"


def test_foreign_and_missing_sessions_look_identical(two_users_store):
    """Negative / IDOR: B asking for A's session gets the SAME 404 as a session that does not exist, so ids cannot be probed."""
    errors = []
    for sid in ("s-a", "does-not-exist"):
        with pytest.raises(HTTPException) as err:
            deps.load_owned_session(sid, deps.User(id="user-b"))
        errors.append((err.value.status_code, err.value.detail))
    assert errors[0] == errors[1] == (404, "Session not found")


def test_require_owned_blocks_foreign_session(two_users_store):
    """Negative: the planner/brief check (id only) is just as strict."""
    with pytest.raises(HTTPException) as err:
        deps.require_owned("s-a", deps.User(id="user-b"))
    assert err.value.status_code == 404
    deps.require_owned("s-a", deps.User(id="user-a"))  # the owner passes
