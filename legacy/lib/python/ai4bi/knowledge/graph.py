"""In-memory knowledge graph: entities, columns, joins, metrics, terms, questions.

The graph grows after every answered question. Storage is handled by a store.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ai4bi.utils.text import slug


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeGraph:
    def __init__(self, domain: str) -> None:
        self.domain = domain
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, str]] = []
        self.episodes: list[dict[str, Any]] = []
        self._edge_keys: set[tuple[str, str, str]] = set()

    # ----- serialization ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "updated_at": _now(),
            "nodes": list(self.nodes.values()),
            "edges": list(self.edges),
            "episodes": list(self.episodes),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any], domain: str | None = None) -> "KnowledgeGraph":
        graph = cls(domain or str(payload.get("domain") or "default"))
        for node in payload.get("nodes") or []:
            if node.get("id"):
                graph.nodes[node["id"]] = node
        for edge in payload.get("edges") or []:
            graph.add_edge(edge.get("src", ""), edge.get("rel", ""), edge.get("dst", ""))
        graph.episodes = list(payload.get("episodes") or [])
        return graph

    def stats(self) -> dict[str, int]:
        return {"nodes": len(self.nodes), "edges": len(self.edges), "episodes": len(self.episodes)}

    # ----- mutation ---------------------------------------------------------

    def upsert_node(self, node_id: str, kind: str, label: str, **props: Any) -> None:
        existing = self.nodes.get(node_id) or {"id": node_id, "kind": kind, "label": label, "props": {}}
        existing["kind"] = kind
        existing["label"] = label or existing.get("label") or node_id
        merged = dict(existing.get("props") or {})
        merged.update({k: v for k, v in props.items() if v is not None})
        existing["props"] = merged
        existing["updated_at"] = _now()
        self.nodes[node_id] = existing

    def add_edge(self, src: str, rel: str, dst: str) -> None:
        if not (src and rel and dst):
            return
        key = (src, rel, dst)
        if key not in self._edge_keys:
            self._edge_keys.add(key)
            self.edges.append({"src": src, "rel": rel, "dst": dst})

    def record_episode(self, episode: dict[str, Any]) -> None:
        """Store one answered question and link what it used and learned."""
        self.episodes.append(episode)
        qid = str(episode.get("question_id") or f"q.{len(self.episodes)}")
        self.upsert_node(
            qid,
            "question",
            str(episode.get("question") or "")[:240],
            intent=episode.get("intent"),
            sql=episode.get("sql"),
            status=episode.get("status"),
            answer_excerpt=episode.get("answer_excerpt"),
        )
        for metric in episode.get("metrics") or []:
            if not isinstance(metric, dict):
                continue
            mid = metric.get("id") or "metric." + slug(str(metric.get("name") or "unnamed"))
            existing = self.nodes.get(mid)
            self.upsert_node(
                mid,
                "metric",
                str(metric.get("name") or (existing or {}).get("label") or mid),
                calculation=metric.get("calculation") or metric.get("sql_expression"),
                sql_expression=metric.get("sql_expression"),
                grain=metric.get("grain"),
                source=(existing or {}).get("props", {}).get("source") or "llm",
                last_question=episode.get("question"),
            )
            self.add_edge(qid, "uses_metric", mid)
        for calc in episode.get("calculations") or []:
            if not isinstance(calc, dict):
                continue
            cid = "calc." + slug(str(calc.get("name") or "unnamed"))
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
        if sql and episode.get("status") == "success":
            sid = "sql." + slug(sql[:80])
            self.upsert_node(sid, "sql_pattern", sql[:240], full_sql=sql, status=episode.get("status"))
            self.add_edge(qid, "produced_sql", sid)
        for table in episode.get("datasets") or []:
            for node_id, node in self.nodes.items():
                if node.get("kind") == "entity" and node.get("props", {}).get("physical_dataset") == table:
                    self.add_edge(qid, "queried", node_id)
        for term in episode.get("new_terms") or []:
            if not isinstance(term, dict):
                continue
            tid = "term." + slug(str(term.get("term") or ""))
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

    # ----- queries ----------------------------------------------------------

    def neighbors(self, node_id: str) -> list[str]:
        out = [e["dst"] for e in self.edges if e["src"] == node_id]
        out += [e["src"] for e in self.edges if e["dst"] == node_id]
        return out

    def nodes_of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [n for n in self.nodes.values() if n.get("kind") == kind]
