"""Shared fixtures. Every test runs on a throw-away copy of ``data/`` with a clean environment,
so nothing a test uploads or learns can leak into the project or into another test."""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import BACKEND_DIR, Settings, get_settings
from app.services.common import prompt_files  # AWS-DISABLED: aws_clients
from app.services.context import AppContext, build_context, get_context

_ENV_PREFIXES = ("AWS_", "DDB_", "S3_", "ENTRA_", "BEDROCK_", "AI4BI_", "DOMAIN_", "MODEL_", "LLM_", "ALLOW_")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Local mode, no login, no model, and a private data directory."""
    import os

    for name in list(os.environ):
        if name.startswith(_ENV_PREFIXES):
            monkeypatch.delenv(name)
    data_dir = tmp_path / "data"
    shutil.copytree(BACKEND_DIR / "data", data_dir)
    monkeypatch.setenv("AI4BI_DATA_DIR", str(data_dir))
    _reset_caches()
    yield data_dir
    _reset_caches()


def _reset_caches() -> None:
    get_settings.cache_clear()
    get_context.cache_clear()
    # AWS-DISABLED: aws_clients.reset()
    pass
    prompt_files.clear_cache()


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def ctx(settings: Settings) -> AppContext:
    return build_context(settings)


@pytest.fixture
def make_client() -> Iterator[Callable[[], TestClient]]:
    """Build the app on demand, so a test can set its environment first. Closed when the test ends."""
    from app.main import create_app

    opened: list[TestClient] = []

    def build() -> TestClient:
        test_client = TestClient(create_app())
        test_client.__enter__()
        opened.append(test_client)
        return test_client

    yield build
    for test_client in opened:
        test_client.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Callable[[], TestClient]) -> TestClient:
    return make_client()


def wait_for_job(client: TestClient, job_id: str, headers: dict[str, str] | None = None) -> dict:
    """Poll a job until it finishes (or give up after about ten seconds)."""
    status: dict = {}
    for _ in range(50):
        status = client.get(f"/api/jobs/{job_id}", headers=headers or {}).json()
        if status["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.2)
    return status

# AWS-DISABLED: these suites need boto3, moto and PyJWT. Remove this line when AWS is re-enabled.
collect_ignore = ["test_aws.py", "test_auth.py"]
