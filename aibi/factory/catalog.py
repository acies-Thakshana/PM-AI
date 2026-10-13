"""Versioned KPI catalog. Changing a formula never touches prompts or agents."""

from __future__ import annotations

import re

from aibi.factory.glossary import bind_metric_family
from aibi.factory.models import DomainPackage, MetricVersion

_SCOPE_ALIASES = {
    "emea": "emea",
    "europe": "emea",
    "apac": "apac",
    "asia": "apac",
    "global": "global",
    "worldwide": "global",
}


def detect_scope(question: str, default: str = "global") -> str:
    q = (question or "").lower()
    for token, scope in _SCOPE_ALIASES.items():
        if re.search(rf"\b{re.escape(token)}\b", q):
            return scope
    return default


def metrics_for_family(pkg: DomainPackage, family: str) -> list[MetricVersion]:
    return [m for m in pkg.metrics if m.family == family and m.status != "deprecated"]


def resolve_metric(
    question: str,
    pkg: DomainPackage,
    *,
    user_scope: str | None = None,
) -> MetricVersion | None:
    family = bind_metric_family(question, pkg)
    if not family:
        return None
    scoped = detect_scope(question, default=user_scope or "global")
    candidates = metrics_for_family(pkg, family)
    exact = next((m for m in candidates if m.scope == scoped), None)
    if exact:
        return exact
    return next((m for m in candidates if m.default_for_family), candidates[0] if candidates else None)
