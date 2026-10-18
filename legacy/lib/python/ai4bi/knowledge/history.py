"""Previous question-and-answer turns, stored as JSONL per domain."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class HistoryStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path(self, domain: str) -> Path:
        return self.root / f"{domain}.jsonl"

    def append(self, domain: str, turn: dict[str, Any]) -> None:
        target = self.path(domain)
        target.parent.mkdir(parents=True, exist_ok=True)
        record = {"recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **turn}
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, default=str) + "\n")

    def recent(self, domain: str, *, session_id: str | None = None, limit: int = 3) -> list[dict[str, Any]]:
        target = self.path(domain)
        if not target.exists() or limit <= 0:
            return []
        turns: list[dict[str, Any]] = []
        for line in target.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if session_id and record.get("session_id") != session_id:
                continue
            turns.append(record)
        return [
            {
                "question": t.get("question"),
                "metric": t.get("metric"),
                "answer": t.get("answer"),
                "sql_query": t.get("sql_query"),
                "status": t.get("status"),
            }
            for t in turns[-limit:]
        ]
