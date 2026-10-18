"""Sign-in, roles, per-domain groups and fail-closed configuration (Microsoft Entra ID)."""

from __future__ import annotations

import time
from collections.abc import Callable
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import ConfigError
from tests.conftest import wait_for_job

Headers = dict[str, str]
MakeHeaders = Callable[..., Headers]

CSV = "id,amount\n1,5\n2,6\n"


@pytest.fixture
def make_headers(monkeypatch: pytest.MonkeyPatch) -> MakeHeaders:
    """Issue tokens signed with a throw-away key that the validator is told to trust."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    monkeypatch.setattr(
        jwt.PyJWKClient, "get_signing_key_from_jwt", lambda self, token: SimpleNamespace(key=private.public_key())
    )

    def make(**overrides: object) -> Headers:
        claims: dict[str, object] = {
            "iss": "https://login.microsoftonline.com/tenant-1/v2.0",
            "aud": "client-1",
            "exp": int(time.time()) + 600,
            "oid": "user-1",
            "scp": "access_as_user",
            "roles": ["AI4BI.User"],
            "groups": [],
            **overrides,
        }
        return {"Authorization": "Bearer " + jwt.encode(claims, pem, algorithm="RS256")}

    return make


@pytest.fixture
def secured(monkeypatch: pytest.MonkeyPatch, make_client: Callable[[], TestClient]) -> TestClient:
    monkeypatch.setenv("ENTRA_TENANT_ID", "tenant-1")
    monkeypatch.setenv("ENTRA_CLIENT_ID", "client-1")
    monkeypatch.setenv("DOMAIN_GROUPS", '{"service_ops": ["group-ops"]}')
    return make_client()


def test_authentication(secured: TestClient, make_headers: MakeHeaders) -> None:
    assert secured.get("/health").status_code == 200  # the load balancer's probe stays public
    assert secured.get("/api/info").status_code == 401
    garbage = secured.get("/api/info", headers={"Authorization": "Bearer garbage"})
    assert (garbage.status_code, garbage.json()["error"]["code"]) == (401, "unauthenticated")
    assert secured.get("/api/info", headers=make_headers()).status_code == 200


@pytest.mark.parametrize(
    "claims",
    [
        {"exp": int(time.time()) - 3600},
        {"aud": "someone-else"},
        {"iss": "https://evil.example/"},
        {"scp": "other_scope"},
    ],
    ids=["expired", "wrong-audience", "wrong-issuer", "missing-scope"],
)
def test_bad_tokens_are_rejected(secured: TestClient, make_headers: MakeHeaders, claims: dict) -> None:
    assert secured.get("/api/info", headers=make_headers(**claims)).status_code == 401


def test_unsigned_token_is_rejected(secured: TestClient, make_headers: MakeHeaders) -> None:
    unsigned = jwt.encode({"aud": "client-1", "exp": int(time.time()) + 60}, key=None, algorithm="none")
    assert secured.get("/api/info", headers={"Authorization": f"Bearer {unsigned}"}).status_code == 401


def test_a_signed_in_user_without_a_role_is_forbidden(secured: TestClient, make_headers: MakeHeaders) -> None:
    response = secured.get("/api/info", headers=make_headers(roles=[]))
    assert (response.status_code, response.json()["error"]["code"]) == (403, "forbidden")


def test_domain_groups(secured: TestClient, make_headers: MakeHeaders) -> None:
    body = {"question": "What is EMEA FRT?", "domain": "service_ops"}
    assert secured.post("/api/ask", json=body, headers=make_headers()).status_code == 403
    member = make_headers(groups=["group-ops"])
    assert secured.post("/api/ask", json=body, headers=member).json()["status"] == "success"

    open_domain = {"question": "total productivity", "domain": "generic_cube"}
    assert secured.post("/api/ask", json=open_domain, headers=make_headers()).status_code == 200
    assert "service_ops" not in {d["id"] for d in secured.get("/api/domains", headers=make_headers()).json()}
    assert "service_ops" in {d["id"] for d in secured.get("/api/domains", headers=member).json()}


def test_stewardship_needs_the_steward_role(secured: TestClient, make_headers: MakeHeaders) -> None:
    upload = {"file": ("t.csv", CSV, "text/csv")}
    assert secured.post("/api/domains/demo/datasets", files=upload, headers=make_headers()).status_code == 403
    steward = make_headers(roles=["AI4BI.Steward"], oid="steward-1")
    assert secured.post("/api/domains/demo/datasets", files=upload, headers=steward).status_code == 201
    assert secured.get("/api/domains/demo/registry", headers=make_headers()).status_code == 403


def test_jobs_are_visible_to_their_owner_and_stewards_only(secured: TestClient, make_headers: MakeHeaders) -> None:
    owner = make_headers(roles=["AI4BI.Steward"], oid="steward-1")
    secured.post("/api/domains/demo/datasets", files={"file": ("t.csv", CSV, "text/csv")}, headers=owner)
    job_id = secured.post("/api/domains/demo/onboard", json={}, headers=owner).json()["job_id"]
    wait_for_job(secured, job_id, owner)

    assert secured.get(f"/api/jobs/{job_id}", headers=make_headers(oid="user-2")).status_code == 403
    other_steward = make_headers(roles=["AI4BI.Steward"], oid="steward-2")
    assert secured.get(f"/api/jobs/{job_id}", headers=other_steward).status_code == 200


def test_sessions_are_private_per_user(secured: TestClient, make_headers: MakeHeaders) -> None:
    from app.services.context import get_context

    body = {"question": "What is productivity for csa?", "domain": "generic_cube", "session_id": "shared-id"}
    secured.post("/api/ask", json=body, headers=make_headers(oid="user-1"))
    history = get_context().history
    assert history.recent("generic_cube", "user-1:shared-id", 5)
    assert history.recent("generic_cube", "user-2:shared-id", 5) == []


class TestFailClosedConfiguration:
    base = {"data_dir": ".", "prompts_dir": ".", "visual_templates_path": "."}
    aws = {"s3_bucket": "b", "ddb_registry": "r", "ddb_kg": "k", "ddb_history": "h", "ddb_jobs": "j", "ddb_audit": "a"}

    def settings(self, **overrides: object) -> Settings:
        return Settings(**{**self.base, **overrides})  # type: ignore[arg-type]

    def test_aws_storage_without_sign_in_refuses_to_start(self) -> None:
        with pytest.raises(ConfigError, match="sign-in"):
            self.settings(**self.aws).validate()

    def test_explicit_opt_outs_and_real_sign_in_start(self) -> None:
        self.settings(**self.aws, allow_anon=True).validate()
        self.settings(**self.aws, entra_tenant_id="t", entra_client_id="c").validate()

    def test_partly_configured_aws_is_refused(self) -> None:
        with pytest.raises(ConfigError, match="DDB_KG"):
            self.settings(**{**self.aws, "ddb_kg": ""}, entra_tenant_id="t", entra_client_id="c").validate()

    def test_half_configured_entra_is_refused(self) -> None:
        with pytest.raises(ConfigError, match="ENTRA_TENANT_ID"):
            self.settings(entra_tenant_id="t").validate()

    def test_bedrock_needs_a_model(self) -> None:
        with pytest.raises(ConfigError, match="BEDROCK_DEFAULT_MODEL"):
            self.settings(llm_mode="bedrock").validate()

    def test_local_defaults_start(self) -> None:
        self.settings().validate()
