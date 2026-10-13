"""Reusable glossary framework. Domains only populate terms."""

from __future__ import annotations

import re

from aibi.factory.models import DomainPackage, GlossaryTerm


def resolve_terms(question: str, pkg: DomainPackage) -> list[GlossaryTerm]:
    q = re.sub(r"\s+", " ", (question or "").strip().lower())
    hits: list[GlossaryTerm] = []
    for term in pkg.glossary:
        token = term.term.strip().lower()
        if token and re.search(rf"\b{re.escape(token)}\b", q):
            hits.append(term)
    return hits


def bind_metric_family(question: str, pkg: DomainPackage) -> str | None:
    for term in resolve_terms(question, pkg):
        if term.maps_to_kind == "metric_family":
            return term.maps_to_id
    q = (question or "").lower()
    for kpi in pkg.dictionary.kpis:
        names = [kpi.family, kpi.name, *kpi.synonyms]
        if any(n.lower() in q for n in names if n):
            return kpi.family
    return None
