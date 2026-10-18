"""HTTP API in local mode: reading, uploading, onboarding, stewardship, batch and error handling."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import wait_for_job

ORDERS_CSV = (
    "order_id,region,amount,customer_email\n"
    "1,north,10.5,a@example.com\n2,north,20,b@example.com\n3,south,5,c@example.com\n4,south,7.5,d@example.com\n"
)
QUESTIONS_CSV = "question,Expected_SQL_Query\nWhat is EMEA FRT?,\nWhat is APAC FRT?,\n"


def upload_orders(client: TestClient) -> None:
    response = client.post("/api/domains/shop/datasets", files={"file": ("Orders.CSV", ORDERS_CSV, "text/csv")})
    assert response.status_code == 201
    assert response.json() == {
        "table": "Orders",
        "filename": "Orders.csv",
        "rows": 4,
        "columns": ["order_id", "region", "amount", "customer_email"],
    }


def onboard(client: TestClient, domain: str = "shop") -> dict:
    response = client.post(f"/api/domains/{domain}/onboard", json={})
    assert response.status_code == 202
    status = wait_for_job(client, response.json()["job_id"])
    assert status["status"] == "succeeded", status
    return status["result"]


def test_health_and_request_id(client: TestClient) -> None:
    response = client.get("/health")
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]
    assert client.get("/health", headers={"X-Request-ID": "trace-12345678"}).headers["x-request-id"] == "trace-12345678"


def test_domains_and_detail(client: TestClient) -> None:
    ids = {domain["id"] for domain in client.get("/api/domains").json()}
    assert {"service_ops", "generic_cube"} <= ids
    detail = client.get("/api/domains/service_ops").json()
    assert detail["counts"]["metrics"] > 0
    flagged = {c["name"] for table in detail["tables"] for c in table["columns"] if c["restricted"]}
    assert flagged, "restricted columns must be marked"
    assert all(check["ok"] for check in client.get("/api/domains/service_ops/checks").json())


def test_ask_and_error_envelopes(client: TestClient) -> None:
    ok = client.post("/api/ask", json={"question": "What is EMEA FRT?", "domain": "service_ops"})
    assert ok.status_code == 200
    assert ok.json()["status"] == "success"

    unknown = client.post("/api/ask", json={"question": "anything at all", "domain": "ghost"})
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "domain_not_found"

    assert client.post("/api/ask", json={"question": "x", "domain": "../etc"}).status_code == 422
    invalid = client.post("/api/ask", json={})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_request"


def test_upload_validation(client: TestClient) -> None:
    for name, content in (("evil.exe", b"MZ"), ("empty.csv", b"")):
        response = client.post("/api/domains/shop/datasets", files={"file": (name, content, "text/csv")})
        assert response.status_code == 422, name
    target = client.post("/api/domains/shop/uploads", json={"filename": "Orders.CSV"}).json()
    assert (target["mode"], target["table"]) == ("direct", "Orders")


def test_upload_onboard_and_ask_a_new_domain(client: TestClient) -> None:
    upload_orders(client)
    assert client.get("/api/domains/shop/datasets").json() == ["Orders"]

    result = onboard(client)
    assert result["provider"] == "local_fallback"  # no model configured: the registry must not say "llm"
    assert result["changed"] is True
    assert result["artifacts_written"] > 0

    repeated = onboard(client)
    assert (repeated["changed"], repeated["artifacts_written"]) == (False, 0)

    catalog = client.get("/api/domains/shop/catalog").json()
    email = next(c for t in catalog["datasets"] for c in t["columns"] if c["name"] == "customer_email")
    assert email["restricted"] and email["sample_values"] == []

    registry = client.get("/api/domains/shop/registry").json()
    assert registry
    assert "llm" not in {artifact["source"] for artifact in registry}

    answer = client.post("/api/ask", json={"question": "total amount by region", "domain": "shop"}).json()
    assert answer["status"] == "success"
    assert {row["region"] for row in answer["table"]["rows"]} == {"north", "south"}
    leak = client.post("/api/ask", json={"question": "show customer_email", "domain": "shop"})
    assert "example.com" not in leak.text


def test_stewardship_actions(client: TestClient) -> None:
    upload_orders(client)
    onboard(client)
    metric = next(a for a in client.get("/api/domains/shop/registry").json() if a["artifact_type"] == "metric")
    ref = {"artifact_type": "metric", "artifact_id": metric["artifact_id"]}

    deprecated = client.post("/api/domains/shop/registry/deprecate", json=ref).json()
    assert (deprecated["status"], deprecated["source"]) == ("deprecated", "manual")
    approved = client.post("/api/domains/shop/registry/approve", json=ref).json()
    assert approved["status"] == "active"
    assert approved["payload"]["status"] == "certified"
    assert client.post("/api/domains/shop/registry/approve", json={**ref, "artifact_id": "nope"}).status_code == 404

    term = {"term": "revenue", "kind": "synonym", "maps_to_kind": "metric_family", "maps_to_id": "amount"}
    assert client.post("/api/domains/shop/registry/glossary", json=term).status_code == 201
    assert client.post("/api/domains/shop/registry/glossary", json=term).status_code == 409

    query = {
        "id": "vs.total",
        "question": "total amount",
        "sql": 'SELECT SUM("amount") AS total FROM "Orders"',
        "expected_result": "43",
    }
    assert client.post("/api/domains/shop/registry/validated-sql", json=query).status_code == 201
    rejected = {**query, "id": "vs.bad", "sql": 'SELECT customer_email FROM "Orders"'}
    assert client.post("/api/domains/shop/registry/validated-sql", json=rejected).status_code == 422
    checks = client.get("/api/domains/shop/checks").json()
    assert any(c["name"] == "validated_sql:vs.total" and c["ok"] for c in checks)


def test_batch_and_evaluate(client: TestClient) -> None:
    files = {"file": ("questions.csv", QUESTIONS_CSV, "text/csv")}
    batch = client.post("/api/domains/service_ops/batch", files=files)
    assert batch.status_code == 200
    assert batch.json()["questions"] == 2
    evaluate = client.post("/api/domains/service_ops/evaluate", files=files)
    assert evaluate.status_code == 200
    assert "accuracy" in evaluate.json()["summary"]


def test_batch_size_is_capped(client: TestClient) -> None:
    rows = "\n".join("What is EMEA FRT?" for _ in range(51))
    response = client.post("/api/domains/service_ops/batch", files={"file": ("q.csv", "question\n" + rows, "text/csv")})
    assert response.status_code == 422


def test_unknown_job_is_404(client: TestClient) -> None:
    assert client.get("/api/jobs/doesnotexist").status_code == 404
