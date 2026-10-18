"""Choose a frozen visual template for a result and emit a renderer-neutral chart spec."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from ai4bi.config.errors import ConfigError
from ai4bi.semantic.models import DomainPackage
from ai4bi.utils.frames import as_number

_TIME_LABEL = re.compile(r"(period|date|month|quarter|week|year|day|_at$)", re.IGNORECASE)
MAX_BAR_ROWS = 50


class VisualizationBuilder:
    def __init__(self, templates_path: Path) -> None:
        self.templates_path = Path(templates_path)
        if not self.templates_path.exists():
            raise ConfigError(f"Visual templates file not found: {self.templates_path}")
        payload = yaml.safe_load(self.templates_path.read_text(encoding="utf-8")) or {}
        self.templates = {t["id"]: t for t in payload.get("templates") or [] if t.get("id")}
        if not self.templates:
            raise ConfigError(f"{self.templates_path} defines no templates")

    def validate_bindings(self, pkg: DomainPackage) -> list[str]:
        errors: list[str] = []
        for binding in pkg.visuals:
            template = self.templates.get(binding.get("template"))
            if template is None:
                errors.append(f"{binding.get('id')}: unknown template {binding.get('template')}")
                continue
            missing = [k for k in template.get("required_bindings") or [] if not binding.get(k)]
            if missing:
                errors.append(f"{binding.get('id')}: missing {missing}")
        return errors

    def choose(self, plan: dict[str, Any], preview: dict[str, Any]) -> tuple[str, list[str], list[str]]:
        rows = preview.get("rows") or []
        columns = preview.get("columns") or []
        numeric = [
            c for c in columns
            if any(as_number(r.get(c)) is not None for r in rows)
            and all(r.get(c) is None or as_number(r.get(c)) is not None for r in rows)
        ]
        labels = [c for c in columns if c not in numeric]
        intent = str(plan.get("intent") or "")
        if not rows or not numeric:
            return "table", labels, numeric
        if len(rows) == 1 and not labels:
            return "kpi_card", labels, numeric
        if labels and (intent == "trend" or _TIME_LABEL.search(labels[0])):
            return "trend", labels, numeric
        if len(labels) >= 2:
            return "root_cause", labels, numeric
        if len(labels) == 1 and len(rows) <= MAX_BAR_ROWS:
            return "comparison", labels, numeric
        return "table", labels, numeric

    def build(self, plan: dict[str, Any], preview: dict[str, Any], pkg: DomainPackage | None = None) -> dict[str, Any]:
        rows = preview.get("rows") or []
        if not rows:
            return {}
        template_id, labels, numeric = self.choose(plan, preview)
        template = self.templates.get(template_id) or self.templates.get("table") or {}
        metric = (plan.get("metrics") or [{}])[0] if plan.get("metrics") else {}
        metric_id = metric.get("id") or metric.get("name")
        binding = None
        if pkg is not None:
            binding = next(
                (b for b in pkg.visuals if b.get("template") == template_id and b.get("metric_id") == metric_id),
                None,
            )
        spec: dict[str, Any] = {
            "template": template_id,
            "chart_type": template.get("chart_type", template_id),
            "title": str(metric.get("name") or template.get("title") or "Result"),
            "purpose": template.get("purpose"),
            "metric_id": metric_id,
            "binding_id": binding.get("id") if binding else None,
            "x": labels[0] if labels else None,
            "y": numeric,
            "series": labels[1] if len(labels) > 1 else None,
            "data": rows,
        }
        if template_id == "kpi_card":
            spec["value"] = rows[0][numeric[0]]
            spec["unit"] = metric.get("unit") or ""
        return spec
