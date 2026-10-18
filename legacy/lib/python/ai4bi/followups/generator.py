"""Suggested next questions from the semantic layer and the knowledge graph."""

from __future__ import annotations

from typing import Any

from ai4bi.knowledge.graph import KnowledgeGraph
from ai4bi.knowledge.retrieval import related_episodes
from ai4bi.semantic.models import DomainPackage
from ai4bi.utils.text import content_tokens


def _same(left: str, right: str) -> bool:
    return left.strip().lower().rstrip("?") == right.strip().lower().rstrip("?")


class FollowupGenerator:
    def __init__(self, templates: list[str], max_suggestions: int = 3) -> None:
        self.templates = list(templates)
        self.max_suggestions = max_suggestions

    def suggest(
        self,
        question: str,
        *,
        pkg: DomainPackage,
        plan: dict[str, Any] | None = None,
        graph: KnowledgeGraph | None = None,
        available_columns: set[str] | None = None,
    ) -> list[str]:
        plan = plan or {}
        out: list[str] = []
        asked = content_tokens(question)

        def add(candidate: str) -> None:
            text = candidate.strip()
            if not text or _same(text, question) or any(_same(text, o) for o in out):
                return
            if content_tokens(text) <= asked:
                return
            out.append(text)

        metric = (plan.get("metrics") or [{}])[0] if plan.get("metrics") else {}
        metric_name = str(metric.get("name") or "")
        used_dims = {str(d) for d in plan.get("dimensions") or []}
        used_filters = set((plan.get("filters") or {}).keys())

        dims = [d for d in self._dimensions(pkg, available_columns) if d not in used_dims and d not in used_filters]
        if metric_name and self.templates:
            for index, dim in enumerate(dims[: self.max_suggestions - 1]):
                template = self.templates[index % len(self.templates)]
                add(template.format(metric=self._metric_label(metric_name), dimension=dim.replace("_", " ")))

        family = metric.get("id")
        sibling = next((m for m in pkg.metrics if m.id == family), None)
        if sibling:
            for other in pkg.metrics:
                if other.family == sibling.family and other.id != sibling.id and other.status != "deprecated":
                    add(f"What is {self._metric_label(other.name)}?")

        for candidate in self._library(pkg, question):
            add(candidate)
        if graph is not None:
            for episode in related_episodes(graph, question):
                add(str(episode.get("question") or ""))
        return out[: self.max_suggestions]

    @staticmethod
    def _metric_label(name: str) -> str:
        return name.replace("(global)", "").strip()

    @staticmethod
    def _dimensions(pkg: DomainPackage, available: set[str] | None) -> list[str]:
        restricted = {c.lower() for c in pkg.restricted_columns()}
        dims = [str(d) for d in (pkg.drills or {}).get("dimensions") or []]
        if not dims:
            for entity in pkg.entities:
                dims.extend(c.name for c in entity.columns if c.role == "attribute")
        seen: list[str] = []
        for dim in dims:
            if dim.lower() in restricted or dim in seen:
                continue
            if available is not None and dim not in available:
                continue
            seen.append(dim)
        return seen

    @staticmethod
    def _library(pkg: DomainPackage, question: str) -> list[str]:
        """Harvested dashboard questions and stored examples, most related first."""
        candidates: list[str] = [q.question for q in pkg.query_examples]
        if pkg.harvest:
            for metric in pkg.harvest.metrics:
                candidates.extend(metric.business_questions)
        words = content_tokens(question)
        return sorted(candidates, key=lambda c: len(words & content_tokens(c)), reverse=True)

    def starter_questions(self, pkg: DomainPackage) -> list[str]:
        return self._library(pkg, "")[: self.max_suggestions]
