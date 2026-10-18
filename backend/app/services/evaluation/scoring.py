"""Execution accuracy of generated SQL against expected SQL.

Generated SQL is correct when it returns the same business figures as the
expected SQL. Column names may differ. A ratio and the same ratio times 100
count as the same figure. Questions without expected SQL (for example a
deliberate refusal case) are reported as not_scored and left out of accuracy.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.services.common.frames import as_number, find_column, is_missing, preview
from app.services.sql.executor import SqlExecutor

QUESTION_COLUMNS = ("input_question", "question", "Question")
EXPECTED_COLUMNS = ("Expected_SQL_Query", "expected_sql_query", "expected_sql")
MODEL_SQL_COLUMNS = ("LLM_generated_SQL", "llm_generated_sql", "generated_sql", "sql_query")
OUTCOMES = ("correct", "wrong_value", "no_result", "sql_error")
NOT_SCORED = "not_scored"


def _as_text(value: Any) -> str | None:
    if as_number(value) is not None or is_missing(value):
        return None
    text = str(value).strip().casefold()
    return None if text in {"", "none", "nan", "null"} else text


def _numbers_close(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if abs(left - right) <= 0.02 + 0.001 * max(abs(left), abs(right)):
        return True
    for scale in (100.0, 0.01):
        scaled = left * scale
        if abs(scaled - right) <= 0.02 + 0.001 * max(abs(scaled), abs(right)):
            return True
    return False


def _row_parts(frame: pd.DataFrame | None) -> list[tuple[list[str], list[float]]]:
    rows: list[tuple[list[str], list[float]]] = []
    if frame is None or frame.empty:
        return rows
    for record in frame.itertuples(index=False, name=None):
        texts: list[str] = []
        numbers: list[float] = []
        for value in record:
            number = as_number(value)
            if number is not None:
                numbers.append(number)
            else:
                text = _as_text(value)
                if text is not None:
                    texts.append(text)
        rows.append((texts, numbers))
    return rows


def _has_figure(rows: list[tuple[list[str], list[float]]]) -> bool:
    return any(numbers for _, numbers in rows)


def _match_numbers(expected: list[float], actual: list[float]) -> bool:
    used: set[int] = set()
    for value in expected:
        found = next((i for i, other in enumerate(actual) if i not in used and _numbers_close(value, other)), None)
        if found is None:
            return False
        used.add(found)
    return True


def results_match(expected_frame: pd.DataFrame | None, actual_frame: pd.DataFrame | None) -> bool:
    expected_rows = _row_parts(expected_frame)
    actual_rows = _row_parts(actual_frame)
    if not _has_figure(expected_rows):
        return not _has_figure(actual_rows)
    if len(expected_rows) != len(actual_rows) or not _has_figure(actual_rows):
        return False
    repeated = set(expected_rows[0][0]) if expected_rows else set()
    for texts, _ in expected_rows[1:]:
        repeated &= set(texts)
    pool = list(actual_rows)
    for texts, numbers in expected_rows:
        required = [t for t in texts if t not in repeated]
        found = None
        for index, (other_texts, other_numbers) in enumerate(pool):
            if any(t not in other_texts for t in required) or not other_numbers:
                continue
            if _match_numbers(other_numbers, numbers):
                found = index
                break
        if found is None:
            return False
        pool.pop(found)
    return True


def _column(frame: pd.DataFrame, names: tuple[str, ...], default: Any = "") -> pd.Series:
    found = find_column(frame, names)
    if found is not None:
        return frame[found]
    return pd.Series([default] * len(frame), index=frame.index)


def _run(executor: SqlExecutor, frames: dict[str, pd.DataFrame], sql: Any) -> tuple[pd.DataFrame, str]:
    text = "" if is_missing(sql) else str(sql).strip().rstrip(";")
    if not text:
        return pd.DataFrame(), "SQL is empty."
    result = executor.execute(text, frames)
    return result.frame, result.error


def score_frame(results: pd.DataFrame, frames: dict[str, pd.DataFrame], executor: SqlExecutor) -> pd.DataFrame:
    if find_column(results, MODEL_SQL_COLUMNS) is None:
        raise ValueError("Results have no generated SQL column. Expected one of: " + ", ".join(MODEL_SQL_COLUMNS))
    questions = _column(results, QUESTION_COLUMNS)
    expected_sql = _column(results, EXPECTED_COLUMNS)
    model_sql = _column(results, MODEL_SQL_COLUMNS)
    latency = _column(results, ("latency_seconds", "latency"), default=None)
    confidence = _column(results, ("confidence", "confidence_score"), default=None)
    rows = []
    for question, gold_sql, guess_sql, seconds, score in zip(
        questions.tolist(),
        expected_sql.tolist(),
        model_sql.tolist(),
        latency.tolist(),
        confidence.tolist(),
        strict=True,
    ):
        if is_missing(question) or not str(question).strip():
            continue
        if is_missing(gold_sql) or not str(gold_sql).strip():
            rows.append(
                {
                    "input_question": str(question).strip(),
                    "outcome": NOT_SCORED,
                    "accurate": 0,
                    "latency_seconds": None if is_missing(seconds) else float(seconds),
                    "confidence": None if is_missing(score) else float(score),
                    "expected_preview": "",
                    "model_preview": "",
                    "note": "No Expected_SQL_Query; excluded from accuracy.",
                }
            )
            continue
        gold, gold_error = _run(executor, frames, gold_sql)
        guess, guess_error = _run(executor, frames, guess_sql)
        note = f"Expected SQL failed: {gold_error}" if gold_error else guess_error
        if gold_error or guess_error:
            outcome = "sql_error"
        elif results_match(gold, guess):
            outcome = "correct"
        elif not _has_figure(_row_parts(guess)):
            outcome = "no_result"
        else:
            outcome = "wrong_value"
        rows.append(
            {
                "input_question": str(question).strip(),
                "outcome": outcome,
                "accurate": 1 if outcome == "correct" else 0,
                "latency_seconds": None if is_missing(seconds) else float(seconds),
                "confidence": None if is_missing(score) else float(score),
                "expected_preview": str(preview(gold, 5)["rows"]),
                "model_preview": str(preview(guess, 5)["rows"]),
                "note": note,
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "input_question",
            "outcome",
            "accurate",
            "latency_seconds",
            "confidence",
            "expected_preview",
            "model_preview",
            "note",
        ],
    )


def _percentile(values: list[float], fraction: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))]


def summarize(detail: pd.DataFrame) -> dict[str, Any]:
    skipped = int((detail["outcome"] == NOT_SCORED).sum()) if len(detail) else 0
    detail = detail[detail["outcome"] != NOT_SCORED] if len(detail) else detail
    total = int(len(detail))
    correct = int(detail["accurate"].sum()) if total else 0
    counts = {label: int((detail["outcome"] == label).sum()) if total else 0 for label in OUTCOMES}
    counts[NOT_SCORED] = skipped
    latency = [float(v) for v in detail["latency_seconds"].tolist() if not is_missing(v)] if total else []
    confidence = [float(v) for v in detail["confidence"].tolist() if not is_missing(v)] if total else []
    bins = []
    if confidence:
        for low, high in ((0.0, 0.5), (0.5, 0.8), (0.8, 1.01)):
            chosen = detail[detail["confidence"].astype(float).between(low, high, inclusive="left")]
            if not chosen.empty:
                bins.append(
                    {
                        "confidence_from": low,
                        "confidence_to": min(high, 1.0),
                        "questions": int(len(chosen)),
                        "accuracy": float(chosen["accurate"].mean()),
                    }
                )
    return {
        "questions": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "confusion_matrix": {
            "actual_correct": {"predicted_correct": counts["correct"], "predicted_incorrect": total - counts["correct"]}
        },
        "outcome_counts": counts,
        "latency_seconds": {
            "questions_timed": len(latency),
            "mean": round(sum(latency) / len(latency), 3) if latency else None,
            "median": round(_percentile(latency, 0.5), 3) if latency else None,
            "p95": round(_percentile(latency, 0.95), 3) if latency else None,
        },
        "confidence": {
            "questions_scored": len(confidence),
            "mean": round(sum(confidence) / len(confidence), 3) if confidence else None,
            "accuracy_by_bin": bins,
        },
    }


def score_results(
    results: pd.DataFrame, frames: dict[str, pd.DataFrame], executor: SqlExecutor
) -> tuple[pd.DataFrame, dict[str, Any]]:
    detail = score_frame(results, frames, executor)
    return detail, summarize(detail)
