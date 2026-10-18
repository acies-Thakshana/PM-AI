from __future__ import annotations

import shutil

import pandas as pd
import pytest
import yaml

from ai4bi.config.errors import ConfigError, DomainNotFoundError
from ai4bi.semantic.loader import align_with_frames, package_from_frames
from ai4bi.semantic.models import GlossaryTerm, ValidatedSql
from ai4bi.semantic.schema import schema_for_llm
from ai4bi.semantic.store import SemanticStore


def test_domains_are_discovered(ctx):
    assert ctx.semantic.list_domains() == ["generic_cube", "service_ops"]


def test_service_ops_package_loads_all_files(ctx):
    pkg = ctx.semantic.load("service_ops")
    assert pkg.domain == "service_ops"
    assert {e.physical_dataset for e in pkg.entities} == {"accounts", "cases", "case_extension"}
    assert pkg.business_unit and pkg.business_unit.code == "SVC_OPS"
    assert pkg.rules and pkg.query_examples and pkg.validated_sql
    assert "contact_email" in pkg.restricted_columns()


def test_metric_resolution_uses_glossary_and_scope(ctx):
    store, pkg = ctx.semantic, ctx.semantic.load("service_ops")
    assert store.resolve_metric("What is EMEA FRT?", pkg).scope == "emea"
    assert store.resolve_metric("first response time in Europe", pkg).scope == "emea"
    assert store.resolve_metric("overall FRT", pkg).scope == "global"


def test_relevant_context_is_question_specific(ctx):
    context = ctx.semantic.relevant_context(ctx.semantic.load("service_ops"), "EMEA FRT")
    assert context["business_unit"]["code"] == "SVC_OPS"
    assert context["validated_sql_examples"][0]["id"] == "vsql.ops.frt_emea"
    assert context["business_rules"]


def test_schema_hides_restricted_columns(ctx):
    schema = schema_for_llm(ctx.semantic.load("service_ops"))
    columns = [c["name"] for e in schema["entities"] for c in e["columns"]]
    assert "contact_email" not in columns
    assert schema["registered_joins"]


def test_missing_domain_is_reported(ctx):
    with pytest.raises(DomainNotFoundError):
        ctx.semantic.load("nope")


def test_missing_required_file_is_a_config_error(project, settings):
    folder = settings.semantic_root / "service_ops"
    (folder / "entities.yaml").unlink()
    with pytest.raises(ConfigError, match="entities.yaml"):
        SemanticStore(settings.semantic_root).load("service_ops")


def test_bad_join_reference_is_a_config_error(settings):
    path = settings.semantic_root / "service_ops" / "joins.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload["joins"][0]["right_entity"] = "ghost"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ConfigError, match="ghost"):
        SemanticStore(settings.semantic_root).load("service_ops")


def test_unknown_domain_is_inferred_from_frames(ctx):
    frames = {"sales": pd.DataFrame({"region": ["a"], "amount": [1.0]})}
    pkg = ctx.semantic.load_or_infer("adhoc", frames)
    assert pkg.inferred
    assert pkg.entities[0].physical_dataset == "sales"


def test_align_adds_live_columns_and_unregistered_datasets(ctx):
    pkg = ctx.semantic.load("generic_cube")
    frames = {
        "KPI_data": pd.DataFrame({"BU": ["x"], "New Column": [1]}),
        "extra_table": pd.DataFrame({"k": [1]}),
    }
    aligned = align_with_frames(pkg, frames)
    assert any(c.name == "New Column" for c in aligned.entity_for_dataset("KPI_data").columns)
    assert aligned.entity_for_dataset("extra_table") is not None
    assert pkg.entity_for_dataset("extra_table") is None


def test_package_from_frames_marks_pii():
    pkg = package_from_frames("d", {"t": pd.DataFrame({"email": ["a@b"], "v": [1]})}, pii_columns=["email"])
    assert "email" in pkg.restricted_columns()


def test_store_appends_validated_sql_and_glossary(settings):
    store = SemanticStore(settings.semantic_root)
    store.add_validated_sql("service_ops", ValidatedSql(id="vsql.new", question="q?", sql="SELECT 1"))
    store.add_glossary_term(
        "service_ops",
        GlossaryTerm(term="reply time", kind="synonym", maps_to_kind="metric_family", maps_to_id="frt"),
    )
    pkg = store.load("service_ops", refresh=True)
    assert any(v.id == "vsql.new" for v in pkg.validated_sql)
    assert any(g.term == "reply time" for g in pkg.glossary)


def test_optional_files_may_be_absent(settings):
    folder = settings.semantic_root / "service_ops"
    for name in ("rules.yaml", "query_examples.yaml", "validated_sql.yaml", "business_unit.yaml"):
        (folder / name).unlink()
    shutil.rmtree(folder / "documents")
    pkg = SemanticStore(settings.semantic_root).load("service_ops")
    assert pkg.rules == [] and pkg.business_unit is None
