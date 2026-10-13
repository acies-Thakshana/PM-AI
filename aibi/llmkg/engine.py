"""LLM-first ask: plan → SQL → execute → answer → update knowledge graph."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from aibi.factory.join_guard import assert_registered_joins
from aibi.factory.loader import load_domain
from aibi.factory.models import DomainPackage
from aibi.factory.security_tags import assert_no_restricted_in_sql, restricted_columns
from aibi.llmkg.graph import KnowledgeGraph
from aibi.llmkg.grounding import (
    diagnose,
    load_semantic_hints,
    prepare_sql,
    profile_frame,
    references_unavailable,
    result_is_vacuous,
    schema_text,
)
from aibi.llmkg.llm import complete_json
from aibi.llmkg.seed import package_from_frame, package_from_frames, schema_for_llm, seed_from_package
from aibi.settings import PROJECT_ROOT

_SAFE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def ask_with_graph(
    question: str,
    *,
    domain: str = "generic_cube",
    frames: dict[str, pd.DataFrame] | None = None,
    pkg: DomainPackage | None = None,
    graph: KnowledgeGraph | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Answer one question with the LLM and write what it learned into the graph."""
    question = (question or "").strip()
    if not question:
        raise ValueError("question is required")

    pkg = pkg or _load_or_infer_package(domain, frames)
    graph = graph or KnowledgeGraph(pkg.contract.domain)
    if not graph.nodes:
        seed_from_package(graph, pkg)

    request_id = str(uuid.uuid4())
    question_id = "q." + hashlib.sha1(question.encode("utf-8")).hexdigest()[:12]
    subgraph = graph.subgraph_for_question(question)
    schema = schema_for_llm(pkg)
    loaded_frames = dict(frames or {}) or _load_fixture_frames(pkg)
    notes, aliases = _column_grounding(pkg)
    profiles = []
    catalog_parts = []
    for table_name, frame in loaded_frames.items():
        table_profiles = profile_frame(frame, notes=notes)
        profiles.extend(table_profiles)
        if table_profiles:
            catalog_parts.append(
                schema_text(table_profiles, question, table=table_name, aliases=aliases)
            )
    catalog = "\n\n".join(catalog_parts)

    plan = complete_json(
        "You are the AI4BI planner. Infer intent, metrics, and calculations from "
        "the question plus the retrieved knowledge graph. Do not invent joins. "
        "Output JSON only.",
        json.dumps(
            {
                "question": question,
                "schema": schema,
                "knowledge_graph_slice": subgraph,
                "required_keys": [
                    "intent",
                    "interpreted_question",
                    "entities",
                    "metrics",
                    "dimensions",
                    "filters",
                    "calculations",
                    "new_terms",
                    "confidence",
                ],
            },
            default=str,
        ),
        task="intent",
        fallback=_fallback_plan(question, schema),
    )

    sql_payload = complete_json(
        "You write SQLite SQL. Use only listed physical_dataset names and columns. "
        "If you need a JOIN, the condition MUST be one of registered_joins. "
        "Never select restricted/PII columns. Filter values must be copied from the "
        "catalog members. Never use a column that was omitted for having no data. "
        "Additive measures use SUM unless asked for avg/count. "
        "Output JSON only with sql_query, datasets_used, columns_used, rationale.",
        json.dumps(
            {
                "question": question,
                "plan": {k: plan.get(k) for k in (
                    "intent", "interpreted_question", "metrics",
                    "dimensions", "filters", "calculations", "entities",
                )},
                "schema": schema,
                "catalog": catalog,
                "prior_sql_patterns": [
                    n for n in subgraph.get("nodes") or [] if n.get("kind") == "sql_pattern"
                ][:8],
            },
            default=str,
        ),
        task="sql",
        fallback=_fallback_sql(question, schema, frames),
    )
    sql = _normalize_bool_literals(str(sql_payload.get("sql_query") or "").strip())
    if profiles:
        sql = _normalize_bool_literals(prepare_sql(sql, profiles, question, aliases=aliases))
    assert_no_restricted_in_sql(sql, pkg)
    assert_registered_joins(sql, pkg)
    result, exec_error = _execute_guarded(sql, loaded_frames, pkg)
    if profiles and (
        exec_error or result_is_vacuous(result) or references_unavailable(sql, profiles)
    ):
        repaired = _repair_sql(
            question,
            sql,
            catalog,
            diagnose(sql, profiles, result) if not exec_error else exec_error,
        )
        repaired = _normalize_bool_literals(
            prepare_sql(repaired, profiles, question, aliases=aliases)
        )
        if repaired and repaired != sql:
            assert_no_restricted_in_sql(repaired, pkg)
            assert_registered_joins(repaired, pkg)
            repaired_result, repaired_error = _execute_guarded(repaired, loaded_frames, pkg)
            if (
                not repaired_error
                and not result_is_vacuous(repaired_result)
                and not references_unavailable(repaired, profiles)
            ):
                sql, result = repaired, repaired_result
    preview = _preview(result)

    answer_payload = complete_json(
        "You are a BI analyst. Answer only from the executed result. "
        "If the result has no rows or only null measures, say which filter missed "
        "and quote the closest catalog members from the diagnosis. Do not invent figures. "
        "Output JSON only with keys answer, key_findings.",
        json.dumps(
            {
                "question": question,
                "interpreted_question": plan.get("interpreted_question"),
                "sql_query": sql,
                "result": preview,
                "diagnosis": diagnose(sql, profiles, result)
                if profiles and (result_is_vacuous(result) or references_unavailable(sql, profiles))
                else "",
                "metrics": plan.get("metrics"),
                "calculations": plan.get("calculations"),
            },
            default=str,
        ),
        task="answer",
        fallback={
            "answer": _fallback_answer(question, preview),
            "key_findings": [],
        },
    )

    episode = {
        "request_id": request_id,
        "question_id": question_id,
        "question": question,
        "intent": plan.get("intent"),
        "interpreted_question": plan.get("interpreted_question"),
        "metrics": plan.get("metrics") or [],
        "calculations": plan.get("calculations") or [],
        "new_terms": plan.get("new_terms") or [],
        "sql": sql,
        "status": "success",
        "answer_excerpt": str(answer_payload.get("answer") or "")[:400],
    }
    graph.record_episode(episode)
    if persist:
        graph.save()

    return {
        "request_id": request_id,
        "status": "success",
        "answer_path": "llm_kg",
        "answer": answer_payload.get("answer") or "",
        "key_findings": answer_payload.get("key_findings") or [],
        "intent": plan.get("intent"),
        "confidence": plan.get("confidence"),
        "interpreted_question": plan.get("interpreted_question") or question,
        "metrics": plan.get("metrics") or [],
        "calculations": plan.get("calculations") or [],
        "sql_query": sql,
        "sql_rationale": sql_payload.get("rationale") or "",
        "table": preview,
        "explainability": {
            "metric_definition": plan.get("metrics") or [],
            "calculations": plan.get("calculations") or [],
            "applied_filters": plan.get("filters") or {},
            "source_attribution": {
                "extracts": list(pkg.contract.extracts),
                "source_system": pkg.contract.source_system,
            },
            "sql": sql,
            "knowledge_graph": {
                "nodes": len(graph.nodes),
                "edges": len(graph.edges),
                "episodes": len(graph.episodes),
                "path": str(graph.path),
            },
        },
        "llm": {
            "planner": plan.get("_llm_provider"),
            "sql": sql_payload.get("_llm_provider"),
            "answer": answer_payload.get("_llm_provider"),
        },
        "graph": graph.to_dict(),
    }


def _column_grounding(pkg: DomainPackage) -> tuple[dict[str, str], list[tuple[str, str]]]:
    notes, aliases = load_semantic_hints([PROJECT_ROOT])
    for entity in pkg.entities:
        for column in entity.columns:
            if column.description and column.name not in notes:
                notes[column.name] = column.description
    return notes, aliases


def _repair_sql(question: str, sql: str, catalog: str, problem: str) -> str:
    payload = complete_json(
        "You repair SQLite SELECT SQL. Use only the catalog. "
        "Copy filter members exactly. Do not reference omitted columns. "
        "Output JSON only with sql_query and rationale.",
        json.dumps(
            {
                "question": question,
                "previous_sql": sql,
                "problem": problem,
                "catalog": catalog,
            },
            default=str,
        ),
        task="sql_repair",
        fallback={"sql_query": sql, "rationale": "kept previous SQL"},
    )
    return str(payload.get("sql_query") or sql).strip()


def _normalize_bool_literals(sql: str) -> str:
    text = str(sql or "")
    text = re.sub(r"(?i)(=\s*)(?:'True'|\"True\"|\btrue\b)", r"\g<1>1", text)
    text = re.sub(r"(?i)(=\s*)(?:'False'|\"False\"|\bfalse\b)", r"\g<1>0", text)
    text = re.sub(r"(?i)\bIS\s+TRUE\b", "= 1", text)
    text = re.sub(r"(?i)\bIS\s+FALSE\b", "= 0", text)
    return text


def _execute_guarded(
    sql: str, frames: dict[str, pd.DataFrame] | None, pkg: DomainPackage
) -> tuple[pd.DataFrame, str]:
    try:
        return _execute(sql, frames, pkg), ""
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), str(exc)


def _load_or_infer_package(
    domain: str, frames: dict[str, pd.DataFrame] | None
) -> DomainPackage:
    try:
        return load_domain(domain)
    except FileNotFoundError:
        if frames:
            if len(frames) == 1:
                name, frame = next(iter(frames.items()))
                return package_from_frame(domain, frame, table_name=name)
            return package_from_frames(domain, frames)
        raise


def _execute(
    sql: str, frames: dict[str, pd.DataFrame] | None, pkg: DomainPackage
) -> pd.DataFrame:
    loaded = dict(frames or {})
    if not loaded:
        loaded = _load_fixture_frames(pkg)
    if not loaded:
        raise RuntimeError("No data frames available to execute SQL")
    with sqlite3.connect(":memory:") as conn:
        for name, frame in loaded.items():
            safe = name if _SAFE.match(name) else "fact"
            frame.to_sql(safe, conn, index=False, if_exists="replace")
        conn.execute("PRAGMA query_only = ON")
        return pd.read_sql_query(sql, conn)


def _load_fixture_frames(pkg: DomainPackage) -> dict[str, pd.DataFrame]:
    from aibi.tabular import SUFFIXES, read_table, read_tables_in

    root = PROJECT_ROOT / "local_data" / "fixtures" / pkg.contract.domain
    frames: dict[str, pd.DataFrame] = {}
    if not root.exists():
        return frames
    for entity in pkg.entities:
        for suffix in SUFFIXES:
            path = root / "{0}{1}".format(entity.physical_dataset, suffix)
            if path.exists():
                frames[entity.physical_dataset] = read_table(path)
                break
    if not frames:
        frames.update(read_tables_in(root))
    return frames


def _preview(frame: pd.DataFrame, limit: int = 20) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {"columns": [], "rows": [], "n": 0}
    clipped = frame.head(limit)
    return {
        "columns": [str(c) for c in clipped.columns],
        "rows": json.loads(clipped.to_json(orient="records", date_format="iso")),
        "n": int(len(frame)),
    }


def _fallback_plan(question: str, schema: dict[str, Any]) -> dict[str, Any]:
    q = question.lower()
    intent = "aggregation"
    if re.search(r"\b(top|rank|highest|lowest)\b", q):
        intent = "ranking"
    elif re.search(r"\b(compare|versus|vs|against)\b", q):
        intent = "comparison"
    elif re.search(r"\b(trend|over time|month|quarter)\b", q):
        intent = "trend"
    measures = [
        c["name"]
        for ent in schema.get("entities") or []
        for c in ent.get("columns") or []
        if c.get("role") == "measure"
    ]
    chosen = next((m for m in measures if "productiv" in m.lower()), measures[0] if measures else "")
    return {
        "intent": intent,
        "interpreted_question": question,
        "entities": [e.get("logical_entity") for e in schema.get("entities") or []],
        "metrics": [
            {
                "name": chosen or "measure",
                "calculation": f"SUM({chosen})" if chosen else "COUNT(*)",
                "sql_expression": f'SUM("{chosen}")' if chosen else "COUNT(*)",
                "grain": "cube",
            }
        ],
        "dimensions": [],
        "filters": {},
        "calculations": [
            {"name": "primary", "formula": f"SUM({chosen})" if chosen else "COUNT(*)", "rationale": "local planner"}
        ],
        "new_terms": [],
        "confidence": 0.4,
    }


def _fallback_sql(
    question: str, schema: dict[str, Any], frames: dict[str, pd.DataFrame] | None
) -> dict[str, Any]:
    ents = schema.get("entities") or []
    table = (ents[0].get("physical_dataset") if ents else None) or "KPI_data"
    cols = [c["name"] for e in ents for c in e.get("columns") or []]
    if frames and not cols:
        cols = list(next(iter(frames.values())).columns)
    measure = next((c for c in cols if "productiv" in c.lower() and "actual" in c.lower()), None)
    measure = measure or next((c for c in cols if "productiv" in c.lower()), None)
    dim = next((c for c in cols if c.lower() in {"bu", "site name", "pillar type", "region"}), None)
    q = question.lower()
    if measure and re.search(r"\b(top|rank)\b", q) and dim:
        sql = (
            'SELECT {d} AS dim, SUM({m}) AS value FROM {t} '
            "GROUP BY {d} ORDER BY value DESC LIMIT 10"
        ).format(d=_ident(dim), m=_ident(measure), t=_ident(table))
    elif measure:
        sql = "SELECT SUM({m}) AS value FROM {t}".format(m=_ident(measure), t=_ident(table))
    else:
        sql = "SELECT COUNT(*) AS value FROM {t}".format(t=_ident(table))
    return {
        "sql_query": sql,
        "datasets_used": [table],
        "columns_used": [measure or "*"],
        "rationale": "local structured fallback",
    }


def _fallback_answer(question: str, preview: dict[str, Any]) -> str:
    rows = preview.get("rows") or []
    if not rows:
        return "The query returned no rows."
    return "Result for '{0}': {1}".format(question, json.dumps(rows[:5]))


def _ident(name: str) -> str:
    raw = str(name or "").strip()
    if _SAFE.match(raw):
        return raw
    return '"' + raw.replace('"', '""') + '"'
