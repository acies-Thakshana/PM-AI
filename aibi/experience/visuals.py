"""Reusable visual templates. Projects bind; they do not build widgets."""

from __future__ import annotations

from typing import Any

from aibi.settings import PROJECT_ROOT, load_yaml

TEMPLATES_PATH = PROJECT_ROOT / "config" / "visual_templates.yaml"


class VisualConfigError(ValueError):
    """Project binding is missing a required template field."""


def load_templates() -> list[dict[str, Any]]:
    return list((load_yaml(TEMPLATES_PATH) or {}).get("templates") or [])


def template_by_id(template_id: str) -> dict[str, Any]:
    for item in load_templates():
        if item.get("id") == template_id:
            return item
    raise VisualConfigError(f"Unknown visual template: {template_id}")


def load_bindings(domain: str) -> list[dict[str, Any]]:
    path = PROJECT_ROOT / "onboarding" / "domains" / domain / "visuals.yaml"
    return list((load_yaml(path) or {}).get("bindings") or [])


def validate_visual_bindings(domain: str) -> list[str]:
    errors: list[str] = []
    known = {t["id"] for t in load_templates()}
    for binding in load_bindings(domain):
        tid = binding.get("template")
        if tid not in known:
            errors.append(f"{binding.get('id')}: unknown template {tid}")
            continue
        required = list(template_by_id(tid).get("required_bindings") or [])
        missing = [key for key in required if not binding.get(key)]
        if missing:
            errors.append(f"{binding.get('id')}: missing {missing}")
    return errors


def render_visual(binding: dict[str, Any], rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return a frontend-agnostic spec. Streamlit / Agent Hub only render it."""
    template = template_by_id(binding["template"])
    return {
        "visual_id": binding.get("id"),
        "template": template["id"],
        "title": template["title"],
        "purpose": template["purpose"],
        "surface": binding.get("surface"),
        "metric_id": binding.get("metric_id"),
        "bindings": {
            key: binding.get(key)
            for key in (
                "columns",
                "time_dimension",
                "compare_dimension",
                "breakdown_dimensions",
                "bucket_dimension",
                "comparison_metric_id",
            )
            if binding.get(key) is not None
        },
        "data": rows or [],
        "configurable_only": True,
    }
