"""Per-session analysis repository: the single place every candidate
analysis lands, regardless of which of the five sources proposed it --

  predefined -- parsed from the uploaded Analysis Profile file
  planner    -- Planner Agent recommendations the PM approved
  custom     -- typed directly into the Analysis page by the PM
  ai_suggested -- proposed by the AI analysis-suggestion agent
  drilldown  -- created by confirming a level of a guided drill-down chain
                (see add_chain_entry)

`predefined` and `planner` are derived, not stored -- they always reflect
whatever is currently in the Analysis Profile store / that session's
PLAN#<n> documents, so re-uploading a profile or re-approving planner
recommendations is picked up automatically. `custom`, `ai_suggested`, and
`drilldown` are the only entries actually persisted, inside the ANALYSES
document (their accept/reject state and PM-authored/
PM-triggered content can't be re-derived from anywhere else). Every read
rebuilds the full merged view.
"""
from __future__ import annotations

import uuid

from app.services.analysis import analysis_definitions_store as defs_store
from app.services.common.entry_store import ANALYSES
from app.services.planner import planner_store

_PERSISTED_SOURCES = {"custom", "ai_suggested", "drilldown"}

# Every analysis of the session is one record in the `ANALYSES` document (services/common/
# entry_store.py); analysis_cache.py keeps the final code in the same record under "cache".


def with_answer(description: str, business_question: str | None) -> str:
    """Appends the business question an analysis answers, in the same form the Analysis Profile uses:
    "<what it shows> -- answers '<question>.'". Only the shown description gets it; calculation_intent
    (what the agents compute from) stays the plain description."""
    question = (business_question or "").strip().rstrip(".?").strip()
    if not question:
        return description
    return f"{(description or '').strip().rstrip('.')} -- answers '{question}.'"


def _predefined_entries() -> list[dict]:
    if defs_store.store.definitions is None:
        return []
    entries = []
    for spec in defs_store.store.definitions:
        entries.append({
            "id": f"predefined_{spec['id']}",
            "source": "predefined",
            "status": "approved",
            "name": spec["name"],
            "description": spec.get("description", ""),
            "calculation_intent": spec["calculation_intent"],
            "input_columns": spec.get("input_columns", []),
            # A predefined spec may ship its own pre-authored formula (skips
            # Think entirely); otherwise the Analysis Agent thinks one up at
            # compute time, same convention as feature_repository's
            # "ai_generated" predefined type.
            "formula": spec.get("formula"),
            "parent_id": None,
            # Optional in analysis_profile.json: the features (by id, output
            # column or name) this analysis consumes.
            "required_features": _profile_feature_refs(spec.get("required_features")),
        })
    return entries


def _profile_feature_refs(raw) -> list[dict]:
    """Normalises an analysis-profile `required_features` list -- each item a
    feature id / output column / name string, or a dict with those keys."""
    refs = []
    for item in raw or []:
        if isinstance(item, str) and item.strip():
            key = item.strip()
            refs.append({"feature_id": key if key.startswith("predefined_") else None, "name": key, "output_column": key})
        elif isinstance(item, dict) and (item.get("feature_id") or item.get("name") or item.get("output_column")):
            refs.append({"feature_id": item.get("feature_id"), "name": item.get("name") or item.get("output_column") or "",
                         "output_column": item.get("output_column")})
    return refs




def _planner_entries(session_id: str) -> list[dict]:
    try:
        recs = planner_store.load(session_id)
    except Exception:
        return []
    # Imported here: planner_dependencies itself reads this module's predefined entries.
    from app.services.planner import planner_dependencies

    slug_to_index = {
        planner_dependencies.slug(r.get("name", "")): j
        for j, r in enumerate(recs) if r.get("type") in ("feature", "feature_and_analysis")
    }
    entries = []
    for i, rec in enumerate(recs):
        if rec.get("pm_decision") != "accepted":
            continue
        if rec.get("type") not in ("analysis", "feature_and_analysis"):
            continue
        if rec.get("analysis_source") == "analysis_profile":
            # Already present as a predefined entry with its own configuration.
            continue
        required = []
        for dep in rec.get("feature_dependencies") or []:
            if dep.get("action") == "reuse_existing" and dep.get("existing_id"):
                required.append({"feature_id": dep["existing_id"], "name": dep["feature_name"],
                                 "output_column": dep.get("output_column")})
            elif planner_dependencies.slug(dep.get("feature_name", "")) in slug_to_index:
                j = slug_to_index[planner_dependencies.slug(dep["feature_name"])]
                required.append({"feature_id": f"planner_{j}", "name": recs[j]["name"],
                                 "output_column": planner_dependencies.slug(recs[j]["name"])})
        if rec.get("type") == "feature_and_analysis" and not required:
            # Older output: the combined recommendation's own feature is the dependency.
            required.append({"feature_id": f"planner_{i}", "name": rec.get("name", ""),
                             "output_column": planner_dependencies.slug(rec.get("name", ""))})
        # The Planner's current schema is flat (name/description/required_fields
        # directly on the recommendation) -- see planner.py's system prompt.
        name = rec.get("name") or f"Planner Analysis {i + 1}"
        entries.append({
            "id": f"planner_analysis_{i}",
            "source": "planner",
            "status": "approved",
            "name": name,
            "description": with_answer(rec.get("description", ""), rec.get("business_question")),
            "calculation_intent": rec.get("description", ""),
            "input_columns": rec.get("required_fields", []),
            # Pre-generated by the Analysis Agent's Think step at Planner
            # suggest time (see planner.py) -- the PM saw and approved THIS
            # plan specifically, so it's carried through verbatim.
            "formula": rec.get("generated_analysis_formula"),
            "parent_id": None,
            "required_features": required,
            "kpi_dependencies": rec.get("kpi_dependencies") or [],
        })
    return entries


def _derived(session_id: str) -> list[dict]:
    """The predefined + planner entries right now (snapshotted into the ANALYSES document)."""
    return _predefined_entries() + _planner_entries(session_id)


def _load_persisted(session_id: str) -> list[dict]:
    """The custom / AI-suggested / drill-down analyses of the session, oldest first."""
    try:
        return ANALYSES.load_persisted(session_id)
    except Exception:
        return []


def sync(session_id: str) -> None:
    """Refresh the predefined / planner snapshots in the ANALYSES document (call after the PM
    saved planner decisions, so the JSON shows the current set)."""
    ANALYSES.sync(session_id, _derived(session_id))


def _store(session_id: str, entry: dict) -> None:
    ANALYSES.add(session_id, [entry], _derived(session_id))


def get_repository(session_id: str) -> list[dict]:
    """The full merged view: freshly-derived predefined + planner entries,
    plus whatever custom/ai_suggested/drilldown entries this session has
    persisted. Read-only (nothing is written). Returns definitions
    only -- run results (table/chart/interpretation) live in-memory on the
    audit session and are merged in by the router."""
    return _derived(session_id) + _load_persisted(session_id)


def add_custom_entry(
    session_id: str, name: str, description: str, calculation_intent: str, input_columns: list[str], *,
    formula: str | None = None, template: dict | None = None, chart_recommendation: dict | None = None,
    filters: list[dict] | None = None,
) -> dict:
    """Persists a PM-authored analysis. When it was drafted through the
    Analysis Designer it also carries the reviewed computation logic
    (`formula`), an optional deterministic `template`, the chosen chart, and
    its interactive filters -- all already validated by the caller."""
    entry = {
        "id": f"custom_{uuid.uuid4().hex[:8]}",
        "source": "custom",
        "status": "approved",
        "name": name,
        "description": description or calculation_intent,
        "calculation_intent": calculation_intent,
        "input_columns": input_columns,
        "formula": formula,
        "parent_id": None,
        "template": template,
        "chart_recommendation": chart_recommendation,
        "filters": filters or [],
    }
    _store(session_id, entry)
    return entry


def _normalize_name(name: str) -> str:
    """Shared with analysis_suggester so both dedupe names the same way."""
    return " ".join(name.lower().split())


def add_ai_suggested_entries(session_id: str, suggestions: list[dict]) -> list[dict]:
    """Appends new AI-suggested candidates (status=pending), skipping any
    whose name already exists in the repository (case/whitespace-insensitive)
    so re-running suggestions doesn't pile up duplicates."""
    existing = get_repository(session_id)
    existing_names = {_normalize_name(e["name"]) for e in existing}

    new_entries = []
    for s in suggestions:
        if _normalize_name(s["name"]) in existing_names:
            continue
        entry = {
            "id": f"ai_{uuid.uuid4().hex[:8]}",
            "source": "ai_suggested",
            "status": "pending",
            "name": s["name"],
            "description": with_answer(s.get("description", ""), s.get("business_question")),
            "calculation_intent": s["calculation_intent"],
            "input_columns": s.get("input_columns", []),
            "formula": None,
            "parent_id": None,
        }
        new_entries.append(entry)
        existing_names.add(_normalize_name(entry["name"]))

    if new_entries:
        ANALYSES.add(session_id, new_entries, _derived(session_id))
    return new_entries


def add_chain_entry(
    session_id: str, parent_id: str, *, name: str, description: str, template: dict, chart_type: str,
    filters: list[dict], chain: dict, status: str = "approved",
) -> dict:
    """Persists one confirmed level of a guided drill-down chain. Its
    deterministic `template` carries the whole narrowed-down scope, so it
    runs without any LLM call."""
    entry = {
        "id": f"drilldown_{uuid.uuid4().hex[:8]}",
        "source": "drilldown",
        "status": status,
        "name": name,
        "description": description,
        "calculation_intent": description,
        "input_columns": [],
        "formula": None,
        "parent_id": parent_id,
        "template": template,
        "chart_recommendation": {"chart_type": chart_type, "reason": "Chosen for this drill-down level.", "alternatives": []},
        "filters": filters,
        "chain": chain,
    }
    _store(session_id, entry)
    return entry


def update_entry(session_id: str, entry_id: str, fields: dict) -> dict | None:
    """Merges `fields` into one persisted entry (predefined and planner
    entries are derived, so they can't be edited here)."""
    return ANALYSES.update_persisted(session_id, entry_id, fields, _derived(session_id))


def set_entry_status(session_id: str, entry_id: str, status: str) -> dict | None:
    return update_entry(session_id, entry_id, {"status": status})


def get_entry(session_id: str, entry_id: str) -> dict | None:
    for e in get_repository(session_id):
        if e["id"] == entry_id:
            return e
    return None
