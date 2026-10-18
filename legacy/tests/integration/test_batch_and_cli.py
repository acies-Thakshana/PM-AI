from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from ai4bi.evaluation.scoring import score_results
from ai4bi.pipeline import run_batch
from ai4bi.pipeline.batch import RESULT_COLUMNS
from ai4bi.pipeline.checks import check_domain

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"


def test_batch_then_evaluate(ctx, service_frames):
    questions = pd.read_csv(EXAMPLES / "questions_service_ops.csv")
    results, graph = run_batch(questions, context=ctx, domain="service_ops")
    assert list(results.columns) == RESULT_COLUMNS
    assert len(results) == len(questions)
    answered = int((results["status"] == "success").sum())
    assert answered == len(questions) - 1
    assert graph.stats()["episodes"] == answered
    _, summary = score_results(results, service_frames, ctx.executor)
    assert summary["accuracy"] == 1.0
    assert summary["outcome_counts"]["not_scored"] == 1


def test_generic_cube_examples_are_all_correct(ctx):
    questions = pd.read_csv(EXAMPLES / "questions_generic_cube.csv")
    results, _ = run_batch(questions, context=ctx, domain="generic_cube")
    frames = ctx.data.load("generic_cube")
    _, summary = score_results(results, frames, ctx.executor)
    assert summary["accuracy"] == 1.0


def test_batch_requires_a_question_column(ctx):
    from ai4bi.config.errors import DataNotFoundError

    with pytest.raises(DataNotFoundError, match="input_question"):
        run_batch(pd.DataFrame({"x": ["a"]}), context=ctx, domain="service_ops")


def test_domain_checks_pass(ctx):
    for domain in ("service_ops", "generic_cube"):
        failed = [c for c in check_domain(ctx, domain) if not c.ok]
        assert failed == [], failed


def _cli(project: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "AIBI_PROJECT_ROOT": str(project), "AIBI_LLM_MODE": "local", "AIBI_LOG_LEVEL": "WARNING"}
    return subprocess.run(
        [sys.executable, "-m", "local", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
    )


def test_cli_ask(project):
    run = _cli(project, "ask", "What is EMEA FRT?", "--domain", "service_ops")
    assert run.returncode == 0, run.stderr
    assert "2.50 hours" in run.stdout
    assert (project / "storage" / "knowledge_graph" / "service_ops.json").exists()


def test_cli_validate_and_metadata(project):
    assert _cli(project, "validate").returncode == 0
    run = _cli(project, "refresh-metadata", "--domain", "generic_cube")
    assert run.returncode == 0, run.stderr
    assert (project / "storage" / "metadata" / "generic_cube" / "dataset_catalog.json").exists()


def test_cli_batch_and_evaluate(project, tmp_path):
    out = tmp_path / "results.csv"
    run = _cli(project, "batch", str(EXAMPLES / "questions_generic_cube.csv"), "--domain", "generic_cube", "--output", str(out))
    assert run.returncode == 0, run.stderr
    run = _cli(project, "evaluate", str(out), "--domain", "generic_cube", "--output", str(tmp_path / "m.csv"))
    assert run.returncode == 0, run.stderr
    assert '"accuracy": 1.0' in run.stdout


def test_cli_reports_config_errors(project):
    run = _cli(project, "ask", "What is the total?", "--domain", "missing_domain")
    assert run.returncode == 2
    assert "Configuration error" in run.stderr


def test_cli_onboards_an_unknown_domain_without_yaml(project):
    folder = project / "storage" / "samples" / "sales"
    folder.mkdir(parents=True)
    pd.DataFrame(
        {"order_id": ["O1", "O2"], "revenue": [10.0, 20.0]}
    ).to_csv(folder / "orders.csv", index=False)
    run = _cli(project, "onboard", "--domain", "sales")
    assert run.returncode == 0, run.stderr
    registry = project / "storage" / "semantic_registry" / "sales.json"
    assert registry.exists()
    run = _cli(
        project,
        "ask",
        "What is total revenue?",
        "--domain",
        "sales",
        "--no-persist",
    )
    assert run.returncode == 0, run.stderr
    assert "30" in run.stdout
