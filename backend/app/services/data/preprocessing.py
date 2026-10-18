"""Prepare frames for SQL and build the column catalog the model sees."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

import pandas as pd

from app.errors import DataNotFoundError
from app.services.common.frames import coerce_flags
from app.services.sql.grounding import ColumnProfile, schema_text

_SAFE_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def safe_table_name(name: str) -> str:
    text = str(name or "").strip()
    if _SAFE_TABLE.match(text):
        return text
    raise DataNotFoundError(
        f"Dataset {name!r} cannot be a SQL table name. Rename it to letters, numbers, and underscores."
    )


def prepare_frames(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    if not frames:
        raise DataNotFoundError("At least one fact dataset is required.")
    prepared: dict[str, pd.DataFrame] = {}
    for name, frame in frames.items():
        if frame is None:
            raise DataNotFoundError(f"Dataset {name!r} is empty.")
        prepared[safe_table_name(name)] = coerce_flags(frame)
    return prepared


def drop_restricted(frames: dict[str, pd.DataFrame], restricted: set[str]) -> dict[str, pd.DataFrame]:
    """Restricted columns never reach SQL execution or the prompt catalog."""
    lowered = {c.lower() for c in restricted}
    out: dict[str, pd.DataFrame] = {}
    for name, frame in frames.items():
        keep = [c for c in frame.columns if str(c).lower() not in lowered]
        out[name] = frame[keep]
    return out


@dataclass
class Catalog:
    text: str
    profiles: list[ColumnProfile] = field(default_factory=list)
    by_table: dict[str, list[ColumnProfile]] = field(default_factory=dict)


def build_catalog(
    profiles_by_table: dict[str, list[ColumnProfile]],
    question: str,
    *,
    notes: dict[str, str] | None = None,
    aliases: list[tuple[str, str]] | None = None,
) -> Catalog:
    """The catalog text the model sees for one question.

    ``profiles_by_table`` comes from the data cache, so profiling is not repeated per question.
    Column notes from the semantic layer are attached to copies; the cached profiles stay as they are.
    """
    notes = notes or {}
    parts: list[str] = []
    profiles: list[ColumnProfile] = []
    by_table: dict[str, list[ColumnProfile]] = {}
    for table, cached in profiles_by_table.items():
        table_profiles = [replace(p, description=str(notes.get(p.name) or "").strip()) for p in cached]
        by_table[table] = table_profiles
        profiles.extend(table_profiles)
        if table_profiles:
            parts.append(schema_text(table_profiles, question, table=table, aliases=aliases or []))
    return Catalog(text="\n\n".join(parts), profiles=profiles, by_table=by_table)
