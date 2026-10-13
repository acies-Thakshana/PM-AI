from __future__ import annotations

import pytest

from aibi.experience.drill import apply_drill, load_drills, project_only_config
from aibi.experience.eval import run_excel_escape
from aibi.experience.explain import explain_answer
from aibi.experience.visuals import (
    VisualConfigError,
    load_bindings,
    render_visual,
    validate_visual_bindings,
)
from aibi.factory.catalog import resolve_metric
from aibi.factory.validate import validate_domain


def test_six_visual_templates_are_bound():
    errors = validate_visual_bindings("service_ops")
    assert errors == []
    templates = {b["template"] for b in load_bindings("service_ops")}
    assert templates == {
        "kpi_card",
        "table",
        "trend",
        "comparison",
        "root_cause",
        "distribution",
    }


def test_unknown_visual_template_is_rejected():
    spec = render_visual(load_bindings("service_ops")[0])
    assert spec["configurable_only"] is True
    with pytest.raises(VisualConfigError):
        render_visual({"id": "x", "template": "sankey", "metric_id": "m"})


def test_drill_only_changes_four_lists():
    cfg = project_only_config(load_drills("service_ops"))
    assert set(cfg) == {"entities", "dimensions", "filters", "actions"}
    nxt = apply_drill(
        "service_ops",
        path_id="drill.ops.frt",
        dimension="region",
        value="EMEA",
    )
    assert nxt["applied_filters"] == {"region": "EMEA"}
    assert nxt["action"] == "open_root_cause"
    with pytest.raises(ValueError):
        apply_drill(
            "service_ops",
            path_id="drill.ops.frt",
            dimension="owner_email",
            value="x",
        )


def test_explainability_hides_sql_for_analyst():
    pkg = validate_domain("service_ops")
    metric = resolve_metric("What is FRT?", pkg)
    assert metric is not None
    analyst = explain_answer(
        domain="service_ops",
        pkg=pkg,
        metric=metric,
        sql="SELECT 1",
        applied_filters={"region": "EMEA"},
        level="analyst",
    )
    power = explain_answer(
        domain="service_ops",
        pkg=pkg,
        metric=metric,
        sql="SELECT 1",
        level="power",
    )
    assert analyst["sql"] is None
    assert analyst["metric_definition"]["name"]
    assert analyst["data_freshness"]["data_product_id"]
    assert analyst["source_attribution"]["source_system"]
    assert power["sql"] == "SELECT 1"


def test_excel_escape_regression():
    report = run_excel_escape("service_ops")
    assert report["failed"] == 0
    assert report["total"] == 4
    assert {r["id"] for r in report["results"]} >= {
        "ee.ops.frt_global",
        "ee.ops.frt_emea",
        "ee.ops.frt_apac",
    }
