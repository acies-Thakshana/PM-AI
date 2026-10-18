"""Question answering on the bundled sample domains, with no model: the deterministic path.

The expected figures are the ones the legacy implementation produced for the same questions.
"""

from __future__ import annotations

import pytest

from app.errors import DataNotFoundError, DomainNotFoundError
from app.services.ask.pipeline import ask
from app.services.context import AppContext


def first_number(result: dict) -> float:
    row = result["table"]["rows"][0]
    return float(next(v for v in row.values() if isinstance(v, int | float)))


def test_scoped_metric_answer_is_complete_and_honest(ctx: AppContext) -> None:
    result = ask("What is EMEA FRT?", context=ctx, domain="service_ops")
    assert result["status"] == "success"
    assert first_number(result) == pytest.approx(2.5)
    assert result["answer"] == "First Response Time (emea) is 2.50 hours."
    assert result["chart"]["template"] == "kpi_card"
    assert result["follow_up_questions"]
    # No model ran, so the response must not claim one did or invent a confidence.
    assert result["answer_path"] == "deterministic"
    assert result["confidence"] is None


@pytest.mark.parametrize(
    ("question", "expected"),
    [("What is APAC FRT?", 7.0), ("What is global FRT?", 4.0), ("What is AMER FRT?", 2.5)],
)
def test_scoped_metrics(ctx: AppContext, question: str, expected: float) -> None:
    assert first_number(ask(question, context=ctx, domain="service_ops")) == pytest.approx(expected)


def test_generic_cube_productivity(ctx: AppContext) -> None:
    total = ask("What is the total productivity achieved so far?", context=ctx, domain="generic_cube")
    csa = ask("What is productivity for csa?", context=ctx, domain="generic_cube")
    assert first_number(total) == pytest.approx(620.3)
    assert first_number(csa) == pytest.approx(215.3)


def test_join_question_reports_the_registered_join(ctx: AppContext) -> None:
    result = ask("What is FRT by account name?", context=ctx, domain="service_ops")
    assert result["status"] == "success"
    assert result["joins_used"] == ["join.ops.case_to_account"]


def test_restricted_columns_are_refused_and_never_returned(ctx: AppContext) -> None:
    refused = ask("Show the contact email for EMEA cases", context=ctx, domain="service_ops")
    assert refused["status"] == "refuse_unauthorized"
    assert refused["sql_query"] == ""
    assert "@example" not in str(ask("cases by region", context=ctx, domain="service_ops"))


def test_unsafe_request_is_refused(ctx: AppContext) -> None:
    assert ask("drop table cases", context=ctx, domain="service_ops")["status"] == "refuse_unsupported"


def test_vague_question_asks_for_clarification(ctx: AppContext) -> None:
    result = ask("How are we performing?", context=ctx, domain="service_ops")
    assert result["status"] == "clarification_needed"
    assert "First Response Time" in result["answer"]


def test_follow_up_uses_the_session_and_only_that_session(ctx: AppContext) -> None:
    ask("What is EMEA FRT?", context=ctx, domain="service_ops", session_id="u:one")
    follow_up = ask("And APAC?", context=ctx, domain="service_ops", session_id="u:one")
    assert follow_up["status"] == "success"
    assert first_number(follow_up) == pytest.approx(7.0)
    assert ask("And APAC?", context=ctx, domain="service_ops", session_id="u:two")["status"] == "clarification_needed"


def test_answered_questions_grow_the_persisted_graph(ctx: AppContext) -> None:
    ask("What is EMEA FRT?", context=ctx, domain="service_ops")
    graph = ctx.graphs.load("service_ops")
    assert graph.stats()["episodes"] == 1
    assert graph.nodes_of_kind("document_fact")


def test_unknown_domain_and_missing_data_raise(ctx: AppContext, clean_environment) -> None:
    with pytest.raises(DomainNotFoundError):
        ask("What is the total?", context=ctx, domain="nope")
    (clean_environment / "samples" / "service_ops" / "cases.csv").unlink()
    with pytest.raises(DataNotFoundError):
        ask("What is EMEA FRT?", context=ctx, domain="service_ops")
