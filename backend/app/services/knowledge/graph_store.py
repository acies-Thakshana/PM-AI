"""Where knowledge graphs live: JSON files locally, a DynamoDB table on AWS.

``save`` persists only what changed since the graph was loaded. Locally that is applied on top of
the file's current content under a lock; on AWS each node, edge and episode is its own item, so
concurrent requests add items side by side. Either way two simultaneous questions both keep
their episode.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Protocol

# AWS-DISABLED: from app.services.common import dynamo
from app.services.knowledge.graph import GraphChanges, KnowledgeGraph


class GraphStore(Protocol):
    def load(self, domain: str) -> KnowledgeGraph:
        """The stored graph, or an empty one for a domain that has none yet."""
        ...

    def save(self, graph: KnowledgeGraph) -> None:
        """Persist the changes made to ``graph`` since it was loaded."""
        ...


class LocalGraphStore:
    """``<root>/<domain>.json``. Keeps only the newest ``max_episodes`` episodes."""

    def __init__(self, root: Path, max_episodes: int) -> None:
        self._root = Path(root)
        self._max_episodes = max_episodes
        self._lock = threading.Lock()

    def _path(self, domain: str) -> Path:
        return self._root / f"{domain}.json"

    def _read(self, domain: str) -> KnowledgeGraph:
        path = self._path(domain)
        if not path.exists():
            return KnowledgeGraph(domain)
        return KnowledgeGraph.from_dict(json.loads(path.read_text(encoding="utf-8")), domain=domain)

    def load(self, domain: str) -> KnowledgeGraph:
        with self._lock:
            return self._read(domain)

    def save(self, graph: KnowledgeGraph) -> None:
        changes = graph.drain_changes()
        if not changes:
            return
        with self._lock:
            stored = self._read(graph.domain)
            stored.apply(changes)
            stored.episodes = stored.episodes[-self._max_episodes :]
            self._root.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=str(self._root), suffix=".tmp")
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(stored.to_dict(), stream, ensure_ascii=False, default=str)
            os.replace(temporary, self._path(graph.domain))


# AWS-DISABLED: class DynamoGraphStore:
# AWS-DISABLED:     """Partition ``domain``; sort key ``node#<id>``, ``edge#<src>|<rel>|<dst>`` or ``episode#<ts>#<id>``.

# AWS-DISABLED:     Loading reads every node and edge but only the newest ``max_episodes`` episodes, which keeps
# AWS-DISABLED:     the cost of a request bounded as the history grows. Episodes expire after ``ttl_days``.
# AWS-DISABLED:     """

# AWS-DISABLED:     def __init__(self, table: str, max_episodes: int, ttl_days: int) -> None:
# AWS-DISABLED:         self._table = table
# AWS-DISABLED:         self._max_episodes = max_episodes
# AWS-DISABLED:         self._ttl_days = ttl_days

# AWS-DISABLED:     def load(self, domain: str) -> KnowledgeGraph:
# AWS-DISABLED:         key = ("domain", domain)
# AWS-DISABLED:         graph = KnowledgeGraph(domain)
# AWS-DISABLED:         for item in dynamo.query(self._table, key, sort_prefix=("sort_key", "node#")):
# AWS-DISABLED:             node = json.loads(item["payload"])
# AWS-DISABLED:             graph.nodes[node["id"]] = node
# AWS-DISABLED:         for item in dynamo.query(self._table, key, sort_prefix=("sort_key", "edge#")):
# AWS-DISABLED:             edge = json.loads(item["payload"])
# AWS-DISABLED:             graph.add_edge(edge["src"], edge["rel"], edge["dst"])
# AWS-DISABLED:         newest_first = dynamo.query(
# AWS-DISABLED:             self._table, key, sort_prefix=("sort_key", "episode#"), newest_first=True, limit=self._max_episodes
# AWS-DISABLED:         )
# AWS-DISABLED:         graph.episodes = [json.loads(item["payload"]) for item in reversed(newest_first)]
# AWS-DISABLED:         graph.mark_clean()
# AWS-DISABLED:         return graph

# AWS-DISABLED:     def save(self, graph: KnowledgeGraph) -> None:
# AWS-DISABLED:         changes = graph.drain_changes()
# AWS-DISABLED:         if changes:
# AWS-DISABLED:             dynamo.batch_put(self._table, self._items(graph.domain, changes))

# AWS-DISABLED:     def _items(self, domain: str, changes: GraphChanges) -> list[dynamo.Item]:
# AWS-DISABLED:         items: list[dynamo.Item] = []
# AWS-DISABLED:         for node in changes.nodes:
# AWS-DISABLED:             items.append(self._item(domain, f"node#{node['id']}", node))
# AWS-DISABLED:         for edge in changes.edges:
# AWS-DISABLED:             items.append(self._item(domain, f"edge#{edge['src']}|{edge['rel']}|{edge['dst']}", edge))
# AWS-DISABLED:         for episode in changes.episodes:
# AWS-DISABLED:             sort_key = f"episode#{episode['recorded_at']}#{episode.get('question_id', '')}"
# AWS-DISABLED:             items.append(self._item(domain, sort_key, episode, expires=True))
# AWS-DISABLED:         return items

# AWS-DISABLED:     def _item(self, domain: str, sort_key: str, payload: dict, *, expires: bool = False) -> dynamo.Item:
# AWS-DISABLED:         item: dynamo.Item = {"domain": domain, "sort_key": sort_key, "payload": json.dumps(payload, default=str)}
# AWS-DISABLED:         if expires:
# AWS-DISABLED:             item["expires_at"] = dynamo.expiry(self._ttl_days)
# AWS-DISABLED:         return item
