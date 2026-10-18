"""Recipe contract against a fake dataiku module: inputs, outputs, graph carry-over."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pandas as pd
import pytest

from ai4bi.pipeline.batch import RESULT_COLUMNS

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def flow(fake_dataiku, project):
    samples = project / "storage" / "samples" / "generic_cube"
    fake_dataiku.datasets["KPI_data"] = pd.read_csv(samples / "KPI_data.csv")
    fake_dataiku.datasets["kpi_questions"] = pd.read_csv(ROOT / "examples" / "questions_generic_cube.csv")
    fake_dataiku.variables = {"AIBI_DOMAIN": "generic_cube"}
    fake_dataiku.inputs = ["KPI_data", "kpi_questions"]
    fake_dataiku.outputs = ["kpi_results", "knowledge_graph"]
    return fake_dataiku


def test_ask_recipe_writes_results_and_graph(flow):
    from ai4bi_dataiku.recipes import run_ask_recipe

    summary = run_ask_recipe()
    results = flow.written["kpi_results"]
    assert list(results.columns) == RESULT_COLUMNS
    assert len(results) == 6
    assert summary["domain"] == "generic_cube"
    assert summary["llm"] == "anthropic:claude-opus"
    graph = flow.written["knowledge_graph"]
    assert set(graph["record_type"]) == {"node", "edge", "episode"}
    assert (graph["record_type"] == "episode").sum() == 6


def test_graph_carries_over_between_runs(flow):
    from ai4bi_dataiku.recipes import run_ask_recipe

    run_ask_recipe()
    run_ask_recipe()
    graph = flow.written["knowledge_graph"]
    assert (graph["record_type"] == "episode").sum() == 12


def test_mesh_client_receives_prompts_and_uses_model_json(flow):
    flow.llm.reply = json.dumps({"answer": "From the model."})
    from ai4bi_dataiku.recipes import run_ask_recipe

    run_ask_recipe()
    assert flow.llm.calls
    roles = [role for role, _ in flow.llm.calls[0]]
    assert roles == ["system", "user"]
    assert "From the model." in flow.written["kpi_results"]["LLM_generated_answer"].tolist()


def test_explicit_connection_variable_wins(flow):
    flow.variables["AIBI_LLM_CONNECTION"] = "custom:conn"
    from ai4bi_dataiku.recipes import run_ask_recipe

    assert run_ask_recipe()["llm"] == "custom:conn"


def test_missing_question_dataset_is_reported(flow):
    flow.inputs = ["KPI_data"]
    from ai4bi.config.errors import DataNotFoundError
    from ai4bi_dataiku.recipes import run_ask_recipe

    with pytest.raises(DataNotFoundError, match="question dataset"):
        run_ask_recipe()


def test_evaluation_recipe(flow):
    from ai4bi_dataiku.recipes import run_ask_recipe, run_evaluation_recipe

    run_ask_recipe()
    flow.inputs = ["KPI_data", "kpi_results"]
    flow.outputs = ["kpi_metrics", "kpi_metrics_summary"]
    summary = run_evaluation_recipe()
    assert summary["accuracy"] == 1.0
    assert len(flow.written["kpi_metrics"]) == 6
    assert "accuracy" in flow.written["kpi_metrics_summary"]["metric"].tolist()


def test_metadata_recipe(flow):
    from ai4bi_dataiku.recipes import run_metadata_recipe

    flow.inputs = ["KPI_data"]
    flow.outputs = ["dataset_catalog"]
    summary = run_metadata_recipe()
    catalog = flow.written["dataset_catalog"]
    assert summary["columns"] == len(catalog) == 10
    assert set(catalog["dataset"]) == {"KPI_data"}


def test_recipe_files_run_as_scripts(flow, capsys):
    runpy.run_path(str(ROOT / "dataiku" / "recipes" / "ai4bi_ask_recipe.py"), run_name="__main__")
    assert '"ok": true' in capsys.readouterr().out


def test_zero_code_onboarding_and_ask_use_registry(fake_dataiku):
    from ai4bi_dataiku.recipes import run_ask_recipe, run_onboarding_recipe

    fake_dataiku.variables = {"AIBI_DOMAIN": "sales"}
    fake_dataiku.datasets["orders"] = pd.DataFrame(
        {
            "order_id": ["O1", "O2", "O3"],
            "customer_id": ["C1", "C1", "C2"],
            "revenue": [10.0, 15.0, 20.0],
        }
    )
    fake_dataiku.datasets["customers"] = pd.DataFrame(
        {"customer_id": ["C1", "C2"], "segment": ["Enterprise", "SMB"]}
    )
    fake_dataiku.inputs = ["orders", "customers"]
    fake_dataiku.outputs = [
        "dataset_catalog",
        "semantic_registry",
        "knowledge_graph",
        "onboarding_audit",
    ]
    summary = run_onboarding_recipe()
    assert summary["changed"]
    registry = fake_dataiku.written["semantic_registry"]
    assert {"entity", "metric", "join", "dictionary_kpi"} <= set(registry["artifact_type"])
    active_join = registry[
        (registry["artifact_type"] == "join") & (registry["status"] == "active")
    ]
    assert len(active_join) == 1
    assert fake_dataiku.written["dataset_catalog"]["semantic_version"].nunique() == 1
    assert {"node", "edge"} <= set(fake_dataiku.written["knowledge_graph"]["record_type"])

    fake_dataiku.datasets["questions"] = pd.DataFrame(
        {"input_question": ["What is revenue by segment?"]}
    )
    fake_dataiku.inputs = [
        "orders",
        "customers",
        "questions",
        "semantic_registry",
        "knowledge_graph",
    ]
    fake_dataiku.outputs = ["results", "knowledge_graph", "semantic_registry"]
    result = run_ask_recipe()
    assert result["semantic_changed"] is False
    row = fake_dataiku.written["results"].iloc[0]
    assert row["status"] == "success"
    assert "JOIN customers" in row["LLM_generated_SQL"]
    assert "segment" in row["LLM_generated_SQL"]


def test_onboarding_is_idempotent_and_detects_new_columns(fake_dataiku):
    from ai4bi_dataiku.recipes import run_onboarding_recipe

    fake_dataiku.variables = {"AIBI_DOMAIN": "dynamic"}
    fake_dataiku.datasets["facts"] = pd.DataFrame({"amount": [1.0, 2.0]})
    fake_dataiku.inputs = ["facts"]
    fake_dataiku.outputs = ["dataset_catalog", "semantic_registry"]
    first = run_onboarding_recipe()
    count = len(fake_dataiku.written["semantic_registry"])
    second = run_onboarding_recipe()
    assert first["changed"] and not second["changed"]
    assert len(fake_dataiku.written["semantic_registry"]) == count

    fake_dataiku.datasets["facts"]["quantity"] = [2.0, 3.0]
    third = run_onboarding_recipe()
    assert third["changed"]
    assert len(fake_dataiku.written["semantic_registry"]) > count
