"""Creates the DynamoDB table that keeps the chat turns (the DDB_CHATS table).

Safe to run twice: an existing table is left alone.

    python scripts/create_chat_table.py --table uda327-chats-dev --region eu-north-1

Needs AWS credentials (`aws configure` or AWS_PROFILE) that may call dynamodb:CreateTable, DescribeTable,
UpdateTimeToLive, UpdateContinuousBackups and TagResource. The backend itself only needs PutItem, GetItem
and Query on the table and on its indexes.
"""
from __future__ import annotations

import argparse
import sys

import boto3
from botocore.exceptions import ClientError

TTL_ATTRIBUTE = "ttl"  # the same attribute name the other tables use
KEY_ATTRIBUTES = ("chat_id", "turn_id", "user_id", "session_id", "started_at")


def _index(name: str, hash_key: str, projected: list[str]) -> dict:
    """A global index sorted by start time; only `projected` plus the table keys are copied into it."""
    return {
        "IndexName": name,
        "KeySchema": [
            {"AttributeName": hash_key, "KeyType": "HASH"},
            {"AttributeName": "started_at", "KeyType": "RANGE"},
        ],
        "Projection": {"ProjectionType": "INCLUDE", "NonKeyAttributes": projected},
    }


def create_chat_table(ddb, table: str) -> None:
    """Create the table with its two indexes, then switch on expiry and point-in-time backup.

    `by-session` is sparse: a turn with no session_id (the chat starts before data is loaded) has no such
    attribute, so it is simply not in that index."""
    ddb.create_table(
        TableName=table,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": name, "AttributeType": "S"} for name in KEY_ATTRIBUTES],
        KeySchema=[
            {"AttributeName": "chat_id", "KeyType": "HASH"},
            {"AttributeName": "turn_id", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            _index("by-user", "user_id", ["session_id", "intent", "handled_by", "status"]),
            _index("by-session", "session_id", ["user_id", "intent", "handled_by", "status"]),
        ],
        DeletionProtectionEnabled=True,
        Tags=[{"Key": "project", "Value": "pm-ai"}],
    )
    ddb.get_waiter("table_exists").wait(TableName=table)
    ddb.update_time_to_live(
        TableName=table, TimeToLiveSpecification={"Enabled": True, "AttributeName": TTL_ATTRIBUTE}
    )
    ddb.update_continuous_backups(
        TableName=table, PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True}
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the chat-turns DynamoDB table.")
    parser.add_argument("--table", required=True, help="table name, e.g. uda327-chats-dev")
    parser.add_argument("--region", default="eu-north-1")
    args = parser.parse_args()

    ddb = boto3.client("dynamodb", region_name=args.region)
    try:
        create_chat_table(ddb, args.table)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceInUseException":
            print(f"{args.table} already exists; nothing to do.")
            return 0
        print(f"Could not create {args.table}: {exc}", file=sys.stderr)
        return 1
    print(f"Created {args.table} with expiry (ttl) and point-in-time recovery.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
