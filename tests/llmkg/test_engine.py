from __future__ import annotations

import os

import pandas as pd
import pytest

os.environ["AIBI_LLM_MODE"] = "local"

from aibi.factory.join_guard import assert_registered_joins
from aibi.factory.security_tags import assert_no_restricted_in_sql
from aibi.llmkg.engine import ask_with_graph
from aibi.llmkg.graph import KnowledgeGraph
from aibi.llmkg.seed import package_from_frame, seed_from_package


def _cube():
    return pd.DataFrame(
        {
            "BU": ["CSA", "CSA", "EMEA"],
            "Site Name": ["Alpha", "Beta", "Gamma"],
            "Actual Productivity": [10.0, 20.0, 5.0],
            "email": ["a@x.com", "b@x.com", "c@x.com"],
        }
    )


def test_answers_come_from_llm_path_and_graph_grows(tmp_path):
    frame = _cube().drop(columns=["email"])
    pkg = package_from_frame("test_cube", frame, table_name="KPI_data")
    graph = KnowledgeGraph("test_cube", path=tmp_path / "graph.json")
    seed_from_package(graph, pkg)
    before_nodes = len(graph.nodes)
    first = ask_with_graph(
        "What is the total productivity achieved so far?",
        pkg=pkg,
        frames={"KPI_data": frame},
        graph=graph,
        persist=True,
    )
    second = ask_with_graph(
        "Which sites have the highest productivity?",
        pkg=pkg,
        frames={"KPI_data": frame},
        graph=graph,
        persist=True,
    )
    assert first["answer_path"] == "llm_kg"
    assert second["answer_path"] == "llm_kg"
    assert first["intent"]
    assert first["sql_query"]
    assert first["answer"]
    assert first["metrics"]
    assert len(graph.episodes) == 2
    assert len(graph.nodes) > before_nodes
    assert (tmp_path / "graph.json").exists()
    assert second["explainability"]["knowledge_graph"]["episodes"] == 2


def test_restricted_columns_never_enter_sql():
    frame = _cube()
    pkg = package_from_frame("test_cube", frame, table_name="KPI_data", pii_columns=["email"])
    with pytest.raises(PermissionError):
        assert_no_restricted_in_sql('SELECT email, SUM("Actual Productivity") FROM KPI_data', pkg)


def test_unregistered_join_is_rejected():
    frame = _cube().drop(columns=["email"])
    pkg = package_from_frame("test_cube", frame, table_name="KPI_data")
    with pytest.raises(PermissionError):
        assert_registered_joins(
            "SELECT * FROM KPI_data a JOIN secret s ON a.BU = s.BU",
            pkg,
        )
