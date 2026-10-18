"""Start the SageMaker server locally and call /ping and /invocations."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("AIBI_PROJECT_ROOT", str(ROOT))
os.environ["AIBI_PORT"] = os.environ.get("AIBI_PORT", "8081")
os.environ["AIBI_HOST"] = "127.0.0.1"
sys.path.insert(0, str(ROOT))

from sagemaker_app.server import main  # noqa: E402


def _call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    port = os.environ["AIBI_PORT"]
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _wait_for_ping() -> tuple[int, dict]:
    last_error: Exception | None = None
    for _ in range(50):
        try:
            return _call("GET", "/ping")
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"Server did not start: {last_error}")


def main_test() -> int:
    thread = threading.Thread(target=main, daemon=True)
    thread.start()
    status, ping = _wait_for_ping()
    if status != 200 or ping.get("status") != "ok":
        print("PING FAILED", status, ping)
        return 1
    status, answer = _call(
        "POST",
        "/invocations",
        {"question": "What is total Agg Productivity?", "domain": "generic_cube"},
    )
    print(json.dumps({"ping": ping, "status": answer.get("status"), "answer": answer.get("answer"), "sql": answer.get("sql_query")}, indent=2))
    if status != 200 or answer.get("status") != "success":
        print("ASK FAILED")
        return 1
    print("LOCAL SAGEMAKER CONTRACT PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_test())
