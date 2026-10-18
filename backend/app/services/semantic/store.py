"""Read-only access to the baseline semantic packages shipped with the service, plus the
lookups the pipeline runs against a loaded package (metric resolution, prompt context).

Anything learned or changed at runtime lives in the registry (``registry_store``), never here.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

from app.errors import DomainNotFoundError
from app.services.common.text import content_tokens, overlap_score, phrase_in
from app.services.semantic.loader import align_with_frames, load_domain_package, package_from_frames
from app.services.semantic.models import DomainPackage, GlossaryTerm, MetricVersion
from app.services.semantic.pii import inferred_restricted_columns
from app.services.semantic.registry import SemanticRegistry

LOGGER = logging.getLogger(__name__)


class SemanticStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._cache: dict[str, DomainPackage] = {}

    # ----- packages ---------------------------------------------------------

    def domain_dir(self, domain: str) -> Path:
        return self.root / domain

    def exists(self, domain: str) -> bool:
        return (self.domain_dir(domain) / "contract.yaml").exists()

    def list_domains(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if (p / "contract.yaml").exists())

    def load(self, domain: str, *, refresh: bool = False) -> DomainPackage:
        if refresh or domain not in self._cache:
            if not self.exists(domain):
                known = ", ".join(self.list_domains()) or "(none)"
                raise DomainNotFoundError(f"Domain {domain!r} not found. Known domains: {known}")
            self._cache[domain] = load_domain_package(self.domain_dir(domain))
        return self._cache[domain]

    def load_or_infer(self, domain: str, frames: dict[str, pd.DataFrame] | None) -> DomainPackage:
        if self.exists(domain):
            pkg = self.load(domain)
            return align_with_frames(pkg, frames) if frames else pkg
        if frames:
            LOGGER.info("No semantic package for %s; inferring one from %s", domain, sorted(frames))
            return package_from_frames(domain, frames, pii_columns=sorted(inferred_restricted_columns(frames)))
        raise DomainNotFoundError(f"Domain {domain!r} has no semantic package and no datasets were supplied.")

    def load_with_registry(
        self,
        domain: str,
        frames: dict[str, pd.DataFrame],
        registry: SemanticRegistry,
        *,
        include_drafts: bool = False,
    ) -> DomainPackage:
        """Load configured or inferred semantics, then overlay learned artifacts."""
        package = self.load_or_infer(domain, frames)
        package = align_with_frames(package, frames)
        return registry.overlay(package, include_drafts=include_drafts)

    # ----- grounding hints --------------------------------------------------

    @staticmethod
    def column_notes(pkg: DomainPackage) -> dict[str, str]:
        notes: dict[str, str] = {}
        for entity in pkg.entities:
            for column in entity.columns:
                if column.description and column.name not in notes:
                    notes[column.name] = column.description
        return notes

    @staticmethod
    def filter_aliases(pkg: DomainPackage) -> list[tuple[str, str]]:
        """(term, stored value) pairs. Applied only when the value is actually stored."""
        pairs: list[tuple[str, str]] = []
        seen: set[str] = set()
        for term in pkg.glossary:
            if term.maps_to_kind != "filter_value" or not term.canonical_value:
                continue
            key = term.term.lower()
            if key not in seen:
                seen.add(key)
                pairs.append((term.term, term.canonical_value))
        pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
        return pairs

    # ----- metric resolution ------------------------------------------------

    @staticmethod
    def resolve_terms(question: str, pkg: DomainPackage) -> list[GlossaryTerm]:
        return [t for t in pkg.glossary if phrase_in(question, t.term)]

    def bind_metric_family(self, question: str, pkg: DomainPackage) -> str | None:
        for term in self.resolve_terms(question, pkg):
            if term.maps_to_kind == "metric_family":
                return term.maps_to_id
        for kpi in pkg.dictionary.kpis:
            if any(phrase_in(question, n) for n in [kpi.family, kpi.name, *kpi.synonyms] if n):
                return kpi.family
        return None

    @staticmethod
    def detect_scope(question: str, pkg: DomainPackage, default: str = "global") -> str:
        scopes = {m.scope.lower() for m in pkg.metrics}
        for kpi in pkg.dictionary.kpis:
            scopes.update(s.lower() for s in kpi.scopes)
        aliases = dict(pkg.business_unit.scope_aliases) if pkg.business_unit else {}
        aliases.update({s: s for s in scopes})
        for token, scope in sorted(aliases.items(), key=lambda kv: len(kv[0]), reverse=True):
            if phrase_in(question, token):
                return scope.lower()
        return default

    def resolve_metric(self, question: str, pkg: DomainPackage) -> MetricVersion | None:
        family = self.bind_metric_family(question, pkg)
        if not family:
            return None
        candidates = [m for m in pkg.metrics if m.family == family and m.status != "deprecated"]
        if not candidates:
            return None
        scope = self.detect_scope(question, pkg)
        exact = next((m for m in candidates if m.scope.lower() == scope), None)
        if exact:
            return exact
        return next((m for m in candidates if m.default_for_family), candidates[0])

    # ----- prompt context ---------------------------------------------------

    def relevant_context(self, pkg: DomainPackage, question: str, *, limit: int = 5) -> dict[str, Any]:
        """Only the semantic objects that relate to this question."""
        words = content_tokens(question)

        def score(*parts: Any) -> int:
            return overlap_score(question, " ".join(str(p) for p in parts if p))

        rules = []
        for rule in pkg.rules:
            hit = score(rule.description, " ".join(rule.keywords), " ".join(rule.applies_to))
            if hit or any(phrase_in(question, k) for k in rule.keywords):
                rules.append((hit, rule.model_dump()))
        examples = [(score(e.question), e.model_dump()) for e in pkg.query_examples]
        validated = [(score(v.question), v.model_dump()) for v in pkg.validated_sql]

        def top(items: list[tuple[int, dict]]) -> list[dict]:
            ranked = sorted((i for i in items if i[0] > 0), key=lambda i: i[0], reverse=True)
            return [item for _, item in ranked[:limit]]

        return {
            "business_unit": pkg.business_unit.model_dump() if pkg.business_unit else None,
            "business_rules": top(rules),
            "query_examples": top(examples),
            "validated_sql_examples": top(validated),
            "question_terms": sorted(words),
        }


def scope_filter_value(metric: MetricVersion) -> tuple[str, str] | None:
    flt = (metric.compute or {}).get("filter") or {}
    if flt.get("column") and flt.get("value") is not None:
        return str(flt["column"]), str(flt["value"])
    match = re.match(r"^\s*(\w+)\s*=\s*'([^']*)'\s*$", metric.filter_sql or "")
    if match:
        return match.group(1), match.group(2)
    return None
