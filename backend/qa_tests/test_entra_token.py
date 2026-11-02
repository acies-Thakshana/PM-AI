"""Unit tests of deps.validate_token (Microsoft Entra ID access tokens).

Each test names the workbook case it covers (docs/PM-AI_Test_Cases_API_Sections.xlsx).
The Microsoft signing keys are faked in conftest.py, so there is no network.
"""
import base64
import hashlib
import hmac
import json
import time

import jwt
import pytest
from fastapi import HTTPException

from app.routers import deps
from conftest import CLIENT, ISSUER_V1, ISSUER_V2


def _rejects(token, status, detail):
    with pytest.raises(HTTPException) as err:
        deps.validate_token(token)
    assert err.value.status_code == status
    assert err.value.detail == detail
    return err.value


# ---------------------------------------------------------------- happy path

def test_valid_token_returns_claims(entra_on, make_token):
    """Happy path: a correctly signed token for this API is accepted."""
    claims = deps.validate_token(make_token())
    assert claims["oid"] == "user-a"
    assert claims["aud"] == CLIENT


@pytest.mark.parametrize("aud", [CLIENT, f"api://{CLIENT}"])
def test_both_audience_forms_are_accepted(entra_on, make_token, aud):
    """Happy path: token version 2 (client id) and version 1 (api://client id) audiences both work."""
    assert deps.validate_token(make_token(aud=aud))["aud"] == aud


@pytest.mark.parametrize("iss", [ISSUER_V2, ISSUER_V1])
def test_both_issuer_forms_are_accepted(entra_on, make_token, iss):
    """Happy path: login.microsoftonline.com/<tenant>/v2.0 and sts.windows.net/<tenant>/ are this tenant."""
    assert deps.validate_token(make_token(iss=iss))["iss"] == iss


# ---------------------------------------------------------------- TC-SEC-003..008: bad tokens

def test_tampered_payload_is_rejected(entra_on, make_token):
    """TC-SEC-003: change the payload but keep the old signature."""
    header, _payload, signature = make_token().split(".")
    forged = base64.urlsafe_b64encode(
        json.dumps({"aud": CLIENT, "iss": ISSUER_V2, "exp": int(time.time()) + 3600, "oid": "admin", "scp": "access_as_user"}).encode()
    ).rstrip(b"=").decode()
    _rejects(f"{header}.{forged}.{signature}", 401, "Invalid token")


def test_token_signed_by_another_key_is_rejected(entra_on, make_token, other_key):
    """TC-SEC-003: a token that is well formed but signed with a key Microsoft did not publish."""
    _rejects(make_token(key=other_key[0]), 401, "Invalid token")


def test_alg_none_is_rejected(entra_on, make_token):
    """TC-SEC-004: an unsigned token (alg = none) must never be accepted."""
    unsigned = jwt.encode(
        {"aud": CLIENT, "iss": ISSUER_V2, "exp": int(time.time()) + 3600, "oid": "x", "scp": "access_as_user"},
        key=None,
        algorithm="none",
    )
    _rejects(unsigned, 401, "Invalid token")


def test_hs256_signed_with_public_key_is_rejected(entra_on, tenant_key):
    """TC-SEC-005: algorithm confusion. The attacker signs HS256 using the PUBLIC key as the secret.
    PyJWT refuses to build this token, so it is assembled by hand."""
    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps({"aud": CLIENT, "iss": ISSUER_V2, "exp": int(time.time()) + 3600, "oid": "x", "scp": "access_as_user"}).encode())
    sig = b64(hmac.new(tenant_key[1], f"{head}.{body}".encode(), hashlib.sha256).digest())
    _rejects(f"{head}.{body}.{sig}", 401, "Invalid token")


def test_wrong_audience_is_rejected(entra_on, make_token):
    """TC-SEC-006: validly signed, but meant for another application."""
    _rejects(make_token(aud="api://some-other-app"), 401, "Invalid token")


def test_wrong_tenant_issuer_is_rejected(entra_on, make_token):
    """TC-SEC-007: validly signed, but issued by a different tenant."""
    _rejects(make_token(iss="https://login.microsoftonline.com/99999999-0000-0000-0000-000000000000/v2.0"), 401, "Invalid token")


@pytest.mark.parametrize("missing", ["exp", "iss", "aud"])
def test_required_claims_must_be_present(entra_on, make_token, missing):
    """TC-SEC-008: exp, iss and aud are required; a token without one is rejected."""
    _rejects(make_token(**{missing: None}), 401, "Invalid token")


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "....", " "])
def test_garbage_is_rejected_not_a_500(entra_on, garbage):
    """Negative: nonsense in the token slot gives a clean 401, never a crash."""
    _rejects(garbage, 401, "Invalid token")


# ---------------------------------------------------------------- TC-SEC-072 / 076: time

def test_expired_token_is_rejected_with_its_own_message(entra_on, make_token):
    """TC-SEC-072: replaying an old token gives 'Token expired'."""
    _rejects(make_token(exp=int(time.time()) - 5), 401, "Token expired")


def test_expiry_boundary(entra_on, make_token):
    """Boundary: one second in the past is rejected, one minute ahead is accepted."""
    _rejects(make_token(exp=int(time.time()) - 1), 401, "Token expired")
    assert deps.validate_token(make_token(exp=int(time.time()) + 60))["oid"] == "user-a"


def test_not_before_in_the_future_is_rejected(entra_on, make_token):
    """TC-SEC-076: nbf one hour ahead means the token is not valid yet."""
    _rejects(make_token(nbf=int(time.time()) + 3600), 401, "Invalid token")


# ---------------------------------------------------------------- TC-UP-024: scope

def test_missing_scope_is_403(entra_on, make_token):
    """TC-UP-024: signed and in date, but not allowed to use this API (403, not 401)."""
    _rejects(make_token(scp="User.Read"), 403, "Token is not authorised for this API")


def test_app_only_token_without_scp_is_403(entra_on, make_token):
    """TC-UP-024: client-credential tokens carry no scp and are refused."""
    _rejects(make_token(scp=None), 403, "Token is not authorised for this API")


def test_scope_among_several_is_accepted(entra_on, make_token):
    """Happy path: the scope is found even when the token carries others."""
    assert deps.validate_token(make_token(scp="User.Read access_as_user openid"))


def test_scope_must_match_exactly(entra_on, make_token):
    """Negative: 'access_as_user_admin' is not 'access_as_user'."""
    _rejects(make_token(scp="access_as_user_admin"), 403, "Token is not authorised for this API")


# ---------------------------------------------------------------- TC-SEC-010: Microsoft unreachable

def test_unreachable_signing_keys_is_503_not_401(entra_on, monkeypatch, make_token):
    """TC-SEC-010 (error handling): when the key fetch fails it is OUR outage: 503, and the token is never accepted."""

    class Down:
        def get_signing_key_from_jwt(self, token):
            raise jwt.PyJWKClientConnectionError("network is down")

    monkeypatch.setattr(deps, "_jwk_client", Down())
    _rejects(make_token(), 503, "Sign-in service unavailable")
