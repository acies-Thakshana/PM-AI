"""Ground SQL in the stored values and repair it once when the result is unusable."""

from __future__ import annotations

import json
import re

import pandas as pd

from app.config import CALL_SQL_REPAIR
from app.services.common.llm import LlmClient, complete_json
from app.services.sql.grounding import ColumnProfile, diagnose, prepare_sql, references_unavailable, result_is_vacuous


def normalize_bool_literals(sql: str) -> str:
    text = str(sql or "")
    text = re.sub(r"(?i)(=\s*)(?:'True'|\"True\"|\btrue\b)", r"\g<1>1", text)
    text = re.sub(r"(?i)(=\s*)(?:'False'|\"False\"|\bfalse\b)", r"\g<1>0", text)
    text = re.sub(r"(?i)\bIS\s+TRUE\b", "= 1", text)
    text = re.sub(r"(?i)\bIS\s+FALSE\b", "= 0", text)
    return text


def ground_sql(
    sql: str,
    profiles: list[ColumnProfile],
    question: str,
    aliases: list[tuple[str, str]] | None = None,
) -> str:
    text = normalize_bool_literals(str(sql or "").strip())
    if profiles and text:
        text = normalize_bool_literals(prepare_sql(text, profiles, question, aliases=aliases or []))
    return text


def problem_with(
    sql: str,
    profiles: list[ColumnProfile],
    frame: pd.DataFrame | None,
    error: str = "",
) -> str:
    """Why the result cannot support an answer, or an empty string when it can."""
    if error:
        return error
    if not profiles:
        return "The query returned no rows." if frame is None or frame.empty else ""
    if result_is_vacuous(frame) or references_unavailable(sql, profiles):
        return diagnose(sql, profiles, frame)
    return ""


def repair_sql(llm: LlmClient, question: str, sql: str, catalog: str, problem: str, schema: dict) -> str:
    payload = complete_json(
        llm,
        CALL_SQL_REPAIR,
        json.dumps(
            {
                "question": question,
                "previous_sql": sql,
                "problem": problem,
                "catalog": catalog,
                "registered_joins": schema.get("registered_joins") or [],
            },
            default=str,
        ),
        fallback={"sql_query": sql, "rationale": "kept previous SQL"},
    )
    return str(payload.get("sql_query") or sql).strip()
