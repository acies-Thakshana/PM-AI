from __future__ import annotations

import json

import pandas as pd

from ai4bi.semantic.onboarding import inferred_restricted_columns, onboard_domain
from ai4bi.semantic.registry import JsonSemanticRegistryStore, SemanticRegistry, schema_fingerprint
from ai4bi.sql.local_planner import LocalPlanner


class SemanticLlm:
    name = "semantic-test"

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def complete(self, system_instruction: str, user_prompt: str) -> str:
        self.calls.append(user_prompt)
        return json.dumps(self.payload)


def _frames():
    return {
        "orders": pd.DataFrame(
            {
                "order_id": ["O1", "O2", "O3"],
                "customer_id": ["C1", "C1", "C2"],
                "revenue": [10.0, 15.0, 20.0],
                "contact_email": ["a@example.com", "a@example.com", "b@example.com"],
            }
        ),
        "customers": pd.DataFrame(
            {"customer_id": ["C1", "C2"], "segment": ["Enterprise", "SMB"]}
        ),
    }


def _payload():
    return {
        "columns": [
            {"dataset": "orders", "name": "revenue", "role": "measure", "description": "Booked revenue."}
        ],
        "metrics": [
            {
                "id": "metric.sales.revenue",
                "family": "revenue",
                "name": "Revenue",
                "scope": "global",
                "default_for_family": True,
                "version": "1",
                "status": "proposed",
                "data_product_id": "dp.sales.orders",
                "grain": "one order",
                "aggregation": "sum",
                "sql_expression": 'SUM("revenue")',
                "compute": {"column": "revenue", "aggregation": "sum"},
                "synonyms": ["sales"],
                "unit": "USD",
                "confidence": 0.95,
            }
        ],
        "joins": [
            {
                "id": "join.sales.orders_customers",
                "left_dataset": "orders",
                "right_dataset": "customers",
                "left_column": "customer_id",
                "right_column": "customer_id",
                "join_type": "left",
                "cardinality": "many_to_one",
                "confidence": 0.96,
                "description": "Each order belongs to a customer.",
            }
        ],
        "glossary": [
            {
                "term": "sales",
                "kind": "synonym",
                "maps_to_kind": "metric_family",
                "maps_to_id": "revenue",
                "confidence": 0.9,
            }
        ],
        "rules": [],
    }


def test_fingerprint_is_stable_and_changes_with_schema():
    frames = _frames()
    assert schema_fingerprint(frames) == schema_fingerprint(dict(reversed(list(frames.items()))))
    changed = {**frames, "orders": frames["orders"].assign(new_column=1)}
    assert schema_fingerprint(frames) != schema_fingerprint(changed)


def test_pii_is_detected_before_prompt():
    assert "contact_email" in inferred_restricted_columns(_frames())


def test_llm_semantics_are_validated_and_activated(settings):
    llm = SemanticLlm(_payload())
    result = onboard_domain("sales", _frames(), llm=llm, settings=settings)
    assert result.changed
    assert result.package.entity_for_dataset("orders").columns[2].description == "Booked revenue."
    metric = next(m for m in result.package.metrics if m.id == "metric.sales.revenue")
    assert metric.status == "certified"
    assert next(j for j in result.package.joins if j.id == "join.sales.orders_customers").allowed_for_nlq
    assert "contact_email" in result.package.restricted_columns()
    email = next(
        c
        for dataset in result.metadata["datasets"]
        for c in dataset["columns"]
        if c["name"] == "contact_email"
    )
    assert email["sample_values"] == []
    assert "a@example.com" not in llm.calls[0]


def test_learned_metric_formula_is_used_by_the_planner(settings):
    result = onboard_domain("sales", _frames(), llm=SemanticLlm(_payload()), settings=settings)
    from ai4bi.semantic.store import SemanticStore

    _, sql = LocalPlanner(SemanticStore(settings.semantic_root)).draft(
        "What is total sales?", result.package, _frames()
    )
    assert "SUM(revenue) AS revenue" in sql["sql_query"]


def test_same_fingerprint_does_not_call_llm_twice(settings):
    llm = SemanticLlm(_payload())
    first = onboard_domain("sales", _frames(), llm=llm, settings=settings)
    second = onboard_domain("sales", _frames(), llm=llm, settings=settings, registry=first.registry)
    assert not second.changed
    assert len(llm.calls) == 1


def test_unsafe_or_low_confidence_artifacts_remain_drafts(settings):
    payload = _payload()
    payload["metrics"][0]["sql_expression"] = "SUM(revenue); DROP TABLE orders"
    payload["joins"][0]["confidence"] = 0.1
    result = onboard_domain("sales", _frames(), llm=SemanticLlm(payload), settings=settings)
    latest = result.registry.latest("sales", include_drafts=True)
    metric = next(a for a in latest if a.artifact_type == "metric")
    join = next(a for a in latest if a.artifact_type == "join")
    assert metric.status == "draft"
    assert join.status == "draft"
    assert not result.package.metrics
    assert not result.package.joins


def test_registry_overlay_precedence_and_draft_control(settings):
    first = onboard_domain("sales", _frames(), llm=SemanticLlm(_payload()), settings=settings)
    active = next(a for a in first.registry.latest("sales") if a.artifact_type == "metric")
    replacement = active.model_copy(
        update={
            "semantic_version": "v2",
            "created_at": "9999-01-01T00:00:00+00:00",
            "status": "draft",
            "payload": {**active.payload, "name": "Draft Revenue"},
        }
    )
    first.registry.append(replacement)
    base = onboard_domain(
        "sales", _frames(), llm=SemanticLlm(_payload()), settings=settings, registry=SemanticRegistry(), force=True
    ).package
    assert all(m.name != "Draft Revenue" for m in first.registry.overlay(base).metrics)
    assert any(m.name == "Draft Revenue" for m in first.registry.overlay(base, include_drafts=True).metrics)


def test_json_registry_store_round_trip(tmp_path, settings):
    result = onboard_domain("sales", _frames(), llm=SemanticLlm(_payload()), settings=settings)
    store = JsonSemanticRegistryStore(tmp_path)
    path = store.save("sales", result.registry)
    assert path.exists()
    assert len(store.load("sales").artifacts) == len(result.registry.artifacts)
