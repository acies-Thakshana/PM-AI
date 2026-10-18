"""Prepare frames for SQL and build the column catalog the model sees."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from ai4bi.config.errors import DataNotFoundError
from ai4bi.sql.grounding import ColumnProfile, profile_frame, schema_text
from ai4bi.utils.frames import coerce_flags

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
    frames: dict[str, pd.DataFrame],
    question: str,
    *,
    notes: dict[str, str] | None = None,
    aliases: list[tuple[str, str]] | None = None,
) -> Catalog:
    parts: list[str] = []
    profiles: list[ColumnProfile] = []
    by_table: dict[str, list[ColumnProfile]] = {}
    for table, frame in frames.items():
        table_profiles = profile_frame(frame, notes=notes or {})
        by_table[table] = table_profiles
        profiles.extend(table_profiles)
        if table_profiles:
            parts.append(schema_text(table_profiles, question, table=table, aliases=aliases or []))
    return Catalog(text="\n\n".join(parts), profiles=profiles, by_table=by_table)
