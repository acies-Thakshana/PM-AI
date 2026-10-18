from __future__ import annotations

from pathlib import Path

from ai4bi.knowledge.documents import ingest_documents
from ai4bi.knowledge.graph import KnowledgeGraph
from ai4bi.knowledge.history import HistoryStore
from ai4bi.knowledge.retrieval import prior_sql_patterns, related_episodes, subgraph_for_question
from ai4bi.knowledge.seed import seed_from_package
from ai4bi.knowledge.store import JsonGraphStore, graph_from_records, graph_to_records


def _episode(**overrides):
    episode = {
        "question_id": "q.1",
        "question": "What is EMEA FRT?",
        "intent": "aggregation",
        "metrics": [{"id": "metric.frt.emea", "name": "First Response Time (emea)", "sql_expression": "AVG(x)"}],
        "calculations": [{"name": "frt", "formula": "AVG(x)", "rationale": "certified"}],
        "new_terms": [{"term": "first reply", "maps_to": "metric.frt.emea"}],
        "sql": "SELECT AVG(x) FROM cases WHERE region = 'EMEA'",
        "datasets": ["cases"],
        "status": "success",
    }
    episode.update(overrides)
    return episode


def test_seed_contains_semantic_layer(ctx):
    graph = KnowledgeGraph("service_ops")
    seed_from_package(graph, ctx.semantic.load("service_ops"))
    kinds = {n["kind"] for n in graph.nodes.values()}
    assert {"entity", "column", "metric", "join", "glossary", "business_rule", "business_unit", "pii"} <= kinds
    assert any(n["kind"] == "sql_pattern" for n in graph.nodes.values())


def test_record_episode_links_metric_sql_and_terms(ctx):
    graph = KnowledgeGraph("service_ops")
    seed_from_package(graph, ctx.semantic.load("service_ops"))
    graph.record_episode(_episode())
    assert "q.1" in graph.nodes
    rels = {(e["src"], e["rel"]) for e in graph.edges}
    assert ("q.1", "uses_metric") in rels
    assert ("q.1", "produced_sql") in rels
    assert ("q.1", "introduced_term") in rels
    assert ("q.1", "queried") in rels


def test_failed_episode_does_not_become_a_sql_pattern():
    graph = KnowledgeGraph("d")
    graph.record_episode(_episode(status="execution_failed"))
    assert not graph.nodes_of_kind("sql_pattern")


def test_edges_are_deduplicated():
    graph = KnowledgeGraph("d")
    graph.add_edge("a", "r", "b")
    graph.add_edge("a", "r", "b")
    assert len(graph.edges) == 1


def test_retrieval_prefers_related_nodes(ctx):
    graph = KnowledgeGraph("service_ops")
    seed_from_package(graph, ctx.semantic.load("service_ops"))
    graph.record_episode(_episode())
    subgraph = subgraph_for_question(graph, "EMEA first response time", 20)
    labels = " ".join(n["label"].lower() for n in subgraph["nodes"])
    assert "first response" in labels
    assert prior_sql_patterns(subgraph, 5)
    assert related_episodes(graph, "EMEA FRT please")


def test_json_store_round_trip(tmp_path: Path):
    store = JsonGraphStore(tmp_path)
    graph = KnowledgeGraph("d")
    graph.upsert_node("n1", "entity", "Cases")
    graph.record_episode(_episode())
    store.save(graph)
    loaded = store.load("d")
    assert loaded.stats() == graph.stats()
    assert store.load("missing").stats() == {"nodes": 0, "edges": 0, "episodes": 0}


def test_record_round_trip_for_tabular_storage():
    graph = KnowledgeGraph("d")
    graph.record_episode(_episode())
    records = graph_to_records(graph)
    assert {r["record_type"] for r in records} == {"node", "edge", "episode"}
    assert graph_from_records("d", records).stats() == graph.stats()


def test_documents_become_fact_nodes(tmp_path: Path):
    folder = tmp_path / "documents"
    folder.mkdir()
    (folder / "notes.md").write_text(
        "# Title\n\nFirst response time is measured in hours from case creation.\n\n"
        "The EMEA region covers Europe, the Middle East, and Africa.\n",
        encoding="utf-8",
    )
    graph = KnowledgeGraph("d")
    added = ingest_documents(graph, folder)
    assert added >= 2
    assert any("hours" in n["label"] for n in graph.nodes_of_kind("document_fact"))
    assert ingest_documents(graph, tmp_path / "absent") == 0


def test_history_is_per_session(tmp_path: Path):
    history = HistoryStore(tmp_path)
    history.append("d", {"question": "a", "session_id": "s1"})
    history.append("d", {"question": "b", "session_id": "s2"})
    history.append("d", {"question": "c", "session_id": "s1"})
    assert [t["question"] for t in history.recent("d", session_id="s1")] == ["a", "c"]
    assert len(history.recent("d", limit=1)) == 1
