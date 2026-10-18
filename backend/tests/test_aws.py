"""The AWS path: S3 + DynamoDB through moto, and a fake Bedrock that answers the way a model would.

Only Bedrock itself is faked. Everything else (presigned upload, DynamoDB items, S3 objects) is
exercised for real against moto.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import boto3
import pytest
import requests
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from moto import mock_aws

from app.config import Settings, get_settings
from app.services.common import aws_clients
from app.services.common.dynamo_tables import create_tables, table_specs
from app.services.context import get_context
from tests.conftest import wait_for_job

REGION = "us-east-1"
ORDERS_CSV = (
    "order_id,region,amount,customer_email\n"
    "1,north,10.5,a@x.com\n2,north,20,b@x.com\n3,south,5,c@x.com\n4,south,7.5,d@x.com\n"
)
SQL = 'SELECT region, SUM(amount) AS total FROM "Orders" GROUP BY region'


class FakeBedrock:
    """Returns a plausible reply for each of the five calls and remembers what it was asked."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.junk = False
        self.reject_temperature = False

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        system = kwargs["system"][0]["text"]
        inference = kwargs["inferenceConfig"]
        self.calls.append({"model": kwargs["modelId"], "temperature": "temperature" in inference})
        if self.reject_temperature and "temperature" in inference:
            error = {"Code": "ValidationException", "Message": "temperature is not supported for this model"}
            raise ClientError({"Error": error}, "Converse")
        return {
            "output": {"message": {"content": [{"text": self._text(system)}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 100, "outputTokens": 20},
        }

    def _text(self, system: str) -> str:
        if self.junk:
            return "I am sorry, I cannot help with that."
        if system.startswith("You are the AI4BI planner"):
            return json.dumps(
                {
                    "intent": "aggregate",
                    "interpreted_question": "total amount by region",
                    "metrics": [{"name": "amount"}],
                    "dimensions": ["region"],
                    "filters": {},
                    "calculations": [],
                    "new_terms": [],
                    "confidence": 0.9,
                    "clarification_question": "",
                }
            )
        if system.startswith("You write SQLite"):
            return json.dumps({"sql_query": SQL, "datasets_used": ["Orders"], "columns_used": [], "rationale": "sum"})
        if system.startswith("You are a BI analyst"):
            return json.dumps({"answer": "north is 30.50 and south is 12.50.", "key_findings": ["north 30.5"]})
        return json.dumps(
            {
                "metrics": [
                    {
                        "id": "metric.shop.revenue",
                        "family": "revenue",
                        "name": "Revenue",
                        "data_product_id": "dp.shop.Orders",
                        "grain": "order",
                        "aggregation": "sum",
                        "sql_expression": 'SUM("amount")',
                        "unit": "USD",
                        "synonyms": ["sales"],
                        "confidence": 0.95,
                    }
                ],
                "joins": [],
                "glossary": [],
                "rules": [],
                "columns": [],
            }
        )


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeBedrock]:
    for name, value in {
        "AWS_REGION": REGION,
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "S3_BUCKET": "ai4bi-test",
        "DDB_REGISTRY": "t-registry",
        "DDB_KG": "t-kg",
        "DDB_HISTORY": "t-history",
        "DDB_JOBS": "t-jobs",
        "DDB_AUDIT": "t-audit",
        "ALLOW_ANON": "1",
        "BEDROCK_DEFAULT_MODEL": "fake.model-v1",
        "BEDROCK_STRONG_MODEL": "fake.strong-v1",
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    get_context.cache_clear()
    with mock_aws():
        settings: Settings = get_settings()
        boto3.client("s3", region_name=REGION).create_bucket(Bucket=settings.s3_bucket)
        create_tables(boto3.client("dynamodb", region_name=REGION), table_specs(settings))
        bedrock = FakeBedrock()
        monkeypatch.setattr(aws_clients, "bedrock_runtime", lambda: bedrock)
        yield bedrock


def item_count(table: str) -> int:
    return boto3.client("dynamodb", region_name=REGION).scan(TableName=table, Select="COUNT")["Count"]


def upload_orders(client: TestClient) -> None:
    target = client.post("/api/domains/shop/uploads", json={"filename": "Orders.csv"}).json()
    assert target["mode"] == "presigned"
    posted = requests.post(target["url"], data=target["fields"], files={"file": ("Orders.csv", ORDERS_CSV)})
    assert posted.status_code in (200, 201, 204)
    completed = client.post("/api/domains/shop/uploads/complete", json={"filename": "Orders.csv"})
    assert completed.status_code == 200
    assert completed.json()["rows"] == 4


def test_presigned_upload_lands_in_s3(aws: FakeBedrock, client: TestClient) -> None:
    assert client.get("/docs").status_code == 404  # interactive docs are off on AWS
    upload_orders(client)
    keys = [o["Key"] for o in boto3.client("s3", region_name=REGION).list_objects_v2(Bucket="ai4bi-test")["Contents"]]
    assert "datasets/shop/Orders.csv" in keys
    assert client.post("/api/domains/shop/uploads/complete", json={"filename": "Missing.csv"}).status_code == 404
    domains = {d["id"] for d in client.get("/api/domains").json()}
    assert {"shop", "service_ops"} <= domains  # uploaded data plus the bundled samples


def test_onboarding_and_questions_use_the_model_and_persist_to_dynamodb(aws: FakeBedrock, client: TestClient) -> None:
    upload_orders(client)
    job = client.post("/api/domains/shop/onboard", json={}).json()
    result = wait_for_job(client, job["job_id"])["result"]
    assert result["provider"] == "bedrock"
    assert result["metrics"]["active"] == 1
    assert item_count("t-registry") >= 3
    assert item_count("t-jobs") == 1
    assert client.get("/api/domains/shop/catalog").json()["domain"] == "shop"
    registry = client.get("/api/domains/shop/registry").json()
    assert any(a["source"] == "llm" and a["artifact_type"] == "metric" for a in registry)
    assert any(call["model"] == "fake.strong-v1" for call in aws.calls)  # onboarding uses the strong tier

    aws.calls.clear()
    answer = client.post(
        "/api/ask", json={"question": "total amount by region", "domain": "shop", "session_id": "s"}
    ).json()
    assert answer["status"] == "success"
    assert answer["answer_path"] == "llm"
    assert answer["confidence"] == 0.9
    assert answer["answer"].startswith("north is 30.50")
    assert not any(w.startswith("llm_fallback") for w in answer["warnings"])
    assert {call["model"] for call in aws.calls} == {"fake.strong-v1", "fake.model-v1"}  # plan/sql strong, answer cheap
    assert item_count("t-kg") > 5
    assert item_count("t-history") == 1
    assert item_count("t-audit") >= 5  # per-call token usage plus the ask itself


def test_a_second_instance_sees_the_same_state(aws: FakeBedrock, make_client: Callable[[], TestClient]) -> None:
    first = make_client()
    upload_orders(first)
    wait_for_job(first, first.post("/api/domains/shop/onboard", json={}).json()["job_id"])
    body = {"question": "total amount by region", "domain": "shop", "session_id": "s"}
    assert first.post("/api/ask", json=body).json()["status"] == "success"

    get_context.cache_clear()  # a different task: new process memory, same S3 and DynamoDB
    second = make_client()
    assert second.post("/api/ask", json=body).json()["status"] == "success"
    context = get_context()
    assert context.graphs.load("shop").stats()["episodes"] == 2
    assert len(context.history.recent("shop", "anonymous:s", 5)) == 2


def test_an_unusable_model_reply_falls_back_and_says_so(aws: FakeBedrock, client: TestClient) -> None:
    upload_orders(client)
    wait_for_job(client, client.post("/api/domains/shop/onboard", json={}).json()["job_id"])
    aws.junk = True
    answer = client.post("/api/ask", json={"question": "total amount by region", "domain": "shop"}).json()
    assert answer["status"] == "success"
    assert answer["answer_path"] == "deterministic"
    assert answer["confidence"] is None
    assert any(w.startswith("llm_fallback_used") for w in answer["warnings"])


def test_models_that_reject_temperature_are_retried_without_it(aws: FakeBedrock, client: TestClient) -> None:
    upload_orders(client)
    wait_for_job(client, client.post("/api/domains/shop/onboard", json={}).json()["job_id"])
    aws.reject_temperature = True
    aws.calls.clear()
    answer = client.post("/api/ask", json={"question": "total amount by region", "domain": "shop"}).json()
    assert answer["answer_path"] == "llm"
    assert any(not call["temperature"] for call in aws.calls)


def test_bundled_samples_still_work_on_aws(aws: FakeBedrock, client: TestClient) -> None:
    response = client.post("/api/ask", json={"question": "What is EMEA FRT?", "domain": "service_ops"})
    assert response.json()["status"] == "success"
