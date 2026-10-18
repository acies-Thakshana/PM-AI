"""Retrieve the slice of the knowledge graph that relates to one question."""

from __future__ import annotations

import json
from typing import Any

from ai4bi.knowledge.graph import KnowledgeGraph
from ai4bi.utils.text import content_tokens

STRUCTURAL_KINDS = frozenset({"join", "entity", "column", "metric", "glossary"})


def subgraph_for_question(graph: KnowledgeGraph, question: str, limit: int = 40) -> dict[str, Any]:
    """Nodes whose id, label, or properties share words with the question.

    Structural nodes get a small boost so the schema is always represented.
    """
    words = content_tokens(question)
    scored: list[tuple[int, dict[str, Any]]] = []
    for node in graph.nodes.values():
        blob = " ".join(
            [
                str(node.get("id") or ""),
                str(node.get("kind") or ""),
                str(node.get("label") or ""),
                json.dumps(node.get("props") or {}, default=str),
            ]
        ).lower()
        score = sum(1 for word in words if word in blob)
        if node.get("kind") in STRUCTURAL_KINDS:
            score += 1
        if score:
            scored.append((score, node))
    scored.sort(key=lambda item: item[0], reverse=True)
    nodes = [node for _, node in scored[:limit]]
    ids = {node["id"] for node in nodes}
    edges = [e for e in graph.edges if e["src"] in ids or e["dst"] in ids]
    return {"nodes": nodes, "edges": edges, "episode_count": len(graph.episodes)}


def prior_sql_patterns(subgraph: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    return [n for n in subgraph.get("nodes") or [] if n.get("kind") == "sql_pattern"][:limit]


def related_episodes(graph: KnowledgeGraph, question: str, limit: int = 5) -> list[dict[str, Any]]:
    """Earlier successful questions that share words with this one."""
    words = content_tokens(question)
    ranked: list[tuple[int, dict[str, Any]]] = []
    for episode in graph.episodes:
        if episode.get("status") != "success":
            continue
        other = str(episode.get("question") or "")
        if other.strip().lower() == question.strip().lower():
            continue
        score = len(words & content_tokens(other))
        if score:
            ranked.append((score, episode))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [episode for _, episode in ranked[:limit]]
