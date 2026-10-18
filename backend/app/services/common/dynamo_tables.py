"""The DynamoDB tables the service expects: one definition used by the setup script and by tests.

All tables are on-demand (pay per request). Infrastructure-as-code should create the same keys,
the ``expires_at`` TTL attribute, and the ``by_user`` index on the audit table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings


@dataclass(frozen=True)
class TableSpec:
    name: str
    hash_key: str
    range_key: str | None = None
    ttl_attribute: str | None = "expires_at"
    user_index: bool = False  # the audit table is also queried by user


def table_specs(settings: Settings) -> list[TableSpec]:
    return [
        TableSpec(settings.ddb_registry, "domain", "sort_key", ttl_attribute=None),
        TableSpec(settings.ddb_kg, "domain", "sort_key"),
        TableSpec(settings.ddb_history, "session_key", "sort_key"),
        TableSpec(settings.ddb_jobs, "job_id"),
        TableSpec(settings.ddb_audit, "session_id", "ts_event", user_index=True),
    ]


def _definition(spec: TableSpec) -> dict[str, Any]:
    attributes = [spec.hash_key] + ([spec.range_key] if spec.range_key else [])
    key_schema = [{"AttributeName": spec.hash_key, "KeyType": "HASH"}]
    if spec.range_key:
        key_schema.append({"AttributeName": spec.range_key, "KeyType": "RANGE"})
    definition: dict[str, Any] = {
        "TableName": spec.name,
        "BillingMode": "PAY_PER_REQUEST",
        "KeySchema": key_schema,
    }
    if spec.user_index:
        attributes.append("user_id")
        definition["GlobalSecondaryIndexes"] = [
            {
                "IndexName": "by_user",
                "KeySchema": [
                    {"AttributeName": "user_id", "KeyType": "HASH"},
                    {"AttributeName": "ts_event", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ]
    definition["AttributeDefinitions"] = [{"AttributeName": name, "AttributeType": "S"} for name in attributes]
    return definition


def create_tables(client: Any, specs: list[TableSpec]) -> list[str]:
    """Create every table that does not exist yet. Returns the names it created."""
    existing = set(client.list_tables()["TableNames"])
    created: list[str] = []
    for spec in specs:
        if spec.name in existing:
            continue
        client.create_table(**_definition(spec))
        client.get_waiter("table_exists").wait(TableName=spec.name)
        if spec.ttl_attribute:
            client.update_time_to_live(
                TableName=spec.name,
                TimeToLiveSpecification={"Enabled": True, "AttributeName": spec.ttl_attribute},
            )
        created.append(spec.name)
    return created
