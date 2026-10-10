"""Column metadata of an uploaded dataset: ONE `COLUMNS` document per session.

Written once at upload (the Planner reads all of it to know what the data holds). The document is
`{"column_count": n, "columns": {<column name>: <profile>, ...}}` -- every column's full profile
(type, role, missing/unique counts, ranges, samples ...) in file order. A very wide file can make
the document large; doc_store gzip-compresses anything over ~300 KB on its own, so the item stays
under DynamoDB's 400 KB limit. The session's row count lives on the session header (`SESSIONS`).
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from app.services.audit.column_profiler import profile_dataframe
from app.services.common import doc_store

DOC = "COLUMNS"


def save(session_id: str, df: pd.DataFrame) -> int:
    """Profile every column and store them as one document; returns how many columns."""
    columns = profile_dataframe(df)
    doc_store.put(session_id, DOC, {"column_count": len(columns), "columns": columns})
    return len(columns)


def load(session_id: str) -> dict[str, Any] | None:
    """{"row_count", "column_count", "columns": {name: profile}} in file order, or None if the
    session has no column metadata."""
    from app.services.audit.audit_store import store

    data = doc_store.get(session_id, DOC)
    if not isinstance(data, dict) or "columns" not in data:
        return None
    session = store.get(session_id)
    return {
        "session_id": session_id,
        "row_count": getattr(session, "row_count", 0) if session else 0,
        "column_count": len(data["columns"]),
        "columns": data["columns"],
    }
