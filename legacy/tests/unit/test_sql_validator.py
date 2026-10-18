from __future__ import annotations

import pytest

from ai4bi.config.errors import SqlValidationError
from ai4bi.guardrails.sql_policy import SqlPolicy
from ai4bi.sql.validator import SqlValidator

TABLES = ["cases", "accounts", "case_extension"]


@pytest.fixture
def pkg(ctx):
    return ctx.semantic.load("service_ops")


@pytest.fixture
def validator(settings, pkg):
    return SqlValidator(SqlPolicy.from_settings(settings).with_restricted(pkg.restricted_columns()))


def test_plain_select_is_valid(validator, pkg):
    result = validator.validate("SELECT region, COUNT(*) FROM cases GROUP BY region;", pkg, TABLES)
    assert result.ok, result.errors
    assert result.tables == ["cases"]
    assert not result.sql.endswith(";")


def test_registered_join_with_aliases_is_valid(validator, pkg):
    sql = (
        "SELECT a.account_name, COUNT(*) FROM cases c "
        "JOIN accounts a ON a.account_id = c.account_id GROUP BY a.account_name"
    )
    result = validator.validate(sql, pkg, TABLES)
    assert result.ok, result.errors
    assert result.joins_used == ["join.ops.case_to_account"]


def test_unregistered_join_key_is_rejected(validator, pkg):
    sql = "SELECT * FROM cases c JOIN accounts a ON c.region = a.region"
    result = validator.validate(sql, pkg, TABLES)
    assert not result.ok
    assert any("join" in e.lower() for e in result.errors)


def test_comma_join_is_rejected(validator, pkg):
    result = validator.validate("SELECT * FROM cases, accounts WHERE cases.account_id = accounts.account_id", pkg, TABLES)
    assert not result.ok


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM cases",
        "SELECT 1; DROP TABLE cases",
        "SELECT * FROM cases -- comment",
        "WITH x AS (SELECT 1) INSERT INTO cases SELECT * FROM x",
        "REPLACE INTO cases VALUES (1)",
        "",
    ],
)
def test_unsafe_sql_is_rejected(validator, pkg, sql):
    assert not validator.validate(sql, pkg, TABLES).ok


def test_keywords_inside_strings_are_ignored(validator, pkg):
    result = validator.validate("SELECT COUNT(*) FROM cases WHERE status = 'drop update'", pkg, TABLES)
    assert result.ok, result.errors


def test_replace_function_is_allowed(validator, pkg):
    result = validator.validate("SELECT REPLACE(region, 'E', 'e') FROM cases", pkg, TABLES)
    assert result.ok, result.errors


def test_restricted_column_is_rejected(validator, pkg):
    result = validator.validate("SELECT contact_email FROM cases", pkg, TABLES)
    assert not result.ok
    assert any("contact_email" in e for e in result.errors)


def test_unknown_table_is_rejected(validator, pkg):
    assert not validator.validate("SELECT * FROM salaries", pkg, TABLES).ok


def test_cte_names_are_not_unknown_tables(validator, pkg):
    sql = "WITH r AS (SELECT region, COUNT(*) AS n FROM cases GROUP BY region) SELECT * FROM r"
    assert validator.validate(sql, pkg, TABLES).ok


def test_assert_valid_raises(validator, pkg):
    with pytest.raises(SqlValidationError):
        validator.assert_valid("DELETE FROM cases", pkg, TABLES)
