"""Local JSONL audit sink."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from aibi.settings import get_settings


def write_audit(event: dict[str, Any]) -> None:
    path = get_settings().audit_path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        **event,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, default=str) + "\n")
