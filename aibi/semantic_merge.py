"""Merge enterprise core + domain packs + BU extensions into one semantic model.

Generic pattern (reuse for any dashboard):
  semantic/enterprise/*.yaml     # shared enterprise contract
  semantic/domains/<domain>.yaml # domain pack (metrics for one subject area)
  semantic/business_units/*.yaml # optional BU-owned products / metrics
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aibi.settings import get_settings, load_yaml


def _merge_list(base: list[Any], extra: list[Any], key: str = "id") -> list[Any]:
    by_id: dict[str, Any] = {}
    order: list[str] = []
    for item in list(base or []) + list(extra or []):
        if not isinstance(item, dict):
            continue
        iid = str(item.get(key) or "")
        if not iid:
            continue
        if iid not in by_id:
            order.append(iid)
        by_id[iid] = {**by_id.get(iid, {}), **item}
    return [by_id[i] for i in order]


def merge_semantic_models(core: dict[str, Any], extensions: list[dict[str, Any]]) -> dict[str, Any]:
    out = dict(core or {})
    for ext in extensions:
        if not ext:
            continue
        for section in (
            "data_products",
            "metrics",
            "dimensions",
            "entities",
            "relationships",
            "approved_joins",
            "synonyms",
            "sample_questions",
            "assumptions",
            "unresolved_decisions",
            "semantic_versions",
        ):
            if section == "synonyms":
                # synonyms use term as soft key
                existing = list(out.get(section) or [])
                seen = {(s.get("term"), s.get("maps_to_id")) for s in existing}
                for item in ext.get(section) or []:
                    key = (item.get("term"), item.get("maps_to_id"))
                    if key not in seen:
                        existing.append(item)
                        seen.add(key)
                out[section] = existing
            else:
                out[section] = _merge_list(out.get(section) or [], ext.get(section) or [])
        # security roles: union metric/data product allow-lists
        base_sec = dict(out.get("security") or {})
        ext_sec = ext.get("security") or {}
        roles = _merge_list(base_sec.get("roles") or [], ext_sec.get("roles") or [])
        base_sec["roles"] = roles
        for key in ("row_level_policies", "bu_filters", "sensitive_columns"):
            base_sec[key] = _merge_list(base_sec.get(key) or [], ext_sec.get(key) or [])
        out["security"] = {**base_sec, **{k: v for k, v in ext_sec.items() if k not in {
            "roles", "row_level_policies", "bu_filters", "sensitive_columns"
        }}}
        out.setdefault("_extensions", []).append(ext.get("model_id"))
    return out


def load_merged_semantic_model(*, include_enterprise_template: bool = False) -> dict[str, Any]:
    """Load the active domain pack and optional BU extensions."""
    settings = get_settings()
    core_path = settings.semantic_core_path
    if not core_path.exists():
        core_path = settings.enterprise_template_path
    core = load_yaml(core_path) or {}
    core["_source_path"] = str(core_path)

    extensions: list[dict[str, Any]] = []
    if include_enterprise_template and settings.enterprise_template_path.exists():
        # Domain pack is primary; enterprise template can supply shared dims if needed.
        pass

    ext_dir = settings.project_root / "semantic" / "business_units"
    if ext_dir.is_dir():
        for path in sorted(ext_dir.glob("*.yaml")):
            if path.name.startswith("example_"):
                continue
            doc = load_yaml(path) or {}
            if doc:
                doc["_source_path"] = str(path)
                extensions.append(doc)

    # Also load sibling domain packs (multi-dataset dashboards)
    domains_dir = settings.project_root / "semantic" / "domains"
    if domains_dir.is_dir():
        for path in sorted(domains_dir.glob("*.yaml")):
            if path.name.startswith("_") or path.name.startswith("example_"):
                continue
            if path.resolve() == Path(core_path).resolve():
                continue
            doc = load_yaml(path) or {}
            if doc.get("model_kind") in {"domain_pack", "enterprise_core"} or doc.get("metrics"):
                doc["_source_path"] = str(path)
                extensions.append(doc)

    merged = merge_semantic_models(core, extensions)
    merged["_source_path"] = str(core_path)
    merged["_extension_paths"] = [e.get("_source_path") for e in extensions]
    return merged
