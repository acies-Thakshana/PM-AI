from __future__ import annotations

import pytest

from aibi.factory.catalog import resolve_metric
from aibi.factory.catalog_executor import execute_catalog_metric
from aibi.factory.compiler import compile_domain
from aibi.factory.glossary import bind_metric_family
from aibi.factory.harvest import harvest_summary
from aibi.factory.join_guard import assert_registered_joins
from aibi.factory.loader import load_domain
from aibi.factory.security_tags import assert_no_restricted_in_sql, strip_restricted
from aibi.factory.validate import OnboardingError, validate_domain, validate_package


def test_service_ops_contract_validates():
    pkg = validate_domain("service_ops")
    assert {e.logical_entity for e in pkg.entities} >= {
        "account",
        "service_case",
        "case_extension",
    }
    assert any(e.is_custom_object for e in pkg.entities)


def test_missing_joins_fail_closed():
    pkg = load_domain("service_ops")
    broken = pkg.model_copy(update={"joins": []})
    errors = validate_package(broken)
    assert any("will not infer joins" in e for e in errors)


def test_compiler_writes_scoped_frt_and_never_joins():
    pkg = validate_domain("service_ops")
    metrics = compile_domain(pkg, activate=False)
    scopes = {m.scope for m in metrics}
    assert scopes == {"global", "emea", "apac"}
    assert all("JOIN" not in m.sql_expression.upper() for m in metrics)
    assert all(m.status == "proposed" for m in metrics)


def test_glossary_and_metric_resolver():
    pkg = validate_domain("service_ops")
    assert bind_metric_family("What is FRT in EMEA?", pkg) == "frt"
    emea = resolve_metric("What is FRT in EMEA?", pkg)
    global_m = resolve_metric("What is first response time?", pkg)
    assert emea is not None and emea.scope == "emea"
    assert global_m is not None and global_m.scope == "global"
    assert emea.id != global_m.id


def test_catalog_executor_matches_sample_hours():
    global_r = execute_catalog_metric("What is FRT?", domain="service_ops")
    emea = execute_catalog_metric("What is EMEA FRT?", domain="service_ops")
    apac = execute_catalog_metric("What is APAC first response time?", domain="service_ops")
    assert global_r and "4.00" in global_r["answer"]
    assert emea and "2.50" in emea["answer"]
    assert apac and "7.00" in apac["answer"]
    assert "contact_email" not in (global_r.get("preview_columns") or [])


def test_join_guard_rejects_unregistered_join():
    pkg = validate_domain("service_ops")
    assert_registered_joins(
        "SELECT * FROM cases JOIN accounts ON service_case.account_id = account.account_id",
        pkg,
    )
    with pytest.raises(PermissionError):
        assert_registered_joins(
            "SELECT * FROM cases JOIN users ON cases.owner_id = users.id",
            pkg,
        )


def test_pii_not_in_sql_or_preview():
    pkg = validate_domain("service_ops")
    with pytest.raises(PermissionError):
        assert_no_restricted_in_sql("SELECT contact_email FROM cases", pkg)
    assert "contact_email" not in strip_restricted(
        ["case_id", "contact_email", "region"], pkg
    )


def test_harvest_does_not_clone_dashboard():
    pkg = load_domain("service_ops")
    summary = harvest_summary(pkg.harvest)
    assert summary["cloned_dashboards"] == 0
    assert summary["metrics_extracted"] >= 1
    assert summary["questions_extracted"] >= 1


def test_kpi_change_is_metadata_only():
    pkg = validate_domain("service_ops")
    original = next(m for m in pkg.metrics if m.scope == "emea")
    original.filter_sql = "region = 'EMEA' AND status = 'closed'"
    # Resolver still returns the same metric id — no agent or prompt involved.
    resolved = resolve_metric("EMEA FRT", pkg)
    assert resolved is not None
    assert resolved.id == "metric.service_ops.frt_emea"
    assert "status = 'closed'" in (resolved.filter_sql or "")
