from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd

from ai4bi.evaluation.scoring import results_match, score_results

LIB = Path(__file__).resolve().parents[2] / "lib" / "python"


def test_results_match_ignores_column_names_and_scale():
    left = pd.DataFrame({"region": ["EMEA"], "ratio": [0.25]})
    right = pd.DataFrame({"r": ["EMEA"], "pct": [25.0]})
    assert results_match(left, right)
    assert not results_match(left, pd.DataFrame({"r": ["EMEA"], "pct": [30.0]}))


def test_score_results_outcomes(ctx, service_frames):
    results = pd.DataFrame(
        {
            "question": ["a", "b", "c", "d"],
            "Expected_SQL_Query": [
                "SELECT COUNT(*) FROM cases",
                "SELECT COUNT(*) FROM cases",
                "SELECT COUNT(*) FROM cases",
                "",
            ],
            "LLM_generated_SQL": ["SELECT COUNT(*) AS n FROM cases", "SELECT 99", "SELECT nope FROM cases", ""],
            "latency_seconds": [0.1, 0.2, 0.3, 0.1],
            "confidence": [0.9, 0.4, 0.6, None],
        }
    )
    detail, summary = score_results(results, service_frames, ctx.executor)
    assert detail["outcome"].tolist() == ["correct", "wrong_value", "sql_error", "not_scored"]
    assert summary["questions"] == 3
    assert summary["accuracy"] == round(1 / 3, 4)
    assert summary["outcome_counts"]["not_scored"] == 1


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_core_never_imports_dataiku():
    offenders = [str(p) for p in (LIB / "ai4bi").rglob("*.py") if "dataiku" in _imports(p)]
    assert offenders == []


def test_core_never_imports_the_adapter():
    offenders = [str(p) for p in (LIB / "ai4bi").rglob("*.py") if "ai4bi_dataiku" in _imports(p)]
    assert offenders == []


def test_core_imports_without_dataiku_installed():
    import importlib
    import sys

    assert "dataiku" not in sys.modules or getattr(sys.modules["dataiku"], "__file__", None) is None
    for module in ("ai4bi.pipeline", "ai4bi.sql.validator", "ai4bi.knowledge.store", "ai4bi_dataiku"):
        importlib.import_module(module)
