"""Graph persistence. JSON on disk locally; tabular records for platforms with datasets."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Protocol

from ai4bi.knowledge.graph import KnowledgeGraph

RECORD_COLUMNS = ("record_type", "payload")


class GraphStore(Protocol):
    def load(self, domain: str) -> KnowledgeGraph:
        ...

    def save(self, graph: KnowledgeGraph) -> Any:
        ...


class JsonGraphStore:
    """storage/knowledge_graph/<domain>.json"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path(self, domain: str) -> Path:
        return self.root / f"{domain}.json"

    def load(self, domain: str) -> KnowledgeGraph:
        target = self.path(domain)
        if not target.exists():
            return KnowledgeGraph(domain)
        payload = json.loads(target.read_text(encoding="utf-8"))
        return KnowledgeGraph.from_dict(payload, domain=domain)

    def save(self, graph: KnowledgeGraph) -> Path:
        target = self.path(graph.domain)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(graph.to_dict(), indent=2, ensure_ascii=False, default=str)
        handle, temp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temp, target)
        return target


class MemoryGraphStore:
    """Keeps graphs in memory. Used by batch runs that write the graph elsewhere."""

    def __init__(self, graphs: dict[str, KnowledgeGraph] | None = None) -> None:
        self.graphs = dict(graphs or {})

    def load(self, domain: str) -> KnowledgeGraph:
        return self.graphs.setdefault(domain, KnowledgeGraph(domain))

    def save(self, graph: KnowledgeGraph) -> KnowledgeGraph:
        self.graphs[graph.domain] = graph
        return graph


def graph_to_records(graph: KnowledgeGraph) -> list[dict[str, str]]:
    """One row per node, edge, and episode: the knowledge_graph dataset layout."""
    payload = graph.to_dict()
    rows = [{"record_type": "node", "payload": json.dumps(n, default=str)} for n in payload["nodes"]]
    rows += [{"record_type": "edge", "payload": json.dumps(e)} for e in payload["edges"]]
    rows += [{"record_type": "episode", "payload": json.dumps(e, default=str)} for e in payload["episodes"]]
    return rows


def graph_from_records(domain: str, records: Iterable[dict[str, Any]]) -> KnowledgeGraph:
    graph = KnowledgeGraph(domain)
    for row in records:
        raw = row.get("payload")
        if raw is None or (isinstance(raw, float) and raw != raw):
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        kind = str(row.get("record_type") or "")
        if kind == "node" and payload.get("id"):
            graph.nodes[payload["id"]] = payload
        elif kind == "edge":
            graph.add_edge(payload.get("src", ""), payload.get("rel", ""), payload.get("dst", ""))
        elif kind == "episode":
            graph.episodes.append(payload)
    return graph
