"""Run validated SQL. The default engine is in-memory SQLite over pandas frames."""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from app.services.guardrails.sql_policy import SqlPolicy

LOGGER = logging.getLogger(__name__)
_PROGRESS_EVERY = 1000


@dataclass
class QueryResult:
    frame: pd.DataFrame
    error: str = ""
    truncated: bool = False
    elapsed_seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.error


class SqlExecutor(Protocol):
    def execute(self, sql: str, frames: dict[str, pd.DataFrame]) -> QueryResult: ...


class SqliteFrameExecutor:
    """Loads frames into a read-only in-memory database and fetches at most ``row_limit`` rows."""

    def __init__(self, policy: SqlPolicy) -> None:
        self.policy = policy
        self._key: tuple[int, ...] | None = None
        self._conn: sqlite3.Connection | None = None

    def _connection(self, frames: dict[str, pd.DataFrame]) -> sqlite3.Connection:
        key = tuple(sorted((id(frame), hash(name)) for name, frame in frames.items()))
        if self._conn is not None and self._key == key:
            return self._conn
        self.close()
        conn = sqlite3.connect(":memory:")
        for name, frame in frames.items():
            frame.to_sql(name, conn, index=False, if_exists="replace")
        conn.execute("PRAGMA query_only = ON")
        self._conn, self._key = conn, key
        return conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
        self._conn, self._key = None, None

    def execute(self, sql: str, frames: dict[str, pd.DataFrame]) -> QueryResult:
        started = time.perf_counter()
        if not frames:
            return QueryResult(pd.DataFrame(), error="No datasets are loaded.")
        conn = self._connection(frames)
        budget = {"steps": 0}

        def progress() -> int:
            budget["steps"] += _PROGRESS_EVERY
            return 1 if budget["steps"] > self.policy.max_execution_steps else 0

        conn.set_progress_handler(progress, _PROGRESS_EVERY)
        try:
            cursor = conn.execute(sql)
            columns = [d[0] for d in cursor.description or []]
            rows = cursor.fetchmany(self.policy.row_limit + 1)
            truncated = len(rows) > self.policy.row_limit
            frame = pd.DataFrame(rows[: self.policy.row_limit], columns=columns)
            return QueryResult(frame, truncated=truncated, elapsed_seconds=time.perf_counter() - started)
        except sqlite3.OperationalError as exc:
            message = str(exc)
            if "interrupted" in message.lower():
                message = "Query stopped: it exceeded the execution budget. Add filters or aggregate."
            LOGGER.info("SQL failed: %s", message)
            return QueryResult(pd.DataFrame(), error=message, elapsed_seconds=time.perf_counter() - started)
        except sqlite3.Error as exc:
            LOGGER.info("SQL failed: %s", exc)
            return QueryResult(pd.DataFrame(), error=str(exc), elapsed_seconds=time.perf_counter() - started)
        finally:
            conn.set_progress_handler(None, 0)
