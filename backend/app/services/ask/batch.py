"""Answer a table of questions against one domain, sharing one data view and one knowledge graph."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import pandas as pd

from app.errors import DataNotFoundError, InvalidInputError
from app.services.ask.domain_view import resolve_domain
from app.services.ask.pipeline import ask, normalize_confidence
from app.services.common.frames import find_column, is_missing
from app.services.common.text import stable_id
from app.services.context import AppContext

LOGGER = logging.getLogger(__name__)

QUESTION_COLUMNS = ("input_question", "question", "Question")
EXPECTED_COLUMNS = ("Expected_SQL_Query", "expected_sql_query", "expected_sql")
RESULT_COLUMNS = [
    "question",
    "Expected_SQL_Query",
    "LLM_generated_SQL",
    "LLM_generated_answer",
    "status",
    "intent",
    "confidence",
    "metrics_json",
    "calculations_json",
    "chart_template",
    "follow_up_questions",
    "warnings",
    "latency_seconds",
    "kg_nodes",
    "kg_edges",
    "kg_episodes",
]


def run_batch(
    questions: pd.DataFrame,
    *,
    context: AppContext,
    domain: str,
    persist: bool = False,
    max_questions: int | None = None,
) -> pd.DataFrame:
    """One result row per question. The graph accumulates across the batch.

    The graph is saved once at the end when ``persist`` is set, instead of after every question.
    """
    question_column = find_column(questions, QUESTION_COLUMNS)
    if question_column is None:
        raise InvalidInputError("The question table needs a column named one of: " + ", ".join(QUESTION_COLUMNS))
    if max_questions is not None and len(questions) > max_questions:
        raise InvalidInputError(f"A batch can hold at most {max_questions} questions; this one has {len(questions)}.")
    expected_column = find_column(questions, EXPECTED_COLUMNS)
    view = resolve_domain(context, domain)
    graph = context.graphs.load(domain)
    rows: list[dict[str, Any]] = []
    for index, record in enumerate(questions.to_dict(orient="records")):
        question = record.get(question_column)
        if is_missing(question) or not str(question).strip():
            continue
        question = str(question).strip()
        expected = record.get(expected_column) if expected_column else ""
        started = time.perf_counter()
        try:
            result = ask(question, context=context, domain=domain, view=view, graph=graph, persist=False)
        except Exception as exc:  # noqa: BLE001 - one bad question must not abort the batch
            LOGGER.exception("Question %s failed", index)
            result = {"status": "error", "answer": f"ERROR: {exc}", "sql_query": "", "warnings": ["error"]}
            graph.record_episode(
                {
                    "question_id": stable_id("q.err", question),
                    "question": question,
                    "intent": "error",
                    "sql": "",
                    "status": "error",
                    "answer_excerpt": str(exc)[:400],
                }
            )
        stats = graph.stats()
        rows.append(
            {
                "question": question,
                "Expected_SQL_Query": "" if is_missing(expected) else str(expected),
                "LLM_generated_SQL": result.get("sql_query") or "",
                "LLM_generated_answer": result.get("answer") or "",
                "status": result.get("status"),
                "intent": result.get("intent") or "",
                "confidence": normalize_confidence(result.get("confidence")),
                "metrics_json": json.dumps(result.get("metrics") or [], default=str),
                "calculations_json": json.dumps(result.get("calculations") or [], default=str),
                "chart_template": (result.get("chart") or {}).get("template", ""),
                "follow_up_questions": json.dumps(result.get("follow_up_questions") or []),
                "warnings": json.dumps(result.get("warnings") or []),
                "latency_seconds": round(time.perf_counter() - started, 3),
                "kg_nodes": stats["nodes"],
                "kg_edges": stats["edges"],
                "kg_episodes": stats["episodes"],
            }
        )
        LOGGER.info("%s %s %s", index, result.get("status"), str(result.get("answer") or "")[:120])
    if not rows:
        raise DataNotFoundError("The question table has no questions.")
    if persist:
        context.graphs.save(graph)
    return pd.DataFrame(rows, columns=RESULT_COLUMNS)
