"""Existing dashboards are harvested, not cloned."""

from __future__ import annotations

from aibi.factory.models import BiHarvest, DataDictionary, DictionaryKpi


def harvest_to_dictionary(harvest: BiHarvest, domain: str) -> DataDictionary:
    kpis: list[DictionaryKpi] = []
    questions: list[str] = []
    for item in harvest.metrics:
        family = re_family(item.name)
        kpis.append(
            DictionaryKpi(
                family=family,
                name=item.name,
                business_definition=f"Harvested from {item.source_dashboard}: {item.calculation}",
                formula_hint=item.calculation,
                grain="as defined on source dashboard",
                owner="metric_owner",
                synonyms=[item.name, family],
                scopes=["global"],
            )
        )
        questions.extend(item.business_questions)
    return DataDictionary(
        domain=domain,
        entities=[],
        kpis=kpis,
        hierarchies=[m.drill_path for m in harvest.metrics if m.drill_path],
        synonyms=[{"term": q, "kind": "business_phrase"} for q in questions],
    )


def re_family(name: str) -> str:
    return (
        name.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("(", "")
        .replace(")", "")
    )


def harvest_summary(harvest: BiHarvest) -> dict:
    return {
        "domain": harvest.domain,
        "purpose": harvest.purpose,
        "metrics_extracted": len(harvest.metrics),
        "questions_extracted": sum(len(m.business_questions) for m in harvest.metrics),
        "drill_paths_extracted": sum(1 for m in harvest.metrics if m.drill_path),
        "cloned_dashboards": 0,
    }
