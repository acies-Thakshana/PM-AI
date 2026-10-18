"""Answers, follow-ups, charts, metadata, and the LLM client contract."""

from __future__ import annotations

import pytest

from ai4bi.answers.generator import AnswerGenerator, local_answer, unverified_figures
from ai4bi.config.errors import ConfigError, LlmError
from ai4bi.knowledge.graph import KnowledgeGraph
from ai4bi.llm.client import LocalFallbackClient, complete_json, get_llm_client, register_llm_factory
from ai4bi.metadata.extractor import extract_metadata, metadata_to_records

PLAN = {
    "intent": "breakdown",
    "metrics": [{"id": "metric.frt.global", "name": "First Response Time (global)", "unit": "hours"}],
    "dimensions": ["region"],
    "filters": {},
}
BY_REGION = {"columns": ["region", "frt"], "rows": [{"region": "APAC", "frt": 7.0}, {"region": "EMEA", "frt": 2.5}], "n": 2}
SINGLE = {"columns": ["frt"], "rows": [{"frt": 2.5}], "n": 1}


class ScriptedLlm:
    name = "scripted"

    def __init__(self, reply: str) -> None:
        self.reply = reply

    def complete(self, system_instruction: str, user_prompt: str) -> str:
        return self.reply


def test_single_value_answer_has_unit():
    plan = {**PLAN, "metrics": [{"name": "First Response Time (emea)", "unit": "hours"}], "dimensions": []}
    assert local_answer("What is EMEA FRT?", plan, SINGLE)["answer"] == "First Response Time (emea) is 2.50 hours."


def test_grouped_answer_lists_rows():
    answer = local_answer("FRT by region", PLAN, BY_REGION)["answer"]
    assert "APAC: 7 hours" in answer and "EMEA: 2.50 hours" in answer


def test_unverified_figures_ignore_label_digits():
    preview = {"columns": ["account_id", "v"], "rows": [{"account_id": "A-20", "v": 7.0}], "n": 1}
    assert unverified_figures("A-20 has 7.00 hours", preview, "q") == []
    assert unverified_figures("The value is 99", preview, "q") == ["99"]


def test_answer_generator_uses_llm_text_but_flags_invented_figures():
    llm = ScriptedLlm('{"answer": "APAC is 7 hours and EMEA is 3.9 hours.", "key_findings": []}')
    result = AnswerGenerator(llm).generate("FRT by region", plan=PLAN, sql="SELECT 1", preview=BY_REGION, diagnosis="")
    assert result["_llm_provider"] == "scripted"
    assert "3.9" in result["unverified_figures"]


def test_answer_generator_falls_back_locally():
    result = AnswerGenerator(LocalFallbackClient()).generate(
        "FRT by region", plan=PLAN, sql="SELECT 1", preview=BY_REGION, diagnosis=""
    )
    assert result["_llm_provider"] == "local_fallback"
    assert "APAC" in result["answer"]


def test_followups_rotate_templates_and_skip_used_dimensions(ctx):
    pkg = ctx.semantic.load("service_ops")
    suggestions = ctx.followups.suggest("FRT by region", pkg=pkg, plan=PLAN, graph=KnowledgeGraph("service_ops"))
    assert 1 <= len(suggestions) <= ctx.settings.followup_max
    assert not any(s.endswith("by region?") for s in suggestions)
    assert len({s.split()[0] for s in suggestions}) >= 2


def test_followups_never_suggest_restricted_columns(ctx):
    pkg = ctx.semantic.load("service_ops")
    suggestions = ctx.followups.suggest("FRT", pkg=pkg, plan=PLAN)
    assert not any("email" in s.lower() for s in suggestions)


def test_chart_choice(ctx):
    pkg = ctx.semantic.load("service_ops")
    assert ctx.visuals.build(PLAN, BY_REGION, pkg)["template"] == "comparison"
    kpi = ctx.visuals.build({**PLAN, "dimensions": []}, SINGLE, pkg)
    assert kpi["template"] == "kpi_card" and kpi["value"] == 2.5 and kpi["unit"] == "hours"
    trend = ctx.visuals.build({**PLAN, "intent": "trend"}, {"columns": ["period", "v"], "rows": [{"period": "2026-01", "v": 1}], "n": 1}, pkg)
    assert trend["template"] == "trend"
    assert ctx.visuals.build(PLAN, {"columns": [], "rows": [], "n": 0}, pkg) == {}
    assert ctx.visuals.validate_bindings(pkg) == []


def test_metadata_marks_restricted_and_hides_samples(ctx, service_frames):
    pkg = ctx.semantic.load("service_ops")
    metadata = extract_metadata(pkg, service_frames)
    cases = next(d for d in metadata["datasets"] if d["dataset"] == "cases")
    email = next(c for c in cases["columns"] if c["name"] == "contact_email")
    assert email["restricted"] and email["sample_values"] == []
    assert metadata["relationships"]
    rows = metadata_to_records(metadata)
    assert {"dataset", "column", "role", "restricted"} <= set(rows[0])


def test_metadata_store_round_trip(ctx, service_frames):
    metadata = extract_metadata(ctx.semantic.load("service_ops"), service_frames)
    path = ctx.metadata.save(metadata)
    assert path.name == "dataset_catalog.json"
    assert ctx.metadata.load("service_ops")["domain"] == "service_ops"


def test_complete_json_contract():
    assert complete_json(ScriptedLlm('```json\n{"a": 1}\n```'), "s", "u", task="t")["a"] == 1
    fallback = complete_json(ScriptedLlm("not json"), "s", "u", task="t", fallback={"b": 2})
    assert fallback == {"b": 2, "_llm_provider": "local_fallback", "_llm_task": "t"}
    with pytest.raises(LlmError):
        complete_json(ScriptedLlm(""), "s", "u", task="t")


def test_llm_factories(settings):
    assert isinstance(get_llm_client(settings), LocalFallbackClient)
    register_llm_factory("test-mode", lambda s: ScriptedLlm("{}"))
    assert get_llm_client(settings.with_overrides(llm_mode="test-mode")).name == "scripted"
    with pytest.raises(ConfigError):
        get_llm_client(settings.with_overrides(llm_mode="unknown"))
