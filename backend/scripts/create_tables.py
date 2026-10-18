"""Create the DynamoDB tables and S3 bucket for a development environment.

Reads the same environment variables as the service (``backend/.env``), so run it with the
variables of the account you are setting up:

    python -m scripts.create_tables

Production environments should create these resources with infrastructure-as-code; this script
exists so a developer can stand up a working environment in one command.
"""

from __future__ import annotations

import sys

from app.config import get_settings
from app.services.common import aws_clients
from app.services.common.dynamo_tables import create_tables, table_specs


def main() -> int:
    settings = get_settings()
    if not settings.use_aws_storage:
        print("Set S3_BUCKET and every DDB_* variable first (see .env.example).")
        return 1
    created = create_tables(aws_clients.dynamodb(), table_specs(settings))
    print("Created tables:", ", ".join(created) if created else "none (all already exist)")

    s3 = aws_clients.s3()
    if settings.s3_bucket not in {bucket["Name"] for bucket in s3.list_buckets().get("Buckets", [])}:
        options: dict[str, object] = {"Bucket": settings.s3_bucket}
        if settings.aws_region != "us-east-1":  # us-east-1 rejects an explicit location constraint
            options["CreateBucketConfiguration"] = {"LocationConstraint": settings.aws_region}
        s3.create_bucket(**options)
        s3.put_public_access_block(
            Bucket=settings.s3_bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
        print(f"Created bucket {settings.s3_bucket}")
    else:
        print(f"Bucket {settings.s3_bucket} already exists")
    return 0


if __name__ == "__main__":
    sys.exit(main())
