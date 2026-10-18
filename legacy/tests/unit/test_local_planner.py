from __future__ import annotations

import pandas as pd
import pytest

from ai4bi.data.preprocessing import drop_restricted, prepare_frames
from ai4bi.sql.local_planner import LocalPlanner, detect_intent


@pytest.fixture
def service(ctx, service_frames):
    pkg = ctx.semantic.load("service_ops")
    return LocalPlanner(ctx.semantic), pkg, drop_restricted(prepare_frames(service_frames), pkg.restricted_columns())


@pytest.fixture
def cube(ctx):
    pkg = ctx.semantic.load("generic_cube")
    frames = prepare_frames(ctx.data.load("generic_cube"))
    return LocalPlanner(ctx.semantic), pkg, frames


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        ("Which region has the highest FRT?", "ranking"),
        ("EMEA versus APAC", "comparison"),
        ("monthly FRT trend", "trend"),
        ("FRT by region", "breakdown"),
        ("What is EMEA FRT?", "aggregation"),
    ],
)
def test_intent(question, intent):
    assert detect_intent(question) == intent


def test_certified_metric_compiles_with_scope_filter(service):
    planner, pkg, frames = service
    plan, sql = planner.draft("What is EMEA FRT?", pkg, frames)
    assert plan["metrics"][0]["id"].endswith("emea")
    assert "julianday" in sql["sql_query"] and "region = 'EMEA'" in sql["sql_query"]


def test_two_scopes_switch_to_default_metric_grouped(service):
    planner, pkg, frames = service
    _, sql = planner.draft("EMEA FRT versus APAC FRT", pkg, frames)
    assert "IN ('EMEA', 'APAC')" in sql["sql_query"] and "GROUP BY region" in sql["sql_query"]


def test_dimension_on_joined_table_uses_registered_join(service):
    planner, pkg, frames = service
    _, sql = planner.draft("FRT by severity", pkg, frames)
    assert "JOIN case_extension AS t1 ON t0.case_id = t1.case_id" in sql["sql_query"]


def test_entity_name_alone_does_not_group_by_its_id(service):
    planner, pkg, frames = service
    _, sql = planner.draft("cases by region", pkg, frames)
    assert "case_id" not in sql["sql_query"]


def test_unmatched_question_asks_for_clarification(service):
    planner, pkg, frames = service
    plan, _ = planner.draft("How are we performing?", pkg, frames)
    assert plan["clarification_question"].startswith("Which metric")


def test_business_rule_picks_probability_weighted_measure(cube):
    planner, pkg, frames = cube
    _, weighted = planner.draft("total probability weighted productivity", pkg, frames)
    _, default = planner.draft("total non probability weighted productivity", pkg, frames)
    assert '"Agg Productivity"' in weighted["sql_query"]
    assert '"Actual Productivity"' in default["sql_query"]


def test_glossary_filter_and_plural_dimension(cube):
    planner, pkg, frames = cube
    _, csa = planner.draft("productivity for csa", pkg, frames)
    assert "'Climate Solutions Americas'" in csa["sql_query"]
    _, sites = planner.draft("Which sites have the highest productivity?", pkg, frames)
    assert '"Site Name"' in sites["sql_query"] and "LIMIT 5" in sites["sql_query"]


def test_text_period_column_drives_a_trend(cube):
    planner, pkg, frames = cube
    _, sql = planner.draft("productivity by quarter", pkg, frames)
    assert "GROUP BY Quarter" in sql["sql_query"]


def test_inferred_package_counts_rows(ctx):
    frames = {"orders": pd.DataFrame({"region": ["a", "b"], "amount": [1.0, 2.0]})}
    pkg = ctx.semantic.load_or_infer("adhoc", frames)
    _, sql = LocalPlanner(ctx.semantic).draft("How many orders by region?", pkg, frames)
    assert sql["sql_query"].startswith("SELECT region AS region, COUNT(*)")
