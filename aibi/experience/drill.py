"""Reusable drill engine. Per project: entities, dimensions, filters, actions."""

from __future__ import annotations

from typing import Any

from aibi.settings import PROJECT_ROOT, load_yaml

ALLOWED_KEYS = {"entities", "dimensions", "filters", "actions"}


def load_drills(domain: str) -> dict[str, Any]:
    path = PROJECT_ROOT / "onboarding" / "domains" / domain / "drills.yaml"
    return load_yaml(path) or {}


def apply_drill(
    domain: str,
    *,
    path_id: str,
    current_filters: dict[str, Any] | None = None,
    dimension: str,
    value: str,
) -> dict[str, Any]:
    cfg = load_drills(domain)
    path = next((p for p in cfg.get("paths") or [] if p.get("id") == path_id), None)
    if not path:
        raise ValueError(f"Unknown drill path: {path_id}")
    allowed_dims = set(cfg.get("dimensions") or [])
    if dimension not in allowed_dims:
        raise ValueError(
            f"Dimension {dimension!r} is not in this domain's drill dimensions"
        )
    step = next(
        (s for s in path.get("steps") or [] if s.get("dimension") == dimension),
        None,
    )
    if not step:
        raise ValueError(f"Dimension {dimension!r} is not on path {path_id}")
    filters = dict(current_filters or {})
    filters[dimension] = value
    return {
        "path_id": path_id,
        "entity": path.get("start_entity"),
        "action": step.get("action"),
        "applied_filters": filters,
        "next_dimensions": [
            s["dimension"]
            for s in path.get("steps") or []
            if s.get("dimension") != dimension
        ],
        "allowed_actions": list(cfg.get("actions") or []),
    }


def project_only_config(cfg: dict[str, Any]) -> dict[str, Any]:
    return {key: cfg.get(key) or [] for key in ALLOWED_KEYS}
