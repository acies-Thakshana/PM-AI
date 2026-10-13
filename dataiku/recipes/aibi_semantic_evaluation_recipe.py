# -*- coding: utf-8 -*-
"""Score the text-to-SQL run.

Accuracy is execution accuracy: the generated SQL is correct when it returns
the same business figures as Expected_SQL_Query. Column names may differ.
A ratio and the same ratio times 100 count as the same figure.

The confusion matrix is binary:
  actual  = the expected SQL result (every validation question has one)
  predicted correct   = generated result matches
  predicted incorrect = generated result is wrong, empty, null, or the SQL failed

confidence is the 0-1 score the model returned with its answer.
latency_seconds is the wall-clock time of that question, including the LLM calls.

Those two columns are filled only after the validation recipe that records them
has been run. This scorer still reports accuracy and the confusion matrix when
they are missing.

Dataiku inputs:
  sf_accounts, sf_opportunities, sf_service_cases, coldchain_shipments,
  temperature_excursions, semantic_validation_llm
Dataiku output:
  semantic_validation_metrics

Local run (no Dataiku):
  py -3 aibi_semantic_evaluation_recipe.py
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import pandas as pd

FACT_TABLES = (
    "sf_accounts",
    "sf_opportunities",
    "sf_service_cases",
    "coldchain_shipments",
    "temperature_excursions",
)
DATA_DIRS = (
    Path(r"c:\Users\BharadNa\Downloads\data\data"),
    Path(r"c:\Users\BharadNa\Downloads\data"),
)
RESULT_GLOBS = (
    Path(r"c:\Users\BharadNa\Downloads"),
)


def _is_missing(value):
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _as_number(value):
    if isinstance(value, bool) or _is_missing(value):
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


def _as_text(value):
    if _as_number(value) is not None or _is_missing(value):
        return None
    text = str(value).strip().casefold()
    if text in {"", "none", "nan", "null"}:
        return None
    return text


def _numbers_close(left, right):
    if left is None or right is None:
        return left is None and right is None
    tolerance = 0.02 + 0.001 * max(abs(left), abs(right))
    if abs(left - right) <= tolerance:
        return True
    for scale in (100.0, 0.01):
        scaled = left * scale
        wide = 0.02 + 0.001 * max(abs(scaled), abs(right))
        if abs(scaled - right) <= wide:
            return True
    return False


def _row_parts(frame):
    rows = []
    if frame is None or frame.empty:
        return rows
    for record in frame.itertuples(index=False, name=None):
        texts = []
        numbers = []
        for value in record:
            number = _as_number(value)
            if number is not None:
                numbers.append(number)
            else:
                text = _as_text(value)
                if text is not None:
                    texts.append(text)
        rows.append((texts, numbers))
    return rows


def _has_figure(rows):
    return any(number is not None for _, numbers in rows for number in numbers)


def _match_numbers(expected, actual):
    used = set()
    for value in expected:
        found = None
        for index, other in enumerate(actual):
            if index in used:
                continue
            if _numbers_close(value, other):
                found = index
                break
        if found is None:
            return False
        used.add(found)
    return True


def _results_match(expected_frame, actual_frame):
    expected_rows = _row_parts(expected_frame)
    actual_rows = _row_parts(actual_frame)
    if not _has_figure(expected_rows):
        return not _has_figure(actual_rows)
    if len(expected_rows) != len(actual_rows) or not _has_figure(actual_rows):
        return False
    repeated = None
    if expected_rows:
        repeated = set(expected_rows[0][0])
        for texts, _ in expected_rows[1:]:
            repeated &= set(texts)
    pool = list(actual_rows)
    for texts, numbers in expected_rows:
        required = [text for text in texts if text not in (repeated or set())]
        found = None
        for index, (other_texts, other_numbers) in enumerate(pool):
            if any(text not in other_texts for text in required):
                continue
            if not other_numbers:
                continue
            # Extra expected columns are allowed. Every figure the model
            # returned still has to appear on the matching expected row.
            if _match_numbers(other_numbers, numbers):
                found = index
                break
        if found is None:
            return False
        pool.pop(found)
    return True


def _execute(frames, sql):
    text = str(sql or "").strip().rstrip(";")
    if not text:
        raise ValueError("SQL is empty.")
    with sqlite3.connect(":memory:") as conn:
        for name, frame in frames.items():
            _coerce_flags(frame).to_sql(name, conn, index=False, if_exists="replace")
        return pd.read_sql_query(text, conn)


def _preview(frame, limit=5):
    if frame is None or frame.empty:
        return ""
    return frame.head(limit).to_json(orient="records")


def _coerce_flags(frame):
    """Store true/false columns as 1/0, which is how SQLite receives Dataiku booleans."""
    out = frame.copy()
    true_tokens = {"true", "t", "yes", "y", "1"}
    false_tokens = {"false", "f", "no", "n", "0"}
    for col in out.columns:
        series = out[col]
        if pd.api.types.is_bool_dtype(series):
            out[col] = series.astype("int64")
            continue
        if not (
            pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)
        ):
            continue
        tokens = set()
        for value in series.dropna().unique():
            text = str(value).strip().lower()
            if text and text not in {"nan", "none"}:
                tokens.add(text)
        if tokens and tokens <= (true_tokens | false_tokens):
            out[col] = series.map(
                lambda value: (
                    None
                    if _is_missing(value)
                    else 1 if str(value).strip().lower() in true_tokens else 0
                )
            )
    return out


def _load_frames():
    frames = {}
    for folder in DATA_DIRS:
        if not folder.is_dir():
            continue
        for name in FACT_TABLES:
            path = folder / "{0}.csv".format(name)
            if path.exists():
                frames[name] = _coerce_flags(pd.read_csv(path))
        if len(frames) == len(FACT_TABLES):
            return frames
    missing = [name for name in FACT_TABLES if name not in frames]
    raise RuntimeError("Missing fact CSVs {0}. Looked in {1}".format(missing, list(DATA_DIRS)))


MODEL_SQL_NAMES = (
    "LLM_generated_SQL",
    "llm_generated_sql",
    "generated_sql",
    "sql_query",
)


def _col_key(name):
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _find_column(frame, names):
    lookup = {_col_key(col): col for col in frame.columns}
    for name in names:
        found = lookup.get(_col_key(name))
        if found is not None:
            return found
    return None


def _has_model_sql(frame):
    name = _find_column(frame, MODEL_SQL_NAMES)
    if name is None:
        return False
    for value in frame[name].tolist():
        if _is_missing(value):
            continue
        if str(value).strip():
            return True
    return False


def _latest_results():
    """Newest CSV that actually contains generated SQL.

    semantic_validation_llm (4).csv is a metrics export: it has outcome and
    note, and no LLM_generated_SQL. Scoring that file makes every row
    'SQL is empty.'
    """
    found = []
    for folder in RESULT_GLOBS:
        if not folder.is_dir():
            continue
        for path in folder.glob("semantic_validation_llm*.csv"):
            if "metrics" in path.stem.lower():
                continue
            try:
                frame = pd.read_csv(path)
            except Exception:
                continue
            if _has_model_sql(frame):
                found.append((path.stat().st_mtime, path, frame))
    if not found:
        raise RuntimeError(
            "No results file with column LLM_generated_SQL was found in {0}. "
            "Connect the dataset written by the validation recipe, not "
            "semantic_validation_questions and not the metrics output.".format(
                list(RESULT_GLOBS)
            )
        )
    found.sort(key=lambda item: item[0])
    return found[-1][1], found[-1][2]


def _column(frame, names, default=""):
    found = _find_column(frame, names)
    if found is not None:
        return frame[found]
    return pd.Series([default] * len(frame), index=frame.index)


def _score_frame(results, frames):
    questions = _column(results, ("input_question", "question", "Question"))
    expected_sql = _column(results, ("Expected_SQL_Query", "expected_sql_query", "expected_sql"))
    model_sql = _column(results, ("LLM_generated_SQL", "llm_generated_sql", "sql_query"))
    latency = _column(results, ("latency_seconds", "latency"), default=None)
    confidence = _column(results, ("confidence", "confidence_score"), default=None)
    rows = []
    for question, gold_sql, guess_sql, seconds, score in zip(
        questions.tolist(),
        expected_sql.tolist(),
        model_sql.tolist(),
        latency.tolist(),
        confidence.tolist(),
    ):
        if _is_missing(question) or not str(question).strip():
            continue
        note = ""
        try:
            gold = _execute(frames, gold_sql)
        except Exception as exc:
            gold = pd.DataFrame()
            note = "Expected SQL failed: {0}".format(exc)
        try:
            guess = _execute(frames, guess_sql)
            sql_error = ""
        except Exception as exc:
            guess = pd.DataFrame()
            sql_error = str(exc)
        gold_rows = _row_parts(gold)
        guess_rows = _row_parts(guess)
        if note:
            outcome = "sql_error"
        elif sql_error:
            outcome = "sql_error"
            note = sql_error
        elif _results_match(gold, guess):
            outcome = "correct"
        elif not _has_figure(guess_rows):
            outcome = "no_result"
        else:
            outcome = "wrong_value"
        rows.append(
            {
                "input_question": str(question).strip(),
                "outcome": outcome,
                "accurate": 1 if outcome == "correct" else 0,
                "latency_seconds": None if _is_missing(seconds) else float(seconds),
                "confidence": None if _is_missing(score) else float(score),
                "expected_preview": _preview(gold),
                "model_preview": _preview(guess),
                "note": note,
            }
        )
    return pd.DataFrame(rows)


def _percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def _summarize(detail):
    total = int(len(detail))
    correct = int(detail["accurate"].sum()) if total else 0
    accuracy = (correct / total) if total else 0.0
    labels = ["correct", "wrong_value", "no_result", "sql_error"]
    counts = {label: int((detail["outcome"] == label).sum()) if total else 0 for label in labels}
    # Every question has a gold result, so the actual class is "correct answer".
    matrix = {
        "actual_correct": {
            "predicted_correct": counts["correct"],
            "predicted_incorrect": total - counts["correct"],
        }
    }
    latency = [value for value in detail["latency_seconds"].tolist() if not _is_missing(value)] if total else []
    confidence = [value for value in detail["confidence"].tolist() if not _is_missing(value)] if total else []
    bins = []
    if confidence:
        for low, high in ((0.0, 0.5), (0.5, 0.8), (0.8, 1.01)):
            chosen = detail[detail["confidence"].between(low, high, inclusive="left")]
            if chosen.empty:
                continue
            bins.append(
                {
                    "confidence_from": low,
                    "confidence_to": min(high, 1.0),
                    "questions": int(len(chosen)),
                    "accuracy": float(chosen["accurate"].mean()),
                }
            )
    summary = {
        "questions": total,
        "correct": correct,
        "accuracy": round(accuracy, 4),
        "confusion_matrix": matrix,
        "outcome_counts": counts,
        "latency_seconds": {
            "questions_timed": len(latency),
            "mean": None if not latency else round(sum(latency) / len(latency), 3),
            "median": None if not latency else round(_percentile(latency, 0.5), 3),
            "p95": None if not latency else round(_percentile(latency, 0.95), 3),
        },
        "confidence": {
            "questions_scored": len(confidence),
            "mean": None if not confidence else round(sum(confidence) / len(confidence), 3),
            "accuracy_by_bin": bins,
        },
    }
    return summary


def _print_summary(summary):
    print("Questions: {0}".format(summary["questions"]))
    print(
        "Accuracy: {0}/{1} = {2:.1%}".format(
            summary["correct"], summary["questions"], summary["accuracy"]
        )
    )
    matrix = summary["confusion_matrix"]["actual_correct"]
    print("Confusion matrix")
    print("                 predicted_correct  predicted_incorrect")
    print(
        "actual_correct   {0:<19}{1}".format(
            matrix["predicted_correct"], matrix["predicted_incorrect"]
        )
    )
    print("Outcome counts: {0}".format(summary["outcome_counts"]))
    timing = summary["latency_seconds"]
    if timing["questions_timed"]:
        print(
            "Latency seconds: mean {0}, median {1}, p95 {2}".format(
                timing["mean"], timing["median"], timing["p95"]
            )
        )
    else:
        print("Latency was not recorded on this result file.")
    scored = summary["confidence"]
    if scored["questions_scored"]:
        print("Mean confidence: {0}".format(scored["mean"]))
        print("Accuracy by confidence bin: {0}".format(scored["accuracy_by_bin"]))
    else:
        print("Confidence was not recorded on this result file.")


def score_results(results, frames=None):
    frames = frames or _load_frames()
    detail = _score_frame(results, frames)
    return detail, _summarize(detail)


def _local_main():
    path, frame = _latest_results()
    print("Scoring", path)
    print("Columns:", list(frame.columns))
    detail, summary = score_results(frame)
    _print_summary(summary)
    out = path.with_name(path.stem + "_metrics.csv")
    detail.to_csv(out, index=False)
    print("Wrote", out)
    return detail, summary


def _dataiku_main():
    import os
    from dataiku import recipe as dku_recipe
    import dataiku

    def norm(name):
        return "".join(ch for ch in (name or "").lower() if ch.isalnum())

    def short(name):
        text = str(name or "").strip()
        return text.split(".")[-1] if "." in text else text

    def unique(names):
        seen = set()
        out = []
        for name in names:
            if name and name not in seen:
                seen.add(name)
                out.append(name)
        return out

    def declared(kind):
        names = []
        roles = ("main", "input", "inputs", "datasets") if kind == "in" else ("main", "output", "outputs")
        getter = dku_recipe.get_input_names_for_role if kind == "in" else dku_recipe.get_output_names_for_role
        for role in roles:
            try:
                names.extend(getter(role) or [])
            except Exception:
                pass
        extra = getattr(
            dku_recipe,
            "get_incoming_names" if kind == "in" else "get_outgoing_names",
            None,
        )
        try:
            if extra is not None:
                names.extend(extra() or [])
        except Exception:
            pass
        return unique(names)

    inputs = declared("in")
    outputs = declared("out")
    result_name = ""
    result_frame = None
    facts = {}
    for name in inputs:
        table = short(name)
        if table in FACT_TABLES:
            facts[table] = dataiku.Dataset(name).get_dataframe()
            continue
        frame = dataiku.Dataset(name).get_dataframe()
        print("Input", name, "columns:", list(frame.columns))
        if _has_model_sql(frame):
            result_name = name
            result_frame = frame
    if result_frame is None:
        path, result_frame = _latest_results()
        print(
            "None of the recipe inputs contain LLM_generated_SQL. "
            "semantic_validation_llm (4) is a metrics file, so its SQL column is empty. "
            "Scoring {0} instead.".format(path)
        )
    else:
        print("Scoring dataset", result_name)
    if not facts:
        facts = _load_frames()
    output = ""
    for name in outputs:
        if norm(short(name)) in {"semanticvalidationmetrics", "semanticvalidationeval"}:
            output = name
    if not output and outputs:
        output = outputs[0]
    if not output:
        raise RuntimeError(
            "Declare output semantic_validation_metrics. Inputs={0} outputs={1}".format(
                inputs, outputs
            )
        )
    detail, summary = score_results(result_frame, facts)
    _print_summary(summary)
    dataiku.Dataset(output).write_with_schema(detail)
    print({"ok": True, "output": output, "accuracy": summary["accuracy"]})


import os

try:
    import dataiku  # noqa: F401
except Exception:
    dataiku = None

if dataiku is not None and os.environ.get("DKU_CURRENT_PROJECT_KEY"):
    _dataiku_main()
elif os.environ.get("AIBI_EVAL_IMPORT_ONLY") != "1":
    _local_main()
