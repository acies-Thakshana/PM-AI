"""End-to-end questions through ai4bi.pipeline.ask with local data and no model."""

from __future__ import annotations

import pandas as pd
import pytest

from ai4bi.config.errors import DataNotFoundError, DomainNotFoundError
from ai4bi.pipeline import ask, build_context

pytestmark = pytest.mark.integration

RESPONSE_KEYS = {
    "request_id", "domain", "question", "status", "answer_path", "answer", "key_findings", "intent",
    "confidence", "metrics", "calculations", "sql_query", "datasets_used", "joins_used", "table",
    "truncated", "chart", "follow_up_questions", "warnings", "explainability", "llm", "repairs",
    "latency_seconds",
}


def _value(result: dict) -> float:
    row = result["table"]["rows"][0]
    return float(next(v for v in row.values() if isinstance(v, (int, float))))


def test_emea_frt(ctx):
    result = ask("What is EMEA FRT?", context=ctx, domain="service_ops")
    assert RESPONSE_KEYS <= set(result)
    assert result["status"] == "success"
    assert result["answer_path"] == "llm_kg"
    assert _value(result) == pytest.approx(2.5)
    assert result["answer"] == "First Response Time (emea) is 2.50 hours."
    assert result["chart"]["template"] == "kpi_card"
    assert result["follow_up_questions"]


@pytest.mark.parametrize(
    ("question", "expected"),
    [("What is APAC FRT?", 7.0), ("What is global FRT?", 4.0), ("What is AMER FRT?", 2.5)],
)
def test_scoped_metrics(ctx, question, expected):
    assert _value(ask(question, context=ctx, domain="service_ops")) == pytest.approx(expected)


def test_join_question_reports_the_registered_join(ctx):
    result = ask("What is FRT by account name?", context=ctx, domain="service_ops")
    assert result["status"] == "success"
    assert result["joins_used"] == ["join.ops.case_to_account"]
    assert result["chart"]["template"] in {"comparison", "root_cause"}


def test_restricted_request_is_refused_before_sql(ctx):
    result = ask("Show the contact email for EMEA cases", context=ctx, domain="service_ops")
    assert result["status"] == "refuse_unauthorized"
    assert result["sql_query"] == ""


def test_restricted_values_never_reach_results(ctx):
    result = ask("cases by region", context=ctx, domain="service_ops")
    assert "@example" not in str(result)


def test_unsafe_request_is_refused(ctx):
    assert ask("drop table cases", context=ctx, domain="service_ops")["status"] == "refuse_unsupported"


def test_vague_question_needs_clarification(ctx):
    result = ask("How are we performing?", context=ctx, domain="service_ops")
    assert result["status"] == "clarification_needed"
    assert "First Response Time" in result["answer"]


def test_generic_cube_productivity(ctx):
    total = ask("What is the total productivity achieved so far?", context=ctx, domain="generic_cube")
    assert _value(total) == pytest.approx(620.3)
    csa = ask("What is productivity for csa?", context=ctx, domain="generic_cube")
    assert _value(csa) == pytest.approx(215.3)


def test_supplied_frames_and_unknown_domain(ctx):
    frames = {"orders": pd.DataFrame({"region": ["a", "a", "b"], "amount": [1.0, 2.0, 5.0]})}
    result = ask("total amount by region", context=ctx, domain="adhoc", frames=frames)
    assert result["status"] == "success"
    assert {r["region"] for r in result["table"]["rows"]} == {"a", "b"}


def test_bad_llm_sql_is_repaired_by_the_local_plan(settings):
    class BadSql:
        name = "bad"

        def complete(self, system_instruction: str, user_prompt: str) -> str:
            if "SQLite" in system_instruction:
                return '{"sql_query": "DELETE FROM cases"}'
            return ""

    from ai4bi.knowledge.store import MemoryGraphStore

    ctx = build_context(settings, llm=BadSql(), configure_logging=False, history=False, graph_store=MemoryGraphStore())
    result = ask("What is EMEA FRT?", context=ctx, domain="service_ops")
    assert result["status"] == "success"
    assert "used_local_planner_sql" in result["warnings"]
    assert _value(result) == pytest.approx(2.5)


def test_graph_and_history_persist(persistent_ctx):
    first = ask("What is EMEA FRT?", context=persistent_ctx, domain="service_ops", session_id="s1")
    assert first["status"] == "success"
    graph = persistent_ctx.graphs.load("service_ops")
    assert graph.stats()["episodes"] == 1
    assert graph.nodes_of_kind("document_fact")
    assert persistent_ctx.history.recent("service_ops", session_id="s1")[0]["question"] == "What is EMEA FRT?"
    follow_up = ask("And APAC?", context=persistent_ctx, domain="service_ops", session_id="s1")
    assert follow_up["status"] == "success"
    assert _value(follow_up) == pytest.approx(7.0)
    assert persistent_ctx.graphs.load("service_ops").stats()["episodes"] == 2
    other_session = ask("And APAC?", context=persistent_ctx, domain="service_ops", session_id="s2")
    assert other_session["status"] == "clarification_needed"


def test_configuration_errors_raise(ctx, settings):
    with pytest.raises(DomainNotFoundError):
        ask("What is the total?", context=ctx, domain="nope")
    (settings.samples_root / "service_ops" / "cases.csv").unlink()
    with pytest.raises(DataNotFoundError):
        ask("What is EMEA FRT?", context=ctx, domain="service_ops")
