# -*- coding: utf-8 -*-
"""Dataiku Python recipe — paste this entire file into the recipe editor.

Folder layout this recipe belongs to:
  ProjectSemantic/ProjectSemantic/
    aibi/factory/grounding.py
    dataiku/recipes/aibi_semantic_validation_recipe.py

In the recipe Inputs/Outputs panel declare:
  Inputs:
    sf_accounts
    sf_opportunities
    sf_service_cases
    coldchain_shipments
    temperature_excursions
    semantic_validation_questions
  Output:
    semantic_validation_llm

semantic_validation_questions columns: input_question, Expected_SQL_Query
semantic_validation_llm columns:
  input_question, Expected_SQL_Query, LLM_generated_SQL, LLM_generated_answer,
  latency_seconds, confidence

Source files for the five fact tables live in:
  c:\\Users\\BharadNa\\Downloads\\data\\data
If those Dataiku inputs are not declared, the recipe loads the CSVs from that folder.
Questions and the output still have to be Dataiku datasets.

SQL runs in SQLite. Boolean columns compare with 1 and 0.
Join keys: account_id, shipment_id, opportunity_id.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import traceback
from pathlib import Path
import sys

import dataiku
import pandas as pd
from dataiku import recipe as dku_recipe

vars_map = dataiku.get_custom_variables()

FACT_TABLES = (
    "sf_accounts",
    "sf_opportunities",
    "sf_service_cases",
    "coldchain_shipments",
    "temperature_excursions",
)
QUESTION_NAMES = {"semanticvalidationquestions", "semanticvalidationquestion"}
OUTPUT_NAMES = {"semanticvalidationllm"}
DATA_DIRS = (
    os.environ.get("AIBI_DATA_DIR") or "",
    r"c:\Users\BharadNa\Downloads\data\data",
    r"c:\Users\BharadNa\Downloads\data",
)
JOIN_NOTES = """
Join keys (use these; do not invent others):
- sf_accounts.account_id = sf_opportunities.account_id
- sf_accounts.account_id = sf_service_cases.account_id
- sf_accounts.account_id = coldchain_shipments.account_id
- sf_accounts.account_id = temperature_excursions.account_id
- coldchain_shipments.shipment_id = sf_service_cases.shipment_id
- coldchain_shipments.shipment_id = temperature_excursions.shipment_id
- coldchain_shipments.opportunity_id = sf_opportunities.opportunity_id
Boolean flags are integers 1 and 0. Write is_won = 1, resolved_flag = 0, is_gxp_regulated = 1. Never compare them to the text 'True' or 'False'.
A rate is SUM(numerator) / NULLIF(SUM(denominator), 0) after GROUP BY.
Which group is highest, then the top N inside it: filter to the winning group first.
""".strip()


class _LocalColumn:
    """Column description used when aibi/factory/grounding.py is not installed."""

    def __init__(self, name, values):
        self.name = name
        self.values = values


def _local_profile_frame(frame, notes=None):
    profiles = []
    for col in frame.columns:
        values = frame[col].dropna().astype(str).drop_duplicates().head(50).tolist()
        profiles.append(_LocalColumn(str(col), values))
    return profiles


def _local_schema_text(profiles, question, table="KPI_data", aliases=None):
    lines = ["Table: {0}".format(table)]
    for profile in profiles:
        lines.append("- {0}; example members: {1}".format(profile.name, profile.values[:10]))
    return "\n".join(lines)


def _normalize_bool_literals(sql):
    """SQLite stores these flags as 1 and 0. 'True' and 'False' match nothing."""
    text = str(sql or "")
    text = re.sub(r"(?i)(=\s*)(?:'True'|\"True\"|\btrue\b)", r"\g<1>1", text)
    text = re.sub(r"(?i)(=\s*)(?:'False'|\"False\"|\bfalse\b)", r"\g<1>0", text)
    text = re.sub(r"(?i)\bIS\s+TRUE\b", "= 1", text)
    text = re.sub(r"(?i)\bIS\s+FALSE\b", "= 0", text)
    return text


def _local_prepare_sql(sql_query, profiles, question, aliases=None):
    return _normalize_bool_literals(sql_query)


def _local_references_unavailable(sql_query, profiles):
    return False


def _local_result_is_vacuous(frame):
    return frame is None or frame.empty


def _local_diagnose(sql_query, profiles, result_frame):
    if result_frame is None or result_frame.empty:
        return "The query returned no rows; verify filters against the catalog members."
    return "The query completed successfully."


def _local_load_semantic_hints(roots):
    return {}, []


def _load_grounding():
    """Load aibi/factory/grounding.py, or use local profiles if it is absent."""
    names = (
        "diagnose",
        "load_semantic_hints",
        "prepare_sql",
        "profile_frame",
        "references_unavailable",
        "result_is_vacuous",
        "schema_text",
    )
    fallback = (
        _local_diagnose,
        _local_load_semantic_hints,
        _local_prepare_sql,
        _local_profile_frame,
        _local_references_unavailable,
        _local_result_is_vacuous,
        _local_schema_text,
    )
    try:
        from aibi.factory import grounding as grounding_mod  # noqa: WPS433
    except Exception:
        grounding_mod = None
        try:
            import importlib.util

            candidates = []
            for entry in list(sys.path):
                candidates.append(Path(entry) / "aibi" / "factory" / "grounding.py")
            here = Path.cwd()
            candidates.extend(
                (root / "aibi" / "factory" / "grounding.py")
                for root in [here, *list(here.parents)[:6]]
            )
            grounding_path = next((path for path in candidates if path.exists()), None)
            if grounding_path is not None:
                spec = importlib.util.spec_from_file_location(
                    "aibi_factory_grounding", str(grounding_path)
                )
                grounding_mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(grounding_mod)
        except Exception as exc:
            print("Grounding module not loaded, using local profiles:", exc)
            grounding_mod = None
    if grounding_mod is None:
        print("Using local column profiles. aibi/factory/grounding.py was not imported.")
        return fallback
    return tuple(getattr(grounding_mod, name) for name in names)


(
    _diagnose,
    _load_semantic_hints,
    _prepare_sql,
    _profile_frame,
    _references_unavailable,
    _result_is_vacuous,
    _schema_text,
) = _load_grounding()
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _norm(name):
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _short(name):
    text = str(name or "").strip()
    if "." in text:
        text = text.split(".")[-1]
    return text


def _unique(names):
    seen = set()
    out = []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _declared_inputs():
    names = []
    for role in ("main", "input", "inputs", "datasets"):
        try:
            names.extend(dku_recipe.get_input_names_for_role(role) or [])
        except Exception:
            pass
    try:
        names.extend(dku_recipe.get_incoming_names() or [])
    except Exception:
        pass
    return _unique(names)


def _declared_outputs():
    names = []
    for role in ("main", "output", "outputs"):
        try:
            names.extend(dku_recipe.get_output_names_for_role(role) or [])
        except Exception:
            pass
    try:
        names.extend(dku_recipe.get_outgoing_names() or [])
    except Exception:
        pass
    return _unique(names)


def _pick(names, aliases):
    for name in names:
        if _norm(_short(name)) in aliases or _norm(name) in aliases:
            return name
    return ""


def _resolve_datasets():
    inputs = _declared_inputs()
    outputs = _declared_outputs()
    print("Declared recipe inputs:", inputs)
    print("Declared recipe outputs:", outputs)
    questions = _pick(inputs, QUESTION_NAMES)
    output = _pick(outputs, OUTPUT_NAMES) or (outputs[0] if outputs else "")
    facts = [name for name in inputs if name != questions]
    missing = []
    if not questions:
        missing.append("semantic_validation_questions")
    if not output:
        missing.append("semantic_validation_llm")
    if missing:
        raise RuntimeError(
            "Declare these datasets in the recipe Inputs/Outputs panel: {0}. "
            "Currently declared inputs={1} outputs={2}".format(missing, inputs, outputs)
        )
    return facts, questions, output


def _question_series(frame):
    for col in ("input_question", "question", "Question"):
        if col in frame.columns:
            return frame[col]
    raise RuntimeError(
        "semantic_validation_questions must have column 'input_question'. Found: {0}".format(
            list(frame.columns)
        )
    )


def _expected_sql_series(frame):
    for col in ("Expected_SQL_Query", "expected_sql_query", "expected_sql"):
        if col in frame.columns:
            return frame[col]
    return pd.Series([""] * len(frame), index=frame.index)


def _load_folder_frames(already):
    loaded = {_short(name) for name in already}
    frames = {}
    for folder in DATA_DIRS:
        if not folder:
            continue
        root = Path(folder)
        if not root.is_dir():
            continue
        try:
            from aibi.tabular import SUFFIXES, read_table
        except Exception:
            SUFFIXES = (".csv",)
            read_table = pd.read_csv
        for path in sorted(root.iterdir()):
            if not path.is_file() or path.suffix.lower() not in SUFFIXES:
                continue
            table = path.stem
            if table in loaded or _norm(table) in QUESTION_NAMES:
                continue
            if table not in FACT_TABLES and loaded:
                continue
            frames[table] = read_table(path)
            print("Loaded table", path, "as", table, "rows", len(frames[table]))
        if frames:
            break
    return frames


def _llm_id(item):
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("id") or item.get("llmId") or item.get("name") or "")
    return str(getattr(item, "id", "") or "")


def _list_mesh_llms():
    client = dataiku.api_client()
    project = client.get_default_project()
    for method in ("list_llms", "list_available_llms"):
        fn = getattr(project, method, None)
        if not callable(fn):
            continue
        try:
            return fn() or []
        except Exception as exc:
            print("Could not list LLMs via", method, exc)
    return []


def _resolve_opus_connection():
    explicit = vars_map.get("AIBI_LLM_CONNECTION") or os.environ.get("AIBI_LLM_CONNECTION")
    if explicit:
        return str(explicit)
    ids = [_llm_id(item) for item in _list_mesh_llms()]
    ids = [item for item in ids if item]
    print("Available LLM Mesh connections:", ids)
    opus = [item for item in ids if "opus" in item.lower()]
    if opus:
        return opus[0]
    raise RuntimeError(
        "No Opus LLM Mesh connection found. Set project variable AIBI_LLM_CONNECTION. "
        "Available: {0}".format(ids)
    )


def _get_opus_llm(connection_id):
    project = dataiku.api_client().get_default_project()
    try:
        return project.get_llm(connection_id)
    except Exception as exc:
        raise RuntimeError(
            "project.get_llm({0!r}) failed: {1}".format(connection_id, exc)
        )


def _mesh_complete(llm, system_instruction, user_prompt):
    completion = llm.new_completion()
    if system_instruction:
        completion.with_message(system_instruction, role="system")
    completion.with_message(user_prompt, role="user")
    try:
        if hasattr(completion, "settings"):
            completion.settings["temperature"] = 0.0
    except Exception:
        pass
    response = completion.execute()
    return getattr(response, "text", None) or str(response)


def _extract_json(text):
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(0))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _is_select_only(sql):
    text = (sql or "").strip().rstrip(";")
    if not text:
        return False
    if ";" in text:
        return False
    upper = text.upper()
    if not upper.startswith("SELECT") and not upper.startswith("WITH"):
        return False
    forbidden = (
        "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE",
        "MERGE", "CREATE", "GRANT", "REVOKE", "ATTACH", "PRAGMA",
    )
    return not any(re.search(r"\b{0}\b".format(word), upper) for word in forbidden)


def _run_sql(frames, sql):
    if not _is_select_only(sql):
        raise ValueError("Refusing non-SELECT SQL from the LLM.")
    with sqlite3.connect(":memory:") as conn:
        for name, frame in frames.items():
            frame.to_sql(name, conn, index=False, if_exists="replace")
        conn.execute("PRAGMA query_only = ON")
        return pd.read_sql_query(sql, conn)


def _preview(frame, limit=20):
    if frame is None or frame.empty:
        return {"columns": [], "rows": [], "n": 0}
    clipped = frame.head(limit)
    return {
        "columns": [str(c) for c in clipped.columns],
        "rows": json.loads(clipped.to_json(orient="records", date_format="iso")),
        "n": int(len(frame)),
    }


def _catalog(profiles_by_table, question, aliases):
    parts = [JOIN_NOTES, ""]
    for table, profiles in profiles_by_table.items():
        parts.append(_schema_text(profiles, question, table=table, aliases=aliases))
        parts.append("")
    return "\n".join(parts)


def _merged_profiles(profiles_by_table):
    merged = []
    seen = set()
    for profiles in profiles_by_table.values():
        if isinstance(profiles, dict):
            columns = list(profiles.values())
        else:
            columns = list(profiles)
        for column in columns:
            name = getattr(column, "name", None)
            if not name or name in seen:
                continue
            seen.add(name)
            merged.append(column)
    return merged


def _ask_opus(llm, question, frames, profiles_by_table, aliases):
    profiles = _merged_profiles(profiles_by_table)
    catalog = _catalog(profiles_by_table, question, aliases)
    table_list = ", ".join(frames)
    sql_prompt = (
        "You write one SQLite SELECT. Tables: {0}.\n"
        "Return JSON only with keys sql_query and rationale.\n"
        "Use only these tables and the columns in the catalog. Copy filter values exactly.\n\n"
        "Catalog:\n{1}\n\nQuestion:\n{2}\n"
    ).format(table_list, catalog, question)
    sql_raw = _mesh_complete(
        llm,
        "You are a careful analytics SQL generator. Output JSON only.",
        sql_prompt,
    )
    sql_payload = _extract_json(sql_raw)
    sql_query = str(sql_payload.get("sql_query") or "").strip()
    if not sql_query:
        raise RuntimeError("Opus did not return sql_query. Raw: {0}".format(sql_raw[:500]))
    sql_query = _normalize_bool_literals(
        _prepare_sql(sql_query, profiles, question, aliases=aliases)
    )

    try:
        result_frame = _run_sql(frames, sql_query)
        problem = ""
    except Exception as exc:
        result_frame = pd.DataFrame()
        problem = str(exc)
    if problem or _result_is_vacuous(result_frame) or _references_unavailable(sql_query, profiles):
        repair_prompt = (
            "Repair the SQLite SELECT. Use only these tables: {0}. "
            "Copy members exactly. Return JSON with sql_query and rationale.\n\n"
            "Question:\n{1}\n\nPrevious SQL:\n{2}\n\nProblem:\n{3}\n\nCatalog:\n{4}\n"
        ).format(
            table_list,
            question,
            sql_query,
            problem or _diagnose(sql_query, profiles, result_frame),
            catalog,
        )
        repaired_raw = _mesh_complete(
            llm,
            "You repair analytics SQL. Output JSON only.",
            repair_prompt,
        )
        repaired = str(_extract_json(repaired_raw).get("sql_query") or "").strip()
        if repaired:
            repaired = _normalize_bool_literals(
                _prepare_sql(repaired, profiles, question, aliases=aliases)
            )
            try:
                repaired_frame = _run_sql(frames, repaired)
            except Exception:
                repaired_frame = pd.DataFrame()
            if not _result_is_vacuous(repaired_frame) and not _references_unavailable(repaired, profiles):
                sql_query, result_frame = repaired, repaired_frame

    preview = _preview(result_frame)
    diagnosis = ""
    if _result_is_vacuous(result_frame) or _references_unavailable(sql_query, profiles):
        diagnosis = _diagnose(sql_query, profiles, result_frame)
    answer_prompt = (
        "Write a short business answer using ONLY the query result JSON.\n"
        "Return JSON only with keys answer and confidence.\n"
        "confidence is a number from 0 to 1: how sure you are that these rows answer the question.\n"
        "Use 0 when the result is empty or the measures are null.\n"
        "Do not use outside knowledge. If the result is empty or the measures are null, "
        "say the filter missed and quote the closest catalog members from the diagnosis. "
        "Do not invent figures.\n\n"
        "Question:\n{0}\n\nSQL:\n{1}\n\nResult:\n{2}\n\nDiagnosis:\n{3}\n"
    ).format(question, sql_query, json.dumps(preview), diagnosis)
    answer_raw = _mesh_complete(
        llm,
        "You are a BI analyst. Output JSON only. Stay faithful to the result rows.",
        answer_prompt,
    )
    answer_payload = _extract_json(answer_raw)
    answer = str(answer_payload.get("answer") or answer_raw).strip()
    confidence = answer_payload.get("confidence")
    try:
        confidence = float(confidence)
        if confidence > 1.0 and confidence <= 100.0:
            confidence = confidence / 100.0
        confidence = min(1.0, max(0.0, confidence))
    except (TypeError, ValueError):
        confidence = None
    return sql_query, answer, confidence


FACT_INPUTS, QUESTIONS_DS, OUTPUT_DS = _resolve_datasets()
print("Using questions input:", QUESTIONS_DS)
print("Using output:", OUTPUT_DS)

os.environ["AIBI_FORCE_LLM"] = "true"
os.environ["AIBI_ENABLE_LLM_FALLBACK"] = "true"
os.environ["NLQ_LLM_MODE"] = "mesh"
os.environ["NLQ_LLM_MODEL_ID"] = str(
    vars_map.get("AIBI_LLM_MODEL_ID") or os.environ.get("NLQ_LLM_MODEL_ID") or "claude-opus"
)

OPUS_ID = _resolve_opus_connection()
os.environ["NLQ_LLM_CONNECTION"] = OPUS_ID
os.environ["AIBI_LLM_CONNECTION"] = OPUS_ID
print("Using LLM Mesh:", OPUS_ID)
opus_llm = _get_opus_llm(OPUS_ID)

frames = {}
for dataset_name in FACT_INPUTS:
    table = _short(dataset_name)
    if _norm(table) in QUESTION_NAMES:
        continue
    frame = dataiku.Dataset(dataset_name).get_dataframe()
    frames[table] = frame
    print("Dataset", dataset_name, "table", table, "rows", len(frame))

for table, frame in _load_folder_frames(frames).items():
    frames[table] = frame

missing_tables = [name for name in FACT_TABLES if name not in frames]
if missing_tables:
    raise RuntimeError(
        "Missing fact tables {0}. Add them as recipe inputs, or place the CSVs in "
        "c:\\Users\\BharadNa\\Downloads\\data\\data. Loaded: {1}".format(missing_tables, list(frames))
    )
for table, frame in frames.items():
    if frame.empty:
        raise RuntimeError("Table '{0}' is empty.".format(table))

_hint_roots = []
try:
    _hint_roots.append(Path(__file__).resolve().parents[2])
except NameError:
    pass
_hint_roots.append(Path.cwd())
_notes, _aliases = _load_semantic_hints(_hint_roots)
profiles_by_table = {}
for table, frame in frames.items():
    profiles_by_table[table] = _profile_frame(frame, notes=_notes)
    counted = profiles_by_table[table]
    if isinstance(counted, dict):
        counted = counted.values()
    print(table, "attributes with members:", sum(1 for col in counted if getattr(col, "values", None)))

q_frame = dataiku.Dataset(QUESTIONS_DS).get_dataframe()
q_col = _question_series(q_frame)
sql_col = _expected_sql_series(q_frame)

rows = []
for i, (question, expected_sql) in enumerate(zip(q_col.tolist(), sql_col.tolist())):
    if question is None or (isinstance(question, float) and pd.isna(question)):
        continue
    question = str(question).strip()
    if not question:
        continue
    expected = ""
    if expected_sql is not None and not (
        isinstance(expected_sql, float) and pd.isna(expected_sql)
    ):
        expected = str(expected_sql)
    llm_sql = ""
    llm_answer = ""
    confidence = None
    started = time.perf_counter()
    try:
        llm_sql, llm_answer, confidence = _ask_opus(
            opus_llm, question, frames, profiles_by_table, _aliases
        )
        print(i, "opus", OPUS_ID, (llm_answer or "")[:120])
    except Exception as exc:
        llm_answer = "ERROR: {0}".format(exc)
        print("ERROR", i, exc)
        traceback.print_exc()
    latency_seconds = round(time.perf_counter() - started, 3)
    rows.append(
        {
            "input_question": question,
            "Expected_SQL_Query": expected,
            "LLM_generated_SQL": llm_sql,
            "LLM_generated_answer": llm_answer,
            "latency_seconds": latency_seconds,
            "confidence": confidence,
        }
    )

if not rows:
    raise RuntimeError("No non-empty input_question values in semantic_validation_questions.")

out_df = pd.DataFrame(
    rows,
    columns=[
        "input_question",
        "Expected_SQL_Query",
        "LLM_generated_SQL",
        "LLM_generated_answer",
        "latency_seconds",
        "confidence",
    ],
)
dataiku.Dataset(OUTPUT_DS).write_with_schema(out_df)
print(json.dumps({"ok": True, "rows": len(out_df), "llm": OPUS_ID, "output": OUTPUT_DS, "tables": list(frames)}, indent=2))
