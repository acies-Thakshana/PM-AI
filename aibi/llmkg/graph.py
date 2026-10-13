"""JSON knowledge graph that grows after every question."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aibi.settings import PROJECT_ROOT


def graph_path(domain: str) -> Path:
    return PROJECT_ROOT / "knowledge_graph" / f"{domain}.json"


class KnowledgeGraph:
    def __init__(self, domain: str, path: Path | None = None) -> None:
        self.domain = domain
        self.path = path or graph_path(domain)
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, str]] = []
        self.episodes: list[dict[str, Any]] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.nodes = {n["id"]: n for n in payload.get("nodes") or [] if n.get("id")}
        self.edges = list(payload.get("edges") or [])
        self.episodes = list(payload.get("episodes") or [])

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return self.path

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "nodes": list(self.nodes.values()),
            "edges": self.edges,
            "episodes": self.episodes,
        }

    def upsert_node(self, node_id: str, kind: str, label: str, **props: Any) -> None:
        existing = self.nodes.get(node_id) or {"id": node_id, "kind": kind, "label": label, "props": {}}
        existing["kind"] = kind
        existing["label"] = label or existing.get("label") or node_id
        merged = dict(existing.get("props") or {})
        merged.update({k: v for k, v in props.items() if v is not None})
        existing["props"] = merged
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.nodes[node_id] = existing

    def add_edge(self, src: str, rel: str, dst: str) -> None:
        edge = {"src": src, "rel": rel, "dst": dst}
        if edge not in self.edges:
            self.edges.append(edge)

    def subgraph_for_question(self, question: str, limit: int = 40) -> dict[str, Any]:
        """Retrieve nodes whose labels or props overlap the question. Stable RAG slice."""
        q = (question or "").lower()
        scored: list[tuple[int, dict[str, Any]]] = []
        for node in self.nodes.values():
            blob = " ".join(
                [
                    str(node.get("id") or ""),
                    str(node.get("kind") or ""),
                    str(node.get("label") or ""),
                    json.dumps(node.get("props") or {}, default=str),
                ]
            ).lower()
            score = sum(1 for token in q.split() if len(token) > 2 and token in blob)
            if node.get("kind") in {"join", "entity", "column", "metric", "glossary"}:
                score += 1
            if score:
                scored.append((score, node))
        scored.sort(key=lambda item: item[0], reverse=True)
        nodes = [n for _, n in scored[:limit]]
        ids = {n["id"] for n in nodes}
        edges = [e for e in self.edges if e["src"] in ids or e["dst"] in ids]
        return {"nodes": nodes, "edges": edges, "episode_count": len(self.episodes)}

    def record_episode(self, episode: dict[str, Any]) -> None:
        self.episodes.append(episode)
        qid = str(episode.get("question_id") or f"q.{len(self.episodes)}")
        self.upsert_node(
            qid,
            "question",
            str(episode.get("question") or "")[:240],
            intent=episode.get("intent"),
            sql=episode.get("sql"),
            status=episode.get("status"),
        )
        for metric in episode.get("metrics") or []:
            mid = "metric." + _slug(str(metric.get("name") or "unnamed"))
            self.upsert_node(
                mid,
                "metric",
                str(metric.get("name") or mid),
                calculation=metric.get("calculation") or metric.get("sql_expression"),
                sql_expression=metric.get("sql_expression"),
                grain=metric.get("grain"),
                source="llm",
                last_question=episode.get("question"),
            )
            self.add_edge(qid, "uses_metric", mid)
        for calc in episode.get("calculations") or []:
            cid = "calc." + _slug(str(calc.get("name") or "unnamed"))
            self.upsert_node(
                cid,
                "calculation",
                str(calc.get("name") or cid),
                formula=calc.get("formula"),
                rationale=calc.get("rationale"),
                source="llm",
            )
            self.add_edge(qid, "uses_calculation", cid)
        sql = episode.get("sql") or ""
        if sql:
            sid = "sql." + _slug(sql[:80])
            self.upsert_node(sid, "sql_pattern", sql[:240], full_sql=sql, status=episode.get("status"))
            self.add_edge(qid, "produced_sql", sid)
        for term in episode.get("new_terms") or []:
            tid = "term." + _slug(str(term.get("term") or ""))
            if tid == "term.":
                continue
            self.upsert_node(
                tid,
                "glossary",
                str(term.get("term") or tid),
                maps_to=term.get("maps_to"),
                term_kind=term.get("kind") or "synonym",
                source="llm_feedback",
            )
            self.add_edge(qid, "introduced_term", tid)


def _slug(text: str) -> str:
    keep = []
    for ch in (text or "").lower():
        if ch.isalnum():
            keep.append(ch)
        elif keep and keep[-1] != "_":
            keep.append("_")
    return "".join(keep).strip("_")[:80]
