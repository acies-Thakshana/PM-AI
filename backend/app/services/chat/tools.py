"""The assistant's read-only tools.

The model never reads a record itself: it asks for one of these, the app runs it, and the result is shown back
to the model (see orchestrator.py). Rules every tool follows:

  * read only: nothing here changes data;
  * bound to ONE session, by the server (`ToolContext`), never by an argument the model chooses;
  * results are plain JSON, capped in size (rows, columns, text), so a prompt cannot grow without limit;
  * a failure comes back as {"error": ...} for the model to explain, it is never raised.
"""
from __future__ import annotations

import inspect
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd

from app.services.analysis import analysis_repository
from app.services.audit.audit_store import get_or_404
from app.services.common import audit_log, doc_store
from app.services.features import feature_repository

log = logging.getLogger(__name__)

MAX_ROWS = 20          # rows of a result table shown to the model
MAX_COLUMNS = 30       # columns described one by one in the dataset summary (the rest are only named)
MAX_OTHER_COLUMN_NAMES = 60
MAX_ISSUES = 20
MAX_EVENTS = 25
MAX_TEXT = 1500        # one text field (plan, interpretation, brief)
MAX_MATCHES = 5
MATCH_THRESHOLD = 0.5


@dataclass(frozen=True)
class ToolContext:
    session_id: str


# ------------------------------------------------------------------------------------------- helpers
def _text(value: Any, limit: int = MAX_TEXT) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _round(value: Any) -> Any:
    """Floats rounded for the prompt; numpy / pandas scalars turned into plain Python values."""
    if isinstance(value, float):
        return round(value, 4)
    if hasattr(value, "item"):
        return _round(value.item())
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


def _clean_row(row: dict) -> dict:
    return {str(k): _round(v) for k, v in row.items()}


_STOP_WORDS = {"the", "and", "per", "for", "with", "all"}


def _tokens(name: str) -> set[str]:
    words = re.sub(r"[^a-z0-9 ]+", " ", name.lower()).split()
    return {w[:-1] if w.endswith("s") else w for w in words if len(w) > 2 and w not in _STOP_WORDS}


def name_overlap(a: str, b: str) -> float:
    """How much two names share ("Alarm rate by origin" vs "Alarms by Origin"): shared words / the shorter name."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def analyses_of(session_id: str) -> list[dict]:
    """The analyses of the report (not rejected, no drill-down levels), each with its run result. The repository only
    holds the definitions: whether an analysis ran, its table and what it shows live on the session, and the pages
    merge them in the same way."""
    try:
        results = getattr(get_or_404(session_id), "analysis_results", None) or {}
    except Exception as exc:  # noqa: BLE001 - without results the definitions are still listed (as not run)
        log.warning("chat tools: no run results for %s: %s", session_id, exc)
        results = {}
    out = []
    for entry in analysis_repository.get_repository(session_id):
        if entry.get("source") == "drilldown" or entry.get("status") == "rejected":
            continue
        result = results.get(entry["id"])
        if result is not None:
            entry = {
                **entry,
                "run_status": result.run_status,
                "plan_text": result.plan_text or entry.get("plan_text"),
                "result_table": result.result_table,
                "result_columns": result.result_columns,
                "chart_type": result.chart_type,
                "interpretation": result.interpretation,
                "error": result.error,
            }
            if not entry.get("filters") and result.filters:
                entry["filters"] = result.filters
        out.append(entry)
    return out


_analyses = analyses_of


def _features(session_id: str) -> list[dict]:
    return [e for e in feature_repository.get_repository(session_id) if e.get("status") != "rejected"]


def known_items(session_id: str) -> dict[str, str]:
    """{entry id: "analysis" | "feature"} of this session: what an action may point at."""
    items = {e["id"]: "feature" for e in _features(session_id)}
    items.update({e["id"]: "analysis" for e in _analyses(session_id)})
    return items


def _brief_text(session_id: str) -> str:
    doc = doc_store.get(session_id, "BRIEF") or {}
    block = doc.get("client_brief", {}) if isinstance(doc, dict) else {}
    return _text(block.get("understanding_text") or block.get("translated_text") or block.get("final_text") or block.get("raw_text"), 3000)


# ---------------------------------------------------------------------------------------------- tools
def get_report_overview(ctx: ToolContext) -> dict:
    """What exists in this session: analyses, calculations, the audit state and the brief."""
    session = get_or_404(ctx.session_id)
    return {
        "brief": _brief_text(ctx.session_id)[:600],
        "analyses": [
            {"id": e["id"], "name": e["name"], "status": e["status"], "run_status": e.get("run_status", "not_run")}
            for e in _analyses(ctx.session_id)
        ],
        "calculations": [{"id": e["id"], "name": e["name"], "status": e["status"]} for e in _features(ctx.session_id)],
        "audit": {
            "decisions_pending": sum(1 for i in session.issues if i.requires_decision and i.status == "pending"),
            "issues": len(session.issues),
        },
        "rows": len(session.df),
    }


def find_item(ctx: ToolContext, query: str = "") -> dict:
    """Analyses and calculations whose name matches `query` (best first)."""
    query = _text(query, 200)
    if not query:
        return {"error": "Give the name of the analysis or calculation to look for."}
    hits = []
    for kind, entries in (("analysis", _analyses(ctx.session_id)), ("calculation", _features(ctx.session_id))):
        for e in entries:
            score = 1.0 if query.lower() == e["name"].lower() else name_overlap(query, e["name"])
            if score >= MATCH_THRESHOLD:
                hits.append({"kind": kind, "id": e["id"], "name": e["name"], "score": round(score, 2)})
    hits.sort(key=lambda h: h["score"], reverse=True)
    return {"matches": hits[:MAX_MATCHES]} if hits else {"matches": [], "note": "No analysis or calculation has a similar name."}


def get_analysis(ctx: ToolContext, id: str = "") -> dict:  # noqa: A002 - `id` is the argument name the model uses
    """One analysis: what it is, how it was calculated, what it shows and the top rows of its result."""
    entry = next((e for e in _analyses(ctx.session_id) if e["id"] == id), None)
    if entry is None:
        return {"error": "No analysis has that id.", "known_ids": [e["id"] for e in _analyses(ctx.session_id)]}
    table = entry.get("result_table") or []
    return {
        "id": entry["id"],
        "name": entry["name"],
        "description": _text(entry.get("description")),
        "status": entry["status"],
        "run_status": entry.get("run_status", "not_run"),
        "how_it_was_calculated": _text(entry.get("plan_text") or entry.get("template_summary") or entry.get("formula")),
        "chart_type": entry.get("chart_type"),
        # The inputs of the analysis: the columns it reads and the filters offered on its chart.
        "inputs": {
            "columns": entry.get("input_columns") or [],
            "filters": [f.get("column") for f in entry.get("filters") or [] if isinstance(f, dict) and f.get("column")],
        },
        "what_it_shows": _text(entry.get("interpretation")),
        "error": _text(entry.get("error"), 300) or None,
        "needs_calculations": [
            {"name": r.get("name"), "state": r.get("state")} for r in (entry.get("required_features") or [])
        ],
        "result_columns": entry.get("result_columns") or [],
        "result_rows_total": len(table),
        "result_rows_shown": [_clean_row(r) for r in table[:MAX_ROWS]],
    }


def _column_stats(df: pd.DataFrame, column: str) -> dict:
    series = df[column]
    stats: dict[str, Any] = {"non_empty": int(series.notna().sum()), "empty": int(series.isna().sum())}
    if pd.api.types.is_numeric_dtype(series) and series.notna().any():
        stats.update(min=_round(series.min()), max=_round(series.max()), mean=_round(series.mean()))
    elif series.notna().any():
        stats["top_values"] = [str(v) for v in series.value_counts().head(3).index]
    return stats


def get_feature(ctx: ToolContext, id: str = "") -> dict:  # noqa: A002
    """One calculation: what it is, its formula, and (once computed) how its values look."""
    entry = next((e for e in _features(ctx.session_id) if e["id"] == id), None)
    if entry is None:
        return {"error": "No calculation has that id.", "known_ids": [e["id"] for e in _features(ctx.session_id)]}
    out = {
        "id": entry["id"],
        "name": entry["name"],
        "description": _text(entry.get("description")),
        "status": entry["status"],
        "how_it_is_calculated": _text(entry.get("calculation_intent")),
        "formula": _text(entry.get("formula")),
        "uses_columns": entry.get("input_columns") or [],
        "output_column": entry.get("output_column"),
        "needed_by_analyses": entry.get("required_for_analysis") or [],
        "computed": False,
    }
    try:
        df = get_or_404(ctx.session_id).df
        column = entry.get("output_column")
        if column in df.columns:
            out["computed"] = True
            out["values"] = _column_stats(df, column)
    except Exception as exc:  # noqa: BLE001 - the description is still useful without the values
        log.warning("get_feature: no values for %s: %s", id, exc)
    return out


def get_dataset_summary(ctx: ToolContext) -> dict:
    """The loaded data as it is now (after the audit): size, every column, and what stands out."""
    session = get_or_404(ctx.session_id)
    df = session.df
    rows = len(df)
    columns = []
    empty, mostly_empty, constant = [], [], []
    for position, name in enumerate(df.columns):
        series = df[name]
        missing = float(series.isna().mean()) if rows else 0.0
        unique = int(series.nunique(dropna=True))
        # What stands out is judged over EVERY column; only the first ones are described one by one.
        if missing >= 1.0:
            empty.append(str(name))
        elif missing > 0.5:
            mostly_empty.append(str(name))
        elif unique == 1:
            constant.append(str(name))
        if position >= MAX_COLUMNS:
            continue
        info: dict[str, Any] = {"name": str(name), "type": str(series.dtype), "missing_pct": round(missing * 100, 1), "distinct": unique}
        if pd.api.types.is_numeric_dtype(series) and series.notna().any():
            info.update(min=_round(series.min()), max=_round(series.max()))
        elif pd.api.types.is_datetime64_any_dtype(series) and series.notna().any():
            info.update(min=_round(series.min()), max=_round(series.max()))
        elif 0 < unique <= 50:
            info["top_values"] = [str(v) for v in series.value_counts().head(3).index]
        columns.append(info)
    notes = []
    if empty:
        notes.append(f"{len(empty)} columns are completely empty: {', '.join(empty[:8])}")
    if mostly_empty:
        notes.append(f"{len(mostly_empty)} columns are more than half empty: {', '.join(mostly_empty[:8])}")
    if constant:
        notes.append(f"{len(constant)} columns hold a single value: {', '.join(constant[:8])}")
    # Highlights first: a result that is too long is cut at the end, and the end is the least important part.
    return {
        "source": session.source,
        "file": session.filename,
        "rows": rows,
        "columns_total": len(df.columns),
        "things_that_stand_out": notes,
        "columns_described_below": len(columns),
        "other_columns": [str(c) for c in list(df.columns)[MAX_COLUMNS:][:MAX_OTHER_COLUMN_NAMES]],
        "columns": columns,
    }


def get_audit_summary(ctx: ToolContext) -> dict:
    """The data audit: its summary and each finding with its state."""
    session = get_or_404(ctx.session_id)
    return {
        "summary": _text(session.summary),
        "decisions_pending": sum(1 for i in session.issues if i.requires_decision and i.status == "pending"),
        "findings": [
            {
                "id": i.id,
                "title": i.title,
                "severity": i.severity,
                "status": i.status,
                "needs_decision": bool(i.requires_decision),
                "what": _text(i.description, 240),
            }
            for i in session.issues[:MAX_ISSUES]
        ],
    }


def get_brief(ctx: ToolContext) -> dict:
    """The client brief and what the interview settled."""
    interview = doc_store.get(ctx.session_id, "INTERVIEW") or {}
    return {
        "brief": _brief_text(ctx.session_id),
        "interview": {
            "understanding": interview.get("understanding") or {},
            "assumptions": [a.get("text", "") for a in interview.get("assumptions") or []],
        },
    }


def get_history(ctx: ToolContext) -> dict:
    """The newest events of this session: what was uploaded, decided, added or changed, and when. The chat's own
    bookkeeping (its messages, tool calls and LLM calls) is left out: it says nothing about the report."""
    recent = audit_log.events_for_session(ctx.session_id, limit=200)
    events = [e for e in recent if e.get("category") != "chat" and e.get("event_type") != "llm_call"][-MAX_EVENTS:]
    return {
        "events": [
            {"time": e["ts_event"][:19], "type": e["event_type"], "result": e["result"], "summary": _text(e["summary"], 200)}
            for e in events
        ]
    }


# --------------------------------------------------------------------------------------------- registry
@dataclass(frozen=True)
class Tool:
    name: str
    run: Callable[..., dict]
    description: str
    args: str = ""


TOOLS: dict[str, Tool] = {t.name: t for t in (
    Tool("get_report_overview", get_report_overview, "What exists: analyses and calculations (with ids and state), the audit state, row count, the brief."),
    Tool("find_item", find_item, "Find an analysis or calculation by (part of) its name; returns ids.", '{"query": "name or words from it"}'),
    Tool("get_analysis", get_analysis, "One analysis: how it was calculated, what it shows, its top result rows.", '{"id": "analysis id"}'),
    Tool("get_feature", get_feature, "One calculation: its formula, the columns it uses and how its values look.", '{"id": "calculation id"}'),
    Tool("get_dataset_summary", get_dataset_summary, "The loaded data: rows, every column (type, empty share, range, top values) and what stands out."),
    Tool("get_audit_summary", get_audit_summary, "The data audit: summary and each finding with its state."),
    Tool("get_brief", get_brief, "The client brief and what the interview settled."),
    Tool("get_history", get_history, "What was uploaded, decided, added or changed in this session, newest last."),
)}


def describe_tools() -> str:
    """The tool list as shown to the model."""
    return "\n".join(f"- {t.name}({t.args}): {t.description}" for t in TOOLS.values())


def run_tool(name: str, args: dict, ctx: ToolContext) -> dict:
    """Run one tool. Unknown tools and failing tools answer with {"error": ...}; this never raises."""
    tool = TOOLS.get(name)
    if tool is None:
        return {"error": f"Unknown tool '{name}'.", "tools": sorted(TOOLS)}
    kwargs = {k: v for k, v in (args or {}).items() if isinstance(k, str)}
    try:
        inspect.signature(tool.run).bind(ctx, **kwargs)
    except TypeError:
        return {"error": f"Wrong arguments for {name}. Expected {tool.args or 'no arguments'}."}
    try:
        return tool.run(ctx, **kwargs)
    except Exception as exc:  # noqa: BLE001 - the model explains the failure, the turn goes on
        log.warning("chat tool %s failed: %s", name, exc)
        return {"error": f"{name} failed: {exc}"}
