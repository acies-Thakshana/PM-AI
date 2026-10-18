"""Thin helpers over the low-level DynamoDB client.

Items are plain ``dict`` values whose attributes are strings, integers or booleans. Structured
data is stored as a JSON string attribute (``payload``), which sidesteps DynamoDB's number rules
and keeps every item readable in the console.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

from app.errors import ConflictError
from app.services.common import aws_clients

Item = dict[str, Any]
_BATCH_SIZE = 25
_BATCH_RETRIES = 6


def _to_attr(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, int):
        return {"N": str(value)}
    return {"S": str(value)}


def _from_attr(attr: dict[str, Any]) -> Any:
    if "N" in attr:
        return int(attr["N"])
    if "BOOL" in attr:
        return attr["BOOL"]
    return attr.get("S", "")


def _encode(item: Item) -> dict[str, Any]:
    return {name: _to_attr(value) for name, value in item.items() if value is not None}


def _decode(raw: dict[str, Any]) -> Item:
    return {name: _from_attr(attr) for name, attr in raw.items()}


def expiry(days: int) -> int:
    """Epoch seconds for the DynamoDB TTL attribute."""
    return int(time.time()) + 86400 * days


def put_item(table: str, item: Item, *, only_if_absent_key: str | None = None) -> None:
    """Write one item. With ``only_if_absent_key`` the write fails if that key already exists."""
    client = aws_clients.dynamodb()
    kwargs: dict[str, Any] = {}
    if only_if_absent_key:
        kwargs["ConditionExpression"] = "attribute_not_exists(#k)"
        kwargs["ExpressionAttributeNames"] = {"#k": only_if_absent_key}
    try:
        client.put_item(TableName=table, Item=_encode(item), **kwargs)
    except client.exceptions.ConditionalCheckFailedException as exc:
        raise ConflictError(f"{table} already holds an item with that key") from exc


def get_item(table: str, key: Item) -> Item | None:
    response = aws_clients.dynamodb().get_item(TableName=table, Key=_encode(key), ConsistentRead=True)
    raw = response.get("Item")
    return _decode(raw) if raw else None


def update_item(table: str, key: Item, changes: Item) -> None:
    """Set the given attributes on an existing item (creating it if needed)."""
    names = {f"#a{i}": name for i, name in enumerate(changes)}
    values = {f":v{i}": _to_attr(value) for i, value in enumerate(changes.values())}
    expression = "SET " + ", ".join(f"#a{i} = :v{i}" for i in range(len(changes)))
    aws_clients.dynamodb().update_item(
        TableName=table,
        Key=_encode(key),
        UpdateExpression=expression,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def query(
    table: str,
    partition: tuple[str, str],
    *,
    sort_prefix: tuple[str, str] | None = None,
    newest_first: bool = False,
    limit: int | None = None,
) -> list[Item]:
    """Every item under one partition key, following pagination.

    ``sort_prefix`` is ``(sort key name, prefix)``. ``limit`` caps the number of items returned.
    """
    client = aws_clients.dynamodb()
    key_name, key_value = partition
    names = {"#p": key_name}
    values = {":p": _to_attr(key_value)}
    condition = "#p = :p"
    if sort_prefix:
        names["#s"] = sort_prefix[0]
        values[":s"] = _to_attr(sort_prefix[1])
        condition += " AND begins_with(#s, :s)"
    kwargs: dict[str, Any] = {
        "TableName": table,
        "KeyConditionExpression": condition,
        "ExpressionAttributeNames": names,
        "ExpressionAttributeValues": values,
        "ConsistentRead": True,
        "ScanIndexForward": not newest_first,
    }
    items: list[Item] = []
    while True:
        if limit is not None:
            kwargs["Limit"] = limit - len(items)
        response = client.query(**kwargs)
        items.extend(_decode(raw) for raw in response.get("Items", []))
        if "LastEvaluatedKey" not in response or (limit is not None and len(items) >= limit):
            return items
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]


def batch_put(table: str, items: Iterable[Item]) -> None:
    """Write many items, 25 per request, retrying whatever DynamoDB leaves unprocessed."""
    client = aws_clients.dynamodb()
    pending = [{"PutRequest": {"Item": _encode(item)}} for item in items]
    for start in range(0, len(pending), _BATCH_SIZE):
        batch = {table: pending[start : start + _BATCH_SIZE]}
        for attempt in range(_BATCH_RETRIES):
            response = client.batch_write_item(RequestItems=batch)
            batch = response.get("UnprocessedItems") or {}
            if not batch:
                break
            time.sleep(0.05 * (2**attempt))
        else:
            raise ConflictError(f"Could not write every item to {table}; DynamoDB kept throttling")
