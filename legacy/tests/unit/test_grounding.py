"""Catalog grounding is general: members, empty columns, rankings. No question list."""

from __future__ import annotations

import sqlite3

import pandas as pd

from ai4bi.sql.grounding import (
    candidate_values,
    diagnose,
    prepare_sql,
    profile_frame,
    result_is_vacuous,
    schema_text,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "BU": [
                "Climate Solutions Americas",
                "Climate Solutions Americas",
                "CS Americas",
                "Climate Solutions APAC",
                "Carrier HQ",
            ],
            "Site Name": [
                "Poland Operations",
                "ALC, Kennesaw, GA",
                "KENNESAW",
                "Franklin",
                "",
            ],
            "Pillar Type": ["Direct", "Indirect", "Logistics", "Direct", "Direct"],
            "Actual Productivity": [10.0, 5.0, 0.0, None, 7.0],
            "Agg Productivity": [8.0, 4.0, 0.0, 1.0, 6.0],
            "Actual Gross Productivity": [None, None, None, None, None],
            "Initiative ID": ["A1", "A1", "B2", "C3", "D4"],
            "Initiative name": ["Alpha", "Alpha", "Beta", "Gamma", "Delta"],
        }
    )


def _profiles():
    notes = {
        "Actual Productivity": "Default productivity. Non-probability-weighted.",
        "Agg Productivity": "Probability-weighted productivity.",
    }
    return profile_frame(_frame(), notes=notes)


def test_empty_columns_are_omitted_and_described_measures_remain():
    text = schema_text(_profiles(), "total productivity", table="KPI_data")
    assert "Actual Gross Productivity" not in text.split("Omitted")[0]
    assert "no stored values" in text
    assert "Non-probability-weighted" in text
    assert "Probability-weighted" in text
    assert '"Pillar Type" members' in text
    assert "'Direct'" in text and "'Logistics'" in text


def test_near_miss_filter_binds_to_the_stored_member():
    profiles = _profiles()
    sql = prepare_sql(
        "SELECT SUM(\"Actual Productivity\") AS value FROM KPI_data "
        "WHERE \"BU\" = 'Climate Solutions America'",
        profiles,
    )
    assert "Climate Solutions Americas" in sql
    assert "Climate Solutions America'" not in sql


def test_case_and_punctuation_bind_without_a_hardcoded_alias():
    profiles = _profiles()
    poland = prepare_sql(
        'SELECT "Site Name", SUM("Actual Productivity") AS value FROM KPI_data '
        "WHERE \"Site Name\" = 'Poland operations' GROUP BY \"Site Name\"",
        profiles,
    )
    assert "'Poland Operations'" in poland
    site = prepare_sql(
        'SELECT "Site Name" FROM KPI_data WHERE "Site Name" = \'ALC Kennesaw\'',
        profiles,
    )
    assert "'ALC, Kennesaw, GA'" in site


def test_glossary_term_overrides_a_different_stored_member():
    profiles = _profiles()
    sql = prepare_sql(
        'SELECT SUM("Actual Productivity") AS value FROM KPI_data WHERE "BU" = \'CS Americas\'',
        profiles,
        "Will csa reach the plan?",
        aliases=[("csa", "Climate Solutions Americas")],
    )
    assert "'Climate Solutions Americas'" in sql
    assert "CS Americas" not in sql


def test_explicit_member_is_not_replaced_by_glossary():
    profiles = _profiles()
    sql = prepare_sql(
        'SELECT SUM("Actual Productivity") AS value FROM KPI_data WHERE "BU" = \'CS Americas\'',
        profiles,
        "How is CS Americas doing on the csa view?",
        aliases=[("csa", "Climate Solutions Americas")],
    )
    assert "'CS Americas'" in sql


def test_ranking_drops_null_aggregates_and_blank_labels():
    profiles = _profiles()
    sql = prepare_sql(
        'SELECT "Site Name", SUM("Actual Productivity") AS "Total" FROM KPI_data '
        'GROUP BY "Site Name" ORDER BY "Total" ASC LIMIT 3',
        profiles,
        "lowest sites",
    )
    assert "HAVING SUM(\"Actual Productivity\") IS NOT NULL" in sql
    assert 'TRIM("Site Name") <> \'\'' in sql
    frame = _execute(sql)
    assert frame["Site Name"].tolist()
    assert "" not in set(frame["Site Name"])
    assert frame["Total"].notna().all()


def test_zero_is_a_real_result_and_all_null_is_not():
    assert not result_is_vacuous(pd.DataFrame({"value": [0.0]}))
    assert result_is_vacuous(pd.DataFrame({"value": [None]}))
    assert result_is_vacuous(pd.DataFrame())


def test_diagnosis_names_the_closest_member_and_the_empty_column():
    profiles = _profiles()
    sql = (
        'SELECT SUM("Actual Gross Productivity") AS gross FROM KPI_data '
        'WHERE "Site Name" = \'Poland operation\''
    )
    text = diagnose(sql, profiles, pd.DataFrame({"gross": [None]}))
    assert "Actual Gross Productivity" in text
    assert "Actual Productivity" in text
    assert "Poland Operations" in text


def test_phrase_match_beats_a_shorter_exact_name():
    site = next(column for column in _profiles() if column.name == "Site Name")
    hits = candidate_values(site, "worst workstream for ALC Kennesaw in Q1")
    assert hits[0][0] == "ALC, Kennesaw, GA"
    assert hits[0][1] > dict(hits).get("KENNESAW", 0)


def test_identifier_pairs_are_detected_from_column_names():
    text = schema_text(_profiles(), "top projects", table="KPI_data")
    assert "Initiative ID" in text and "Initiative name" in text


def test_question_phrase_replaces_a_different_exact_member():
    profiles = _productivity_profiles(_sites())
    toward_operations = prepare_sql(
        'SELECT SUM("Actual Productivity") AS actual FROM KPI_data '
        "WHERE \"Site Name\" = 'Sales Poland'",
        profiles,
        "How is Poland operations performing against the target?",
    )
    assert "'Poland Operations'" in toward_operations
    assert "Sales Poland" not in toward_operations
    toward_sales = prepare_sql(
        'SELECT SUM("Actual Productivity") AS actual FROM KPI_data '
        "WHERE \"Site Name\" = 'Poland Operations'",
        profiles,
        "How is Sales Poland performing against the target?",
    )
    assert "'Sales Poland'" in toward_sales


def test_like_filter_binds_the_full_site_and_drops_null_rank_keys():
    frame = pd.DataFrame(
        {
            "Site Name": ["ALC, Kennesaw, GA", "ALC, Kennesaw, GA", "KENNESAW"],
            "Workstream": [None, "Refrigerants", "Other"],
            "Quarter": ["Q1", "Q1", "Q1"],
            "Actual Productivity": [None, -145.2, 10.0],
        }
    )
    sql = prepare_sql(
        'SELECT "Workstream", SUM("Actual Productivity") AS value FROM KPI_data '
        "WHERE \"Site Name\" LIKE '%Kennesaw%' AND \"Quarter\" = 'Q1' "
        'GROUP BY "Workstream" ORDER BY value ASC LIMIT 1',
        profile_frame(frame),
        "worst workstream for ALC Kennesaw in Q1",
    )
    assert "'ALC, Kennesaw, GA'" in sql
    assert "LIKE" not in sql.upper()
    assert "IS NOT NULL" in sql
    assert _execute(sql, frame)["Workstream"].tolist() == ["Refrigerants"]


def test_summed_measure_filter_does_not_change_the_ratio():
    frame = pd.DataFrame(
        {
            "Site Name": ["Franklin", "Franklin", "Steady"],
            "Actual Productivity": [60.0, -50.0, 90.0],
            "Forecast Productivity Plan": [100.0, None, 100.0],
        }
    )
    sql = prepare_sql(
        'SELECT "Site Name", '
        'SUM("Actual Productivity") * 1.0 / NULLIF(SUM("Forecast Productivity Plan"), 0) AS achievement_pct '
        "FROM KPI_data WHERE \"Forecast Productivity Plan\" IS NOT NULL "
        'GROUP BY "Site Name" HAVING achievement_pct < 0.5 '
        "ORDER BY achievement_pct ASC",
        _productivity_profiles(frame),
        "Which sites have not achieved 50% of their target?",
    )
    assert 'WHERE "Forecast Productivity Plan" IS NOT NULL' not in sql
    assert _execute(sql, frame)["Site Name"].tolist() == ["Franklin"]


def test_performance_rank_orders_by_the_ratio():
    frame = pd.DataFrame(
        {
            "BU": ["Climate Solutions Americas", "Europe"],
            "Actual Productivity": [100.0, 50.0],
            "Forecast Productivity Plan": [100.0, 20.0],
        }
    )
    sql = prepare_sql(
        'SELECT "BU", SUM("Actual Productivity") AS total_actual, '
        'SUM("Forecast Productivity Plan") AS total_plan, '
        'RANK() OVER (ORDER BY SUM("Actual Productivity") DESC) AS performance_rank '
        'FROM KPI_data GROUP BY "BU" ORDER BY performance_rank',
        _productivity_profiles(frame),
        "Rank BUs by performance against the target",
    )
    assert 'ORDER BY SUM("Actual Productivity") DESC' not in sql
    assert 'NULLIF(SUM("Forecast Productivity Plan"), 0)' in sql
    assert _execute(sql, frame).iloc[0]["BU"] == "Europe"


def test_difference_uses_the_two_described_measures():
    frame = pd.DataFrame(
        {
            "Actual Productivity": [10.0],
            "Agg Productivity": [8.0],
            "Forecast Productivity PX3": [1.0],
            "Forecast Productivity Plan": [4.0],
        }
    )
    profiles = profile_frame(
        frame,
        notes={
            "Actual Productivity": "Default productivity. Non-probability-weighted.",
            "Agg Productivity": "Probability-weighted productivity.",
            "Forecast Productivity PX3": "Probability scenario PX3.",
            "Forecast Productivity Plan": "Productivity target plan.",
        },
    )
    sql = prepare_sql(
        'SELECT SUM("Forecast Productivity PX3") - SUM("Forecast Productivity Plan") AS difference '
        "FROM KPI_data",
        profiles,
        "What is the difference between the productivity under probability and non probability weighted?",
    )
    assert '"Agg Productivity"' in sql
    assert '"Actual Productivity"' in sql
    assert "PX3" not in sql


def test_winner_group_limits_the_following_top_n():
    frame = pd.DataFrame(
        {
            "BU": [
                "Climate Solutions Americas",
                "Climate Solutions Americas",
                "Europe",
                "Europe",
                "Europe",
            ],
            "Initiative ID": ["A", "B", "C", "D", "E"],
            "Initiative name": ["Alpha", "Beta", "Delta", "Epsilon", "Zeta"],
            "Quarter": ["Q3", "Q3", "Q3", "Q3", "Q3"],
            "Actual Productivity": [100.0, 50.0, 80.0, 70.0, 60.0],
        }
    )
    sql = prepare_sql(
        'SELECT "Initiative name", "BU", SUM("Actual Productivity") AS total '
        "FROM KPI_data WHERE \"Quarter\" = 'Q3' "
        'GROUP BY "Initiative name", "BU" ORDER BY total DESC LIMIT 3',
        profile_frame(frame, notes={"Initiative name": "Project or initiative label"}),
        "Which BU has the highest productivity in Q3? Name the top 3 projects",
    )
    assert "LIMIT 1" in sql
    assert sql.rstrip().endswith("LIMIT 3")
    assert '"Initiative ID"' in sql
    result = _execute(sql, frame)
    assert set(result["BU"]) == {"Europe"}
    assert set(result["Initiative name"]) == {"Delta", "Epsilon", "Zeta"}


def test_percent_of_plan_drops_an_invented_scale_and_lookalike_columns():
    frame = pd.DataFrame(
        {
            "Actual Productivity": [10.0],
            "Forecast Productivity Plan": [100.0],
            "Forecast Productivity PX9": [3.0],
            "Forecast Spend Plan": [1.0],
        }
    )
    sql = prepare_sql(
        'SELECT SUM("Forecast Productivity PX9") / (SUM("Forecast Spend Plan") * 1e6) AS pct '
        "FROM KPI_data",
        profile_frame(
            frame,
            notes={
                "Actual Productivity": "Default productivity. Non-probability-weighted.",
                "Forecast Productivity Plan": "Productivity target plan.",
                "Forecast Productivity PX9": "Scenario PX9.",
                "Forecast Spend Plan": "Spend dollars plan.",
            },
        ),
        "Is non-probability productivity within 2% of the plan?",
    )
    assert "1e6" not in sql.lower()
    assert "PX9" not in sql
    assert "Spend" not in sql
    assert '"Actual Productivity"' in sql
    assert '"Forecast Productivity Plan"' in sql


def test_listed_members_stay_when_the_question_names_each_one():
    sql = prepare_sql(
        'SELECT "Pillar Type", SUM("Actual Productivity") AS value FROM KPI_data '
        "WHERE \"Pillar Type\" IN ('Direct', 'Indirect', 'Logistics') "
        'GROUP BY "Pillar Type"',
        _profiles(),
        "split actual productivity across Direct, Indirect, and Logistics",
    )
    assert "'Direct'" in sql and "'Indirect'" in sql and "'Logistics'" in sql


def test_misspelled_probability_contrast_uses_actual_and_agg():
    frame = pd.DataFrame(
        {
            "Forecast Productivity PX3": [1.0],
            "Forecast Productivity Plan": [4.0],
            "Agg Productivity": [8.0],
            "Actual Productivity": [10.0],
        }
    )
    sql = prepare_sql(
        'SELECT SUM("Forecast Productivity PX3") - SUM("Forecast Productivity Plan") AS difference '
        "FROM KPI_data",
        profile_frame(frame),
        "What is the difference between the productivity under probablity and non probablity weighted?",
    )
    assert '"Agg Productivity"' in sql
    assert '"Actual Productivity"' in sql
    assert "PX3" not in sql


def test_winning_group_is_found_before_its_top_projects():
    frame = pd.DataFrame(
        {
            "BU": ["Climate Solutions Americas", "Europe", "Europe", "Europe"],
            "Initiative ID": ["A", "B", "C", "D"],
            "Initiative name": ["Alpha", "Beta", "Gamma", "Delta"],
            "Quarter RPT": ["Q3", "Q3", "Q3", "Q3"],
            "Actual Productivity": [100.0, 80.0, 70.0, 60.0],
        }
    )
    sql = prepare_sql(
        'SELECT BU, "Initiative name", SUM(CAST("Actual Productivity" AS FLOAT)) AS total_productivity '
        "FROM KPI_data WHERE \"Quarter RPT\" = 'Q3' "
        'GROUP BY BU, "Initiative name" ORDER BY total_productivity DESC LIMIT 3',
        profile_frame(frame),
        "Which BU has the highest productivity in Q3? Name the top 3 projects",
    )
    assert "LIMIT 1" in sql
    result = _execute(sql, frame)
    assert set(result["BU"]) == {"Europe"}
    assert "Alpha" not in set(result["Initiative name"])


def test_performance_rank_keeps_plan_rows_and_orders_by_the_ratio():
    frame = pd.DataFrame(
        {
            "BU": ["Climate Solutions Americas", "Climate Solutions Americas", "Europe", "Europe"],
            "Actual Productivity": [100.0, None, 40.0, None],
            "Forecast Productivity Plan": [None, 100.0, None, 20.0],
        }
    )
    sql = prepare_sql(
        'SELECT BU, SUM(CAST("Actual Productivity" AS FLOAT)) AS total_actual_productivity, '
        'SUM(CAST("Forecast Productivity Plan" AS FLOAT)) AS total_plan_productivity, '
        'RANK() OVER (ORDER BY SUM(CAST("Actual Productivity" AS FLOAT)) DESC) AS performance_rank '
        'FROM KPI_data WHERE "Actual Productivity" IS NOT NULL GROUP BY BU ORDER BY performance_rank',
        _productivity_profiles(frame),
        "Can you please rank the BUs by performance?",
    )
    assert 'WHERE "Actual Productivity" IS NOT NULL' not in sql
    assert 'NULLIF(SUM("Forecast Productivity Plan"), 0)' in sql
    assert _execute(sql, frame).iloc[0]["BU"] == "Europe"


def test_stated_percent_uses_amount_over_plan():
    frame = pd.DataFrame(
        {
            "Actual Productivity": [10.0],
            "Forecast Productivity Plan": [100.0],
            "Forecast Spend Plan": [1.0],
        }
    )
    sql = prepare_sql(
        'SELECT SUM("Forecast Productivity Plan") / (SUM("Forecast Spend Plan") * 1000000) * 100 AS pct '
        "FROM KPI_data",
        _productivity_profiles(frame),
        "Will csa be able to achieve productivity of 2% by the end of year in overall for non probability weighted",
    )
    assert "1000000" not in sql
    assert "Spend" not in sql
    assert '"Actual Productivity"' in sql
    assert '"Forecast Productivity Plan"' in sql
    assert "* 100.0" in sql


def test_worst_performing_amount_is_not_rewritten_into_a_ratio():
    frame = pd.DataFrame(
        {
            "Workstream": ["Refrigerants", "Packaging"],
            "Actual Productivity": [-145.2, 10.0],
            "Forecast Productivity Plan": [1.0, 1.0],
        }
    )
    sql = prepare_sql(
        'SELECT "Workstream", SUM("Actual Productivity") AS value FROM KPI_data '
        'GROUP BY "Workstream" ORDER BY value ASC LIMIT 1',
        _productivity_profiles(frame),
        "Which is the worst performing workstream for ALC Kennesaw in Q1 for non probability weighted?",
    )
    assert "ORDER BY value ASC" in sql
    assert "Forecast Productivity Plan" not in sql.split("ORDER BY", 1)[-1]


def _sites() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Site Name": ["Poland Operations", "Sales Poland"],
            "Actual Productivity": [100.0, 10.0],
            "Forecast Productivity Plan": [50.0, 4.0],
        }
    )


def _productivity_profiles(frame: pd.DataFrame):
    return profile_frame(
        frame,
        notes={
            "Actual Productivity": "Default productivity. Non-probability-weighted.",
            "Forecast Productivity Plan": "Productivity target plan.",
        },
    )


def _execute(sql: str, frame: pd.DataFrame | None = None) -> pd.DataFrame:
    frame = _frame() if frame is None else frame
    with sqlite3.connect(":memory:") as conn:
        frame.to_sql("KPI_data", conn, index=False)
        return pd.read_sql_query(sql, conn)
