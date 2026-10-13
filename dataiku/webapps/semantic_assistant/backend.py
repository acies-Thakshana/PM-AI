# -*- coding: utf-8 -*-
"""Dataiku standard webapp backend.

Paste this file into the webapp Python tab.
The dashboard numbers are computed from the five fact tables.
The chat box asks Opus for one SQLite SELECT, runs it, and answers from those rows.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import traceback
from pathlib import Path

import pandas as pd

try:
    import dataiku
except Exception:
    dataiku = None

try:
    from flask import jsonify, request
except Exception:
    jsonify = None
    request = None

FACT_TABLES = (
    "sf_accounts",
    "sf_opportunities",
    "sf_service_cases",
    "coldchain_shipments",
    "temperature_excursions",
)
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
Boolean flags are integers 1 and 0. Write is_won = 1, resolved_flag = 0, is_gxp_regulated = 1.
Never compare them to the text 'True' or 'False'.
A rate is SUM(numerator) / NULLIF(SUM(denominator), 0) after GROUP BY.
Copy filter values exactly from the catalog members.
""".strip()

_FRAMES = None


def _missing(value):
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _coerce_flags(frame):
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
                    if _missing(value)
                    else 1 if str(value).strip().lower() in true_tokens else 0
                )
            )
    return out


def _read_dataset(name):
    if dataiku is None:
        raise RuntimeError("dataiku is not available")
    frame = dataiku.Dataset(name).get_dataframe()
    print("Loaded dataset", name, "rows", len(frame))
    return frame


def _read_local_table(name):
    try:
        from aibi.tabular import SUFFIXES, read_table
    except Exception:
        path = None
        for folder in DATA_DIRS:
            if not folder:
                continue
            candidate = Path(folder) / "{0}.csv".format(name)
            if candidate.exists():
                path = candidate
                break
        if path is None:
            return None
        print("Loaded table", path)
        return pd.read_csv(path)
    for folder in DATA_DIRS:
        if not folder:
            continue
        root = Path(folder)
        for suffix in SUFFIXES:
            path = root / "{0}{1}".format(name, suffix)
            if path.exists():
                print("Loaded table", path)
                return read_table(path)
    return None


def load_frames():
    global _FRAMES
    if _FRAMES is not None:
        return _FRAMES
    frames = {}
    for name in FACT_TABLES:
        frame = None
        try:
            frame = _read_dataset(name)
        except Exception as exc:
            print("Dataset", name, "not loaded:", exc)
        if frame is None:
            frame = _read_local_table(name)
        if frame is None or frame.empty:
            continue
        frames[name] = _coerce_flags(frame)
    missing = [name for name in FACT_TABLES if name not in frames]
    if missing:
        raise RuntimeError(
            "Missing fact tables {0}. Add them to this project. CSV, Excel, and Parquet uploads all work.".format(missing)
        )
    _FRAMES = frames
    return frames


def _optional_dataset(name):
    try:
        return _read_dataset(name)
    except Exception:
        frame = _read_csv(name)
        if frame is not None:
            return frame
    downloads = Path(r"c:\Users\BharadNa\Downloads") / "{0}.csv".format(name)
    if downloads.exists():
        return pd.read_csv(downloads)
    return None


def _flag_true(series):
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    if pd.api.types.is_numeric_dtype(series):
        return series.fillna(0).astype(float).eq(1)
    text = series.astype(str).str.strip().str.lower()
    return text.isin(["1", "true", "t", "yes", "y"])


def _money(value):
    if value is None or _missing(value):
        return None
    return round(float(value), 2)


def build_summary(frames):
    accounts = frames["sf_accounts"]
    opportunities = frames["sf_opportunities"]
    cases = frames["sf_service_cases"]
    shipments = frames["coldchain_shipments"]
    excursions = frames["temperature_excursions"]
    won = opportunities[_flag_true(opportunities["is_won"])]
    in_transit = int((shipments["shipment_status"] == "In Transit").sum())
    unresolved = excursions[
        (excursions["severity"] == "Critical") & (excursions["resolved_flag"] == 0)
    ]
    scored = cases.dropna(subset=["csat_score"])
    csat = (
        scored.groupby("entitlement_name", dropna=False)["csat_score"]
        .agg(avg_csat="mean", scored_cases="count")
        .reset_index()
        .sort_values("avg_csat", ascending=False)
    )
    region = (
        won.groupby("region", dropna=False)["amount_usd"]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
    )
    status = (
        shipments["shipment_status"]
        .fillna("(blank)")
        .value_counts()
        .rename_axis("status")
        .reset_index(name="shipments")
    )
    validation = _validation_preview()
    return {
        "kpis": {
            "accounts": int(len(accounts)),
            "opportunities": int(len(opportunities)),
            "won_amount": _money(won["amount_usd"].sum()),
            "shipments": int(len(shipments)),
            "in_transit_pct": round(100.0 * in_transit / max(len(shipments), 1), 1),
            "excursions": int(len(excursions)),
            "unresolved_critical": int(len(unresolved)),
            "service_cases": int(len(cases)),
        },
        "won_by_region": [
            {"label": str(row.region), "amount": _money(row.amount_usd)}
            for row in region.itertuples(index=False)
        ],
        "shipment_status": [
            {"label": str(row.status), "count": int(row.shipments)}
            for row in status.itertuples(index=False)
        ],
        "csat": [
            {
                "entitlement": str(row.entitlement_name),
                "avg_csat": round(float(row.avg_csat), 2),
                "scored_cases": int(row.scored_cases),
            }
            for row in csat.itertuples(index=False)
        ],
        "validation": validation,
    }


def _validation_preview():
    frame = _optional_dataset("semantic_validation_llm")
    if frame is None or frame.empty or "input_question" not in frame.columns:
        return []
    answer_col = "LLM_generated_answer" if "LLM_generated_answer" in frame.columns else ""
    rows = []
    for item in frame.head(14).to_dict(orient="records"):
        question = item.get("input_question")
        answer = item.get(answer_col) if answer_col else ""
        if _missing(question):
            continue
        rows.append(
            {
                "question": str(question),
                "answer": "" if _missing(answer) else str(answer),
            }
        )
    return rows


def _catalog(frames):
    lines = [JOIN_NOTES, ""]
    for name, frame in frames.items():
        lines.append("Table: {0} ({1} rows)".format(name, len(frame)))
        for col in frame.columns:
            series = frame[col]
            values = series.dropna().astype(str).drop_duplicates()
            if len(values) <= 40:
                shown = values.head(40).tolist()
                lines.append("- {0}; members: {1}".format(col, shown))
            elif pd.api.types.is_numeric_dtype(series):
                lines.append(
                    "- {0}; numeric, min {1}, max {2}".format(
                        col, series.min(), series.max()
                    )
                )
            else:
                lines.append("- {0}; {1} distinct text values".format(col, series.nunique(dropna=True)))
        lines.append("")
    return "\n".join(lines)


def _normalize_bool_literals(sql):
    text = str(sql or "")
    text = re.sub(r"(?i)(=\s*)(?:'True'|\"True\"|\btrue\b)", r"\g<1>1", text)
    text = re.sub(r"(?i)(=\s*)(?:'False'|\"False\"|\bfalse\b)", r"\g<1>0", text)
    text = re.sub(r"(?i)\bIS\s+TRUE\b", "= 1", text)
    text = re.sub(r"(?i)\bIS\s+FALSE\b", "= 0", text)
    return text


def _is_select_only(sql):
    text = (sql or "").strip().rstrip(";")
    if not text or ";" in text:
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
        raise ValueError("Only a single SELECT statement is allowed.")
    with sqlite3.connect(":memory:") as conn:
        for name, frame in frames.items():
            frame.to_sql(name, conn, index=False, if_exists="replace")
        conn.execute("PRAGMA query_only = ON")
        return pd.read_sql_query(sql, conn)


def _llm_id(item):
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("id") or item.get("llmId") or item.get("name") or "")
    return str(getattr(item, "id", "") or "")


def _resolve_opus():
    if dataiku is None:
        raise RuntimeError("This chat runs inside a Dataiku webapp with LLM Mesh.")
    variables = dataiku.get_custom_variables()
    explicit = variables.get("AIBI_LLM_CONNECTION") or os.environ.get("AIBI_LLM_CONNECTION")
    project = dataiku.api_client().get_default_project()
    if explicit:
        return project.get_llm(str(explicit)), str(explicit)
    ids = []
    for method in ("list_llms", "list_available_llms"):
        fn = getattr(project, method, None)
        if not callable(fn):
            continue
        try:
            ids = [_llm_id(item) for item in (fn() or [])]
            ids = [item for item in ids if item]
            break
        except Exception as exc:
            print("Could not list LLMs via", method, exc)
    opus = [item for item in ids if "opus" in item.lower()]
    if not opus:
        raise RuntimeError(
            "No Opus LLM Mesh connection found. Set project variable AIBI_LLM_CONNECTION. "
            "Available: {0}".format(ids)
        )
    return project.get_llm(opus[0]), opus[0]


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


def _history_text(history):
    lines = []
    for turn in (history or [])[-6:]:
        role = str(turn.get("role") or "user")
        content = str(turn.get("content") or "").strip()
        if content:
            lines.append("{0}: {1}".format(role, content[:500]))
    return "\n".join(lines)


def _records(frame, limit):
    if frame is None or frame.empty:
        return []
    clipped = frame.head(limit).copy()
    for col in clipped.columns:
        if pd.api.types.is_datetime64_any_dtype(clipped[col]):
            clipped[col] = clipped[col].astype(str)
    return json.loads(clipped.to_json(orient="records", date_format="iso"))


def answer_question(question, history=None):
    started = time.perf_counter()
    frames = load_frames()
    llm, connection_id = _resolve_opus()
    catalog = _catalog(frames)
    prior = _history_text(history)
    sql_prompt = (
        "You write one SQLite SELECT. Tables: {0}.\n"
        "Return JSON only with keys sql_query and rationale.\n"
        "Use only these tables and the columns in the catalog. Copy filter values exactly.\n"
        "Answer only questions that these tables can support.\n\n"
        "Catalog:\n{1}\n\n"
        "Prior turns:\n{2}\n\nQuestion:\n{3}\n"
    ).format(", ".join(frames), catalog, prior or "(none)", question)
    sql_raw = _mesh_complete(
        llm,
        "You are a careful analytics SQL generator. Output JSON only.",
        sql_prompt,
    )
    sql_query = _normalize_bool_literals(str(_extract_json(sql_raw).get("sql_query") or "").strip())
    if not sql_query:
        raise RuntimeError("Opus did not return sql_query.")
    try:
        result = _run_sql(frames, sql_query)
        problem = ""
    except Exception as exc:
        result = pd.DataFrame()
        problem = str(exc)
    if problem or result.empty:
        repair_prompt = (
            "Repair the SQLite SELECT. Use only these tables: {0}. "
            "Copy members exactly. Return JSON with sql_query and rationale.\n\n"
            "Question:\n{1}\n\nPrevious SQL:\n{2}\n\nProblem:\n{3}\n\nCatalog:\n{4}\n"
        ).format(", ".join(frames), question, sql_query, problem or "The query returned no rows.", catalog)
        repaired = _normalize_bool_literals(
            str(_extract_json(_mesh_complete(
                llm, "You repair analytics SQL. Output JSON only.", repair_prompt
            )).get("sql_query") or "").strip()
        )
        if repaired:
            try:
                repaired_frame = _run_sql(frames, repaired)
            except Exception:
                repaired_frame = pd.DataFrame()
            if not repaired_frame.empty:
                sql_query, result = repaired, repaired_frame
    preview = _records(result, 30)
    answer_prompt = (
        "Write a short business answer using ONLY the query result JSON.\n"
        "Return JSON only with keys answer and confidence.\n"
        "confidence is a number from 0 to 1.\n"
        "Use 0 when the result is empty or the measures are null.\n"
        "Do not invent figures.\n\n"
        "Question:\n{0}\n\nSQL:\n{1}\n\nResult:\n{2}\n"
    ).format(question, sql_query, json.dumps({"columns": list(result.columns), "rows": preview, "n": int(len(result))}))
    answer_payload = _extract_json(_mesh_complete(
        llm,
        "You are a BI analyst. Output JSON only. Stay faithful to the result rows.",
        answer_prompt,
    ))
    answer = str(answer_payload.get("answer") or "").strip()
    if not answer:
        answer = "The query finished with {0} row(s).".format(len(result))
    confidence = answer_payload.get("confidence")
    try:
        confidence = float(confidence)
        if confidence > 1 and confidence <= 100:
            confidence = confidence / 100.0
        confidence = min(1.0, max(0.0, confidence))
    except (TypeError, ValueError):
        confidence = None
    return {
        "answer": answer,
        "sql": sql_query,
        "columns": [str(col) for col in result.columns],
        "rows": _records(result, 50),
        "row_count": int(len(result)),
        "confidence": confidence,
        "latency_seconds": round(time.perf_counter() - started, 3),
        "llm": connection_id,
        "error": None,
    }


def _json_error(message, status=400):
    payload = {"error": message}
    if jsonify is None:
        return payload
    response = jsonify(payload)
    response.status_code = status
    return response


def register(flask_app):
    @flask_app.route("/summary", methods=["GET"])
    def summary():
        try:
            return jsonify(build_summary(load_frames()))
        except Exception as exc:
            traceback.print_exc()
            return _json_error(str(exc), 500)

    @flask_app.route("/ask", methods=["POST"])
    def ask():
        payload = request.get_json(silent=True) or {}
        question = str(payload.get("question") or "").strip()
        if not question:
            return _json_error("Enter a question about the cold-chain tables.")
        if len(question) > 2000:
            return _json_error("Ask a shorter question (2000 characters or less).")
        try:
            return jsonify(answer_question(question, payload.get("history") or []))
        except Exception as exc:
            traceback.print_exc()
            return _json_error(str(exc), 500)


try:
    register(app)  # noqa: F821  Dataiku injects the Flask app.
except NameError:
    pass
