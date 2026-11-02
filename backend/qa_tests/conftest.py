"""Shared fixtures for the QA tests.

Nothing here touches the application code. Everything the app would get from outside
(Microsoft's signing keys, AWS) is replaced by a fake for the length of one test.

Run from the backend folder:   python -m pytest qa_tests -v
"""
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.routers import deps  # noqa: E402  (needs the path above)

TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ISSUER_V2 = f"https://login.microsoftonline.com/{TENANT}/v2.0"
ISSUER_V1 = f"https://sts.windows.net/{TENANT}/"


def _new_key():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private_pem, public_pem


@pytest.fixture(scope="session")
def tenant_key():
    """The key pair 'Microsoft' signs with in these tests (made once, it is slow to generate)."""
    return _new_key()


@pytest.fixture(scope="session")
def other_key():
    """A different key pair, for tokens that were not signed by the tenant."""
    return _new_key()


class FakeJwks:
    """Stands in for jwt.PyJWKClient, so no request goes to login.microsoftonline.com."""

    def __init__(self, public_pem):
        self.public_pem = public_pem

    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=self.public_pem)


@pytest.fixture
def entra_on(monkeypatch, tenant_key):
    """Sign-in switched ON for this test, with the tenant's public key as the 'Microsoft' key."""
    monkeypatch.setattr(deps, "AUTH_ENABLED", True)
    monkeypatch.setattr(deps, "ENTRA_TENANT_ID", TENANT)
    monkeypatch.setattr(deps, "ENTRA_CLIENT_ID", CLIENT)
    monkeypatch.setattr(deps, "ENTRA_REQUIRED_SCOPE", "access_as_user")
    monkeypatch.setattr(deps, "_jwk_client", FakeJwks(tenant_key[1]))


@pytest.fixture
def make_token(tenant_key):
    """make_token(**overrides) -> a signed access token.

    A claim set to None is left out. Use key= / algorithm= to sign differently.
    """

    def _make(key=None, algorithm="RS256", **overrides):
        now = int(time.time())
        claims = {
            "aud": CLIENT,
            "iss": ISSUER_V2,
            "iat": now,
            "exp": now + 3600,
            "scp": "access_as_user",
            "oid": "user-a",
            "name": "Ada Tester",
            "preferred_username": "ada@example.com",
        }
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, key or tenant_key[0], algorithm=algorithm)

    return _make
