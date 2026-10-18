"""Answer a table of questions. Used by the Dataiku recipe and the local batch command."""

from __future__ import annotations

import json
import time
from typing import Any

import pandas as pd

from ai4bi.config.errors import DataNotFoundError
from ai4bi.knowledge.graph import KnowledgeGraph
from ai4bi.logging import get_logger
from ai4bi.pipeline.ask import ask
from ai4bi.pipeline.context import AppContext
from ai4bi.semantic.models import DomainPackage
from ai4bi.utils.frames import find_column, is_missing
from ai4bi.utils.text import stable_id

LOGGER = get_logger(__name__)

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


def _confidence(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if 1 < number <= 100:
        number /= 100.0
    return min(1.0, max(0.0, number))


def run_batch(
    questions: pd.DataFrame,
    *,
    context: AppContext,
    domain: str,
    frames: dict[str, pd.DataFrame] | None = None,
    graph: KnowledgeGraph | None = None,
    semantic_package: DomainPackage | None = None,
) -> tuple[pd.DataFrame, KnowledgeGraph]:
    """One result row per question. The graph accumulates across the batch."""
    question_column = find_column(questions, QUESTION_COLUMNS)
    if question_column is None:
        raise DataNotFoundError(
            "The question dataset needs a column named one of: " + ", ".join(QUESTION_COLUMNS)
        )
    expected_column = find_column(questions, EXPECTED_COLUMNS)
    graph = graph if graph is not None else context.graphs.load(domain)
    rows: list[dict[str, Any]] = []
    for index, record in enumerate(questions.to_dict(orient="records")):
        question = record.get(question_column)
        if is_missing(question) or not str(question).strip():
            continue
        question = str(question).strip()
        expected = record.get(expected_column) if expected_column else ""
        started = time.perf_counter()
        try:
            result = ask(
                question,
                context=context,
                domain=domain,
                frames=frames,
                graph=graph,
                persist=False,
                semantic_package=semantic_package,
            )
        except Exception as exc:  # noqa: BLE001
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
                "confidence": _confidence(result.get("confidence")),
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
        raise DataNotFoundError("The question dataset has no questions.")
    return pd.DataFrame(rows, columns=RESULT_COLUMNS), graph
