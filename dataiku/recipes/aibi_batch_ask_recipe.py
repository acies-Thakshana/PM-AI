# -*- coding: utf-8 -*-
"""Dataiku Python recipe — paste this entire file into the existing recipe.

In the recipe Inputs/Outputs panel you MUST declare:
  Inputs:  KPI_data, kpi_cube_validation
  Output:  kpi_cube_validation_llm_results

kpi_cube_validation columns: input_question, Expected_SQL_Query
Output columns: question, Expected_SQL_Query, LLM_generated_SQL, LLM_generated_answer

Every answer comes from the project LLM Mesh connection whose id contains "opus".
SQL is grounded in the live table: real members, empty columns, and column notes.
Override with project variable AIBI_LLM_CONNECTION if auto-pick fails.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import traceback

import dataiku
import pandas as pd
from dataiku import recipe as dku_recipe

from pathlib import Path
import sys

vars_map = dataiku.get_custom_variables()


def _load_grounding():
    """Load aibi/factory/grounding.py from the project library."""
    names = (
        "diagnose",
        "load_semantic_hints",
        "prepare_sql",
        "profile_frame",
        "references_unavailable",
        "result_is_vacuous",
        "schema_text",
    )
    try:
        from aibi.factory import grounding as grounding_mod  # noqa: WPS433
    except Exception:
        import importlib.util

        candidates = []
        for entry in list(sys.path):
            candidates.append(Path(entry) / "aibi" / "factory" / "grounding.py")
        here = Path.cwd()
        candidates.extend((root / "aibi" / "factory" / "grounding.py") for root in [here, *list(here.parents)[:4]])
        grounding_path = next((path for path in candidates if path.exists()), None)
        if grounding_path is None:
            raise ImportError(
                "aibi/factory/grounding.py was not found in the project library."
            )
        spec = importlib.util.spec_from_file_location("aibi_factory_grounding", str(grounding_path))
        grounding_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(grounding_mod)
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


def _pick(names, aliases, leftover):
    for name in names:
        if _norm(name) in aliases:
            return name
    if leftover:
        return leftover.pop(0)
    return ""


def _resolve_datasets():
    inputs = _declared_inputs()
    outputs = _declared_outputs()
    print("Declared recipe inputs:", inputs)
    print("Declared recipe outputs:", outputs)

    leftover = list(inputs)
    kpi = _pick(inputs, {"kpidata", "kpidataset"}, leftover)
    leftover = [n for n in leftover if n != kpi]
    questions = _pick(inputs, {"kpicubevalidation", "questions"}, leftover)
    leftover = [n for n in leftover if n != questions]
    if leftover and not kpi:
        kpi = leftover.pop(0)
    if leftover and not questions:
        questions = leftover.pop(0)

    output = ""
    for name in outputs:
        if _norm(name) == "kpicubevalidationllmresults":
            output = name
            break
    if not output and outputs:
        output = outputs[0]

    missing = []
    if not kpi:
        missing.append("KPI cube input (KPI_data)")
    if not questions:
        missing.append("questions input (kpi_cube_validation)")
    if not output:
        missing.append("output (kpi_cube_validation_llm_results)")
    if missing:
        raise RuntimeError(
            "Declare these datasets in the recipe Inputs/Outputs panel: {0}. "
            "Currently declared inputs={1} outputs={2}".format(missing, inputs, outputs)
        )
    return kpi, questions, output


def _question_series(frame):
    for col in ("input_question", "question", "Question"):
        if col in frame.columns:
            return frame[col]
    raise RuntimeError(
        "kpi_cube_validation must have column 'input_question'. Found: {0}".format(
            list(frame.columns)
        )
    )


def _expected_sql_series(frame):
    for col in ("Expected_SQL_Query", "expected_sql_query", "expected_sql"):
        if col in frame.columns:
            return frame[col]
    return pd.Series([""] * len(frame), index=frame.index)


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
        "No Opus LLM Mesh connection found. Open Project → LLM Mesh, copy the "
        "Opus connection id, then set project variable AIBI_LLM_CONNECTION. "
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


def _ident(name):
    raw = str(name or "").strip()
    if _SAFE_IDENT.match(raw):
        return raw
    return '"' + raw.replace('"', '""') + '"'


def _schema_block(frame):
    lines = []
    for col in frame.columns:
        dtype = str(frame[col].dtype)
        sample = frame[col].dropna().astype(str).head(3).tolist()
        lines.append(
            "- {0} ({1}); samples={2}".format(_ident(col), dtype, sample)
        )
    return "\n".join(lines)


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


def _run_sql(frame, sql):
    if not _is_select_only(sql):
        raise ValueError("Refusing non-SELECT SQL from the LLM.")
    with sqlite3.connect(":memory:") as conn:
        frame.to_sql("KPI_data", conn, index=False, if_exists="replace")
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


def _ask_opus(llm, question, kpi_frame, profiles, aliases):
    catalog = _schema_text(profiles, question, table="KPI_data", aliases=aliases)
    sql_prompt = (
        "You write SQLite SQL for table KPI_data only.\n"
        "Return JSON only with keys sql_query and rationale.\n"
        "Use the catalog. Copy filter values exactly. Do not reference omitted columns.\n\n"
        "Catalog:\n{0}\n\nQuestion:\n{1}\n"
    ).format(catalog, question)
    sql_raw = _mesh_complete(
        llm,
        "You are a careful analytics SQL generator. Output JSON only.",
        sql_prompt,
    )
    sql_payload = _extract_json(sql_raw)
    sql_query = str(sql_payload.get("sql_query") or "").strip()
    if not sql_query:
        raise RuntimeError("Opus did not return sql_query. Raw: {0}".format(sql_raw[:500]))
    sql_query = _prepare_sql(sql_query, profiles, question, aliases=aliases)

    try:
        result_frame = _run_sql(kpi_frame, sql_query)
        problem = ""
    except Exception as exc:
        result_frame = pd.DataFrame()
        problem = str(exc)
    if problem or _result_is_vacuous(result_frame) or _references_unavailable(sql_query, profiles):
        repair_prompt = (
            "Repair the SQLite SELECT. Use only the catalog. Copy members exactly. "
            "Do not reference omitted columns. Return JSON with sql_query and rationale.\n\n"
            "Question:\n{0}\n\nPrevious SQL:\n{1}\n\nProblem:\n{2}\n\nCatalog:\n{3}\n"
        ).format(
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
            repaired = _prepare_sql(repaired, profiles, question, aliases=aliases)
            try:
                repaired_frame = _run_sql(kpi_frame, repaired)
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
        "Return JSON only with key answer.\n"
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
    return sql_query, answer


KPI_INPUT, QUESTIONS_DS, OUTPUT_DS = _resolve_datasets()
print("Using KPI input:", KPI_INPUT)
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

kpi_frame = dataiku.Dataset(KPI_INPUT).get_dataframe()
if kpi_frame.empty:
    raise RuntimeError("KPI input '{0}' is empty.".format(KPI_INPUT))
print("KPI rows:", len(kpi_frame), "columns:", list(kpi_frame.columns))
_hint_roots = []
try:
    _hint_roots.append(Path(__file__).resolve().parents[2])
except NameError:
    pass
_hint_roots.append(Path.cwd())
_notes, _aliases = _load_semantic_hints(_hint_roots)
_profiles = _profile_frame(kpi_frame, notes=_notes)
print("Catalog attributes with members:", sum(1 for col in _profiles if col.values))

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
    try:
        llm_sql, llm_answer = _ask_opus(opus_llm, question, kpi_frame, _profiles, _aliases)
        print(i, "opus", OPUS_ID, (llm_answer or "")[:120])
    except Exception as exc:
        llm_answer = "ERROR: {0}".format(exc)
        print("ERROR", i, exc)
        traceback.print_exc()
    rows.append(
        {
            "question": question,
            "Expected_SQL_Query": expected,
            "LLM_generated_SQL": llm_sql,
            "LLM_generated_answer": llm_answer,
        }
    )

if not rows:
    raise RuntimeError("No non-empty input_question values in the questions input.")

out_df = pd.DataFrame(
    rows,
    columns=[
        "question",
        "Expected_SQL_Query",
        "LLM_generated_SQL",
        "LLM_generated_answer",
    ],
)
dataiku.Dataset(OUTPUT_DS).write_with_schema(out_df)
print(json.dumps({"ok": True, "rows": len(out_df), "llm": OPUS_ID, "output": OUTPUT_DS}, indent=2))
