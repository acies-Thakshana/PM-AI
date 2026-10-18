from __future__ import annotations

import pandas as pd

from ai4bi.guardrails.sql_policy import SqlPolicy
from ai4bi.sql.executor import SqliteFrameExecutor

FRAMES = {"t": pd.DataFrame({"g": ["a", "a", "b"], "v": [1.0, 2.0, 5.0]})}


def _executor(settings, **overrides) -> SqliteFrameExecutor:
    policy = SqlPolicy.from_settings(settings)
    if overrides:
        policy = SqlPolicy(**{**policy.__dict__, **overrides})
    return SqliteFrameExecutor(policy)


def test_runs_a_select(settings):
    result = _executor(settings).execute("SELECT g, SUM(v) AS s FROM t GROUP BY g ORDER BY g", FRAMES)
    assert result.ok
    assert result.frame["s"].tolist() == [3.0, 5.0]
    assert not result.truncated
    assert result.elapsed_seconds >= 0


def test_row_limit_truncates(settings):
    result = _executor(settings, row_limit=2).execute("SELECT * FROM t", FRAMES)
    assert len(result.frame) == 2
    assert result.truncated


def test_errors_are_returned_not_raised(settings):
    result = _executor(settings).execute("SELECT missing FROM t", FRAMES)
    assert not result.ok
    assert "missing" in result.error


def test_connection_is_read_only(settings):
    result = _executor(settings).execute("DELETE FROM t", FRAMES)
    assert not result.ok


def test_execution_budget_interrupts_long_queries(settings):
    sql = (
        "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 100000000) "
        "SELECT COUNT(*) FROM n"
    )
    result = _executor(settings, max_execution_steps=100_000).execute(sql, FRAMES)
    assert not result.ok


def test_new_frames_replace_the_cached_database(settings):
    executor = _executor(settings)
    executor.execute("SELECT * FROM t", FRAMES)
    other = {"t": pd.DataFrame({"g": ["z"], "v": [9.0]})}
    assert executor.execute("SELECT g FROM t", other).frame["g"].tolist() == ["z"]
    executor.close()
