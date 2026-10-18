"""DataFrame helpers that do not depend on a platform."""

from __future__ import annotations

import json
import math
from typing import Any

import pandas as pd

TRUE_TOKENS = frozenset({"true", "t", "yes", "y", "1"})
FALSE_TOKENS = frozenset({"false", "f", "no", "n", "0"})


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def as_number(value: Any) -> float | None:
    if isinstance(value, bool) or is_missing(value):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return None if math.isnan(number) else number
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in {"none", "nan", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def coerce_flags(frame: pd.DataFrame) -> pd.DataFrame:
    """Store true/false columns as 1/0, which is how SQLite receives Dataiku booleans."""
    out = frame.copy()
    for col in out.columns:
        series = out[col]
        if pd.api.types.is_bool_dtype(series):
            out[col] = series.astype("int64")
            continue
        if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
            continue
        seen = set()
        for value in series.dropna().unique():
            text = str(value).strip().lower()
            if text and text not in {"nan", "none"}:
                seen.add(text)
        if seen and seen <= (TRUE_TOKENS | FALSE_TOKENS):
            out[col] = series.map(
                lambda value: None
                if is_missing(value)
                else (1 if str(value).strip().lower() in TRUE_TOKENS else 0)
            )
    return out


def preview(frame: pd.DataFrame | None, limit: int = 20) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {
            "columns": [] if frame is None else [str(c) for c in frame.columns],
            "rows": [],
            "n": 0,
        }
    clipped = frame.head(limit)
    return {
        "columns": [str(c) for c in clipped.columns],
        "rows": json.loads(clipped.to_json(orient="records", date_format="iso")),
        "n": int(len(frame)),
    }


def find_column(frame: pd.DataFrame, names: tuple[str, ...] | list[str]) -> str | None:
    lookup = {"".join(ch for ch in str(c).lower() if ch.isalnum()): c for c in frame.columns}
    for name in names:
        found = lookup.get("".join(ch for ch in name.lower() if ch.isalnum()))
        if found is not None:
            return str(found)
    return None
