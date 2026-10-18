"""Question-and-answer turns of a conversation, used to resolve follow-up questions.

History is scoped to a session: ``recent`` returns nothing without a session id, so one user's
questions never become another user's context.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.services.common import dynamo

_TURN_FIELDS = ("question", "metric", "answer", "sql_query", "status")


def _summary(turn: dict[str, Any]) -> dict[str, Any]:
    return {name: turn.get(name) for name in _TURN_FIELDS}


class HistoryStore(Protocol):
    def append(self, domain: str, session_id: str, turn: dict[str, Any]) -> None: ...

    def recent(self, domain: str, session_id: str | None, limit: int) -> list[dict[str, Any]]:
        """The last ``limit`` turns of the session, oldest first."""
        ...


class LocalHistoryStore:
    """``<root>/<domain>.jsonl``, one line per turn."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._lock = threading.Lock()

    def _path(self, domain: str) -> Path:
        return self._root / f"{domain}.jsonl"

    def append(self, domain: str, session_id: str, turn: dict[str, Any]) -> None:
        record = {"recorded_at": datetime.now(timezone.utc).isoformat(), "session_id": session_id, **turn}
        with self._lock:
            self._root.mkdir(parents=True, exist_ok=True)
            with self._path(domain).open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, default=str) + "\n")

    def recent(self, domain: str, session_id: str | None, limit: int) -> list[dict[str, Any]]:
        path = self._path(domain)
        if not session_id or limit <= 0 or not path.exists():
            return []
        with self._lock:
            lines = path.read_text(encoding="utf-8").splitlines()
        turns: list[dict[str, Any]] = []
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("session_id") == session_id:
                turns.append(record)
        return [_summary(turn) for turn in turns[-limit:]]


class DynamoHistoryStore:
    """Partition ``session_key`` (``<domain>#<session id>``), sort ``sort_key`` (timestamp)."""

    def __init__(self, table: str, ttl_days: int) -> None:
        self._table = table
        self._ttl_days = ttl_days

    @staticmethod
    def _key(domain: str, session_id: str) -> str:
        return f"{domain}#{session_id}"

    def append(self, domain: str, session_id: str, turn: dict[str, Any]) -> None:
        dynamo.put_item(
            self._table,
            {
                "session_key": self._key(domain, session_id),
                "sort_key": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                "payload": json.dumps(turn, default=str),
                "expires_at": dynamo.expiry(self._ttl_days),
            },
        )

    def recent(self, domain: str, session_id: str | None, limit: int) -> list[dict[str, Any]]:
        if not session_id or limit <= 0:
            return []
        items = dynamo.query(
            self._table, ("session_key", self._key(domain, session_id)), newest_first=True, limit=limit
        )
        return [_summary(json.loads(item["payload"])) for item in reversed(items)]
