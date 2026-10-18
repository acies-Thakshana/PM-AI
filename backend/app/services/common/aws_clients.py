"""One lazily created boto3 client per AWS service, shared by the whole process.

boto3 clients are thread-safe. Creating one is the slow part (it resolves credentials and loads
the service model), so each is built once on first use. Nothing here runs in local mode, so a
laptop without AWS credentials never touches it.

Credentials are never read from code or environment variables: on ECS the task role supplies
them, and locally boto3 uses whatever ``aws configure`` or ``AWS_PROFILE`` provides.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import boto3
from botocore.config import Config

from app.config import get_settings

_lock = threading.Lock()
_clients: dict[str, Any] = {}


def _get(key: str, factory: Callable[[], Any]) -> Any:
    client = _clients.get(key)
    if client is None:
        with _lock:
            client = _clients.get(key)
            if client is None:
                client = factory()
                _clients[key] = client
    return client


def s3() -> Any:
    return _get(
        "s3",
        lambda: boto3.client(
            "s3",
            region_name=get_settings().aws_region,
            # Presigned URLs need the regional endpoint and SigV4, or browsers are redirected
            # and the CORS preflight fails for buckets outside us-east-1.
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        ),
    )


def dynamodb() -> Any:
    """The low-level DynamoDB client (items use ``{"S": "..."}`` typed values)."""
    return _get(
        "dynamodb",
        lambda: boto3.client(
            "dynamodb",
            region_name=get_settings().aws_region,
            config=Config(retries={"max_attempts": 5, "mode": "standard"}),
        ),
    )


def bedrock_runtime() -> Any:
    """Converse calls. Model answers can be slow, hence the long read timeout."""
    return _get(
        "bedrock-runtime",
        lambda: boto3.client(
            "bedrock-runtime",
            region_name=get_settings().bedrock_region,
            config=Config(read_timeout=120, connect_timeout=10, retries={"max_attempts": 4, "mode": "standard"}),
        ),
    )


def bedrock_agent() -> Any:
    """Prompt Management (GetPrompt)."""
    return _get(
        "bedrock-agent",
        lambda: boto3.client(
            "bedrock-agent",
            region_name=get_settings().bedrock_region,
            config=Config(retries={"max_attempts": 3, "mode": "standard"}),
        ),
    )


def reset() -> None:
    """Drop every cached client. Used by tests that swap in a mocked AWS."""
    with _lock:
        _clients.clear()
