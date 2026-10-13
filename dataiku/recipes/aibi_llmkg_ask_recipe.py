# -*- coding: utf-8 -*-
"""Reusable Dataiku recipe. Paste this whole file into the Python recipe.

Same recipe for every project. Do not edit it per subject area.

Per project, change only:
  Project variables
    AIBI_DOMAIN            library folder onboarding/domains/<this value>
    AIBI_LLM_CONNECTION    Opus LLM Mesh connection id
  Flow inputs
    one or more fact datasets
    one question dataset with column input_question
    optional: the previous knowledge_graph dataset
  Flow outputs
    a results dataset
    a dataset named knowledge_graph

The library must already contain the aibi package (aibi/llmkg/engine.py and aibi/tabular.py).
Upload each input in the Flow as a dataset. CSV, Excel, and Parquet are all fine.
Dataiku reads the file. This recipe sees a table either way.
Excel needs openpyxl in the code environment. Parquet needs pyarrow.

You do not create a domain folder to get started. The recipe learns columns
from the uploaded tables and stores what it learns in the knowledge_graph
dataset. Add onboarding/domains/<AIBI_DOMAIN>/joins.yaml only when two tables
must be joined and you want to name the columns that link them.

The knowledge_graph output is read on the next run when you also connect
it as an input, so intent, metrics, and SQL patterns carry forward.
"""

from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path

import dataiku
import pandas as pd
from dataiku import recipe as dku_recipe

VARS = dataiku.get_custom_variables()
QUESTION_COLUMNS = ("input_question", "question", "Question")
EXPECTED_COLUMNS = ("Expected_SQL_Query", "expected_sql_query", "expected_sql")
RESULT_COLUMNS = [
    "question",
    "Expected_SQL_Query",
    "LLM_generated_SQL",
    "LLM_generated_answer",
    "intent",
    "confidence",
    "metrics_json",
    "calculations_json",
    "latency_seconds",
    "kg_nodes",
    "kg_edges",
    "kg_episodes",
]


def _norm(name):
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def _unique(names):
    seen = []
    for name in names:
        if name and name not in seen:
            seen.append(name)
    return seen


def _declared(kind):
    names = []
    roles = ("main", "input", "inputs", "datasets") if kind == "in" else ("main", "output", "outputs")
    getter = dku_recipe.get_input_names_for_role if kind == "in" else dku_recipe.get_output_names_for_role
    extra_name = "get_incoming_names" if kind == "in" else "get_outgoing_names"
    for role in roles:
        try:
            names.extend(getter(role) or [])
        except Exception:
            pass
    extra = getattr(dku_recipe, extra_name, None)
    if extra is not None:
        try:
            names.extend(extra() or [])
        except Exception:
            pass
    return _unique(names)


def _find_column(frame, names):
    lookup = {str(column).lower(): column for column in frame.columns}
    for name in names:
        found = lookup.get(name.lower())
        if found is not None:
            return frame[found]
    return None


def _coerce_flags(frame):
    out = frame.copy()
    true_tokens = {"true", "t", "yes", "y", "1"}
    false_tokens = {"false", "f", "no", "n", "0"}
    for col in out.columns:
        series = out[col]
        if pd.api.types.is_bool_dtype(series):
            out[col] = series.astype("int64")
            continue
        if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
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
                    if value is None or (isinstance(value, float) and pd.isna(value))
                    else 1 if str(value).strip().lower() in true_tokens else 0
                )
            )
    return out


def _is_questions(name, frame):
    key = _norm(name)
    named = key in {"questions", "semanticvalidationquestions", "kpicubevalidation"} or key.endswith("questions")
    has_question = _find_column(frame, QUESTION_COLUMNS) is not None
    if named and has_question:
        return True
    return _find_column(frame, ("input_question",)) is not None and "record_type" not in frame.columns


def _is_graph(name, frame):
    key = _norm(name)
    if "knowledgegraph" in key:
        return True
    return "record_type" in frame.columns and "payload" in frame.columns


def _safe_table(name):
    text = str(name or "")
    if text and text.replace("_", "a").isalnum() and not text[0].isdigit():
        return text
    raise RuntimeError(
        "Dataset {0} cannot be a SQL table name. Rename it to letters, numbers, and underscores.".format(name)
    )


def _read_input(name):
    """Read a Flow dataset. Dataiku already accepts CSV, Excel, and Parquet uploads."""
    dataset = dataiku.Dataset(name)
    try:
        frame = dataset.get_dataframe()
        if frame is not None and len(frame.columns):
            print("Loaded", name, "rows", len(frame), "through Dataiku")
            return frame
    except Exception as exc:
        print("Dataiku reader failed for", name, ":", exc)
    try:
        from aibi.tabular import read_table, read_tables_in
    except Exception as exc:
        raise RuntimeError(
            "Could not read {0}. Upload it in the Flow as CSV, Excel, or Parquet. {1}".format(name, exc)
        )
    try:
        info = dataset.get_location_info() or {}
    except Exception as exc:
        raise RuntimeError(
            "Could not read {0}. Upload it in the Flow as CSV, Excel, or Parquet. {1}".format(name, exc)
        )
    details = info.get("info") or {}
    root = details.get("path")
    if not root:
        raise RuntimeError(
            "Could not read {0}. Upload it in the Flow as CSV, Excel, or Parquet.".format(name)
        )
    folder = Path(root)
    chosen = details.get("file") or details.get("filename")
    candidate = folder / chosen if chosen and folder.is_dir() else folder
    if candidate.is_file():
        frame = read_table(candidate)
        print("Loaded file", candidate, "as", name, "rows", len(frame))
        return frame
    found = read_tables_in(folder) if folder.is_dir() else {}
    if not found:
        raise RuntimeError(
            "Could not read {0}. Upload a CSV, Excel, or Parquet file. "
            "Excel needs openpyxl in the code environment. Parquet needs pyarrow.".format(name)
        )
    if len(found) == 1:
        frame = next(iter(found.values()))
        print("Loaded", name, "rows", len(frame), "from", folder)
        return frame
    frame = pd.concat(list(found.values()), ignore_index=True)
    print("Loaded", len(found), "files for", name, "rows", len(frame))
    return frame


def _split_inputs():
    frames = {}
    questions = None
    graph_frame = None
    for name in _declared("in"):
        frame = _read_input(name)
        print("Input", name, "rows", len(frame), "columns", list(frame.columns))
        if _is_graph(name, frame):
            graph_frame = frame
            continue
        if questions is None and _is_questions(name, frame):
            questions = frame
            continue
        frames[_safe_table(name)] = _coerce_flags(frame)
    if not frames:
        raise RuntimeError("Connect at least one fact dataset. The question dataset is separate.")
    if questions is None:
        raise RuntimeError("Connect a question dataset with column input_question.")
    return frames, questions, graph_frame


def _split_outputs():
    results = ""
    graph_out = ""
    for name in _declared("out"):
        if "knowledgegraph" in _norm(name):
            graph_out = name
        elif not results:
            results = name
    if not results:
        raise RuntimeError("Declare a results output dataset.")
    return results, graph_out


def _load_previous_graph(domain, graph_frame):
    from aibi.llmkg.graph import KnowledgeGraph

    graph = KnowledgeGraph(domain)
    graph.nodes = {}
    graph.edges = []
    graph.episodes = []
    if graph_frame is None or graph_frame.empty or "payload" not in graph_frame.columns:
        print("Knowledge graph starts empty for domain", domain)
        return graph
    for row in graph_frame.to_dict(orient="records"):
        raw = row.get("payload")
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        kind = str(row.get("record_type") or "")
        if kind == "node" and payload.get("id"):
            graph.nodes[payload["id"]] = payload
        elif kind == "edge":
            graph.edges.append(payload)
        elif kind == "episode":
            graph.episodes.append(payload)
    print(
        "Loaded knowledge graph",
        domain,
        "nodes",
        len(graph.nodes),
        "edges",
        len(graph.edges),
        "episodes",
        len(graph.episodes),
    )
    return graph


def _graph_frame(graph):
    payload = graph.to_dict()
    rows = []
    for node in payload.get("nodes") or []:
        rows.append({"record_type": "node", "payload": json.dumps(node, default=str)})
    for edge in payload.get("edges") or []:
        rows.append({"record_type": "edge", "payload": json.dumps(edge)})
    for episode in payload.get("episodes") or []:
        rows.append({"record_type": "episode", "payload": json.dumps(episode, default=str)})
    if not rows:
        return pd.DataFrame(columns=["record_type", "payload"])
    return pd.DataFrame(rows)


def _resolve_opus():
    explicit = VARS.get("AIBI_LLM_CONNECTION") or os.environ.get("AIBI_LLM_CONNECTION")
    if explicit:
        return str(explicit)
    project = dataiku.api_client().get_default_project()
    found = []
    for method in ("list_llms", "list_available_llms"):
        fn = getattr(project, method, None)
        if not callable(fn):
            continue
        try:
            for item in fn() or []:
                if isinstance(item, str):
                    found.append(item)
                elif isinstance(item, dict):
                    found.append(str(item.get("id") or item.get("llmId") or item.get("name") or ""))
            break
        except Exception as exc:
            print("Could not list LLMs via", method, exc)
    found = [item for item in found if item]
    opus = [item for item in found if "opus" in item.lower()]
    if not opus:
        raise RuntimeError("No Opus LLM Mesh connection. Set AIBI_LLM_CONNECTION. Available: {0}".format(found))
    return opus[0]


def _confidence(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 1 and number <= 100:
        number = number / 100.0
    return min(1.0, max(0.0, number))


DOMAIN = str(VARS.get("AIBI_DOMAIN") or os.environ.get("AIBI_DOMAIN") or "generic_cube").strip()
OPUS_ID = _resolve_opus()
os.environ["AIBI_LLM_CONNECTION"] = OPUS_ID
os.environ["NLQ_LLM_CONNECTION"] = OPUS_ID
os.environ["AIBI_LLM_MODE"] = "mesh"
print("Domain:", DOMAIN)
print("LLM Mesh:", OPUS_ID)

from aibi.llmkg.engine import ask_with_graph  # noqa: E402

FRAMES, QUESTIONS, PREVIOUS_GRAPH = _split_inputs()
RESULTS_DS, GRAPH_DS = _split_outputs()
print("Fact tables:", list(FRAMES))
print("Results output:", RESULTS_DS)
print("Graph output:", GRAPH_DS or "(none)")
if PREVIOUS_GRAPH is None and GRAPH_DS:
    try:
        existing = dataiku.Dataset(GRAPH_DS).get_dataframe()
        if existing is not None and not existing.empty and "payload" in existing.columns:
            PREVIOUS_GRAPH = existing
            print("Read previous knowledge graph from", GRAPH_DS, "rows", len(existing))
    except Exception as exc:
        print("No previous knowledge graph yet:", exc)

GRAPH = _load_previous_graph(DOMAIN, PREVIOUS_GRAPH)
QUESTION_SERIES = _find_column(QUESTIONS, QUESTION_COLUMNS)
EXPECTED_SERIES = _find_column(QUESTIONS, EXPECTED_COLUMNS)
if EXPECTED_SERIES is None:
    EXPECTED_SERIES = pd.Series([""] * len(QUESTIONS), index=QUESTIONS.index)

ROWS = []
for index, (question, expected_sql) in enumerate(zip(QUESTION_SERIES.tolist(), EXPECTED_SERIES.tolist())):
    if question is None or (isinstance(question, float) and pd.isna(question)):
        continue
    question = str(question).strip()
    if not question:
        continue
    expected = ""
    if expected_sql is not None and not (isinstance(expected_sql, float) and pd.isna(expected_sql)):
        expected = str(expected_sql)
    started = time.perf_counter()
    intent = ""
    confidence = None
    metrics = []
    calculations = []
    llm_sql = ""
    llm_answer = ""
    try:
        result = ask_with_graph(
            question,
            domain=DOMAIN,
            frames=FRAMES,
            graph=GRAPH,
            persist=False,
        )
        intent = str(result.get("intent") or "")
        confidence = _confidence(result.get("confidence"))
        metrics = result.get("metrics") or []
        calculations = result.get("calculations") or []
        llm_sql = str(result.get("sql_query") or "")
        llm_answer = str(result.get("answer") or "")
        print(index, "llm_kg", intent, "nodes", len(GRAPH.nodes), (llm_answer or "")[:120])
    except Exception as exc:
        llm_answer = "ERROR: {0}".format(exc)
        print("ERROR", index, exc)
        traceback.print_exc()
        GRAPH.record_episode(
            {
                "question_id": "q.err.{0}".format(index),
                "question": question,
                "intent": "error",
                "metrics": [],
                "calculations": [],
                "new_terms": [],
                "sql": llm_sql,
                "status": "error",
                "answer_excerpt": llm_answer[:400],
            }
        )
    ROWS.append(
        {
            "question": question,
            "Expected_SQL_Query": expected,
            "LLM_generated_SQL": llm_sql,
            "LLM_generated_answer": llm_answer,
            "intent": intent,
            "confidence": confidence,
            "metrics_json": json.dumps(metrics, default=str),
            "calculations_json": json.dumps(calculations, default=str),
            "latency_seconds": round(time.perf_counter() - started, 3),
            "kg_nodes": len(GRAPH.nodes),
            "kg_edges": len(GRAPH.edges),
            "kg_episodes": len(GRAPH.episodes),
        }
    )

if not ROWS:
    raise RuntimeError("The question dataset has no questions.")

dataiku.Dataset(RESULTS_DS).write_with_schema(pd.DataFrame(ROWS, columns=RESULT_COLUMNS))
if GRAPH_DS:
    dataiku.Dataset(GRAPH_DS).write_with_schema(_graph_frame(GRAPH))
print(
    json.dumps(
        {
            "ok": True,
            "domain": DOMAIN,
            "rows": len(ROWS),
            "llm": OPUS_ID,
            "answer_path": "llm_kg",
            "tables": list(FRAMES),
            "kg_nodes": len(GRAPH.nodes),
            "kg_edges": len(GRAPH.edges),
            "kg_episodes": len(GRAPH.episodes),
        },
        indent=2,
    )
)
