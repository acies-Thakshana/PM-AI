"""The schema view of a domain package that is safe to send to a model."""

from __future__ import annotations

from typing import Any

from ai4bi.semantic.models import DomainPackage


def schema_for_llm(pkg: DomainPackage, tables: list[str] | None = None) -> dict[str, Any]:
    blocked = {c.lower() for c in pkg.restricted_columns()}
    wanted = {t.lower() for t in tables} if tables else None
    entities = []
    for entity in pkg.entities:
        if wanted is not None and entity.physical_dataset.lower() not in wanted:
            continue
        entities.append(
            {
                "logical_entity": entity.logical_entity,
                "physical_dataset": entity.physical_dataset,
                "grain": entity.grain,
                "is_custom_object": entity.is_custom_object,
                "columns": [
                    {
                        "name": c.name,
                        "data_type": c.data_type,
                        "role": c.role,
                        "description": c.description,
                    }
                    for c in entity.columns
                    if c.name.lower() not in blocked
                ],
            }
        )
    joins = [
        {
            "id": j.id,
            "left_dataset": _dataset(pkg, j.left_entity),
            "right_dataset": _dataset(pkg, j.right_entity),
            "condition": j.condition,
            "keys": [f"{k.left_column} = {k.right_column}" for k in j.keys],
            "join_type": j.join_type,
            "cardinality": j.cardinality,
            "grain_note": j.grain_note,
        }
        for j in pkg.joins
        if j.allowed_for_nlq
    ]
    return {
        "domain": pkg.contract.domain,
        "entities": entities,
        "registered_joins": joins,
        "join_rule": "Never invent a join. Only use registered_joins keys.",
        "dictionary_kpis": [
            {
                "family": k.family,
                "name": k.name,
                "definition": k.business_definition,
                "formula_hint": k.formula_hint,
                "scopes": k.scopes,
                "synonyms": k.synonyms,
            }
            for k in pkg.dictionary.kpis
        ],
        "certified_metrics": [
            {
                "id": m.id,
                "name": m.name,
                "scope": m.scope,
                "aggregation": m.aggregation,
                "compute": m.compute,
                "filter": m.filter_sql,
                "dataset": _dataset_for_product(pkg, m.data_product_id),
                "unit": m.unit,
            }
            for m in pkg.metrics
            if m.status == "certified"
        ],
    }


def _dataset(pkg: DomainPackage, logical_entity: str) -> str:
    entity = next((e for e in pkg.entities if e.logical_entity == logical_entity), None)
    return entity.physical_dataset if entity else logical_entity


def _dataset_for_product(pkg: DomainPackage, product_id: str) -> str:
    entity = pkg.entity_for_product(product_id)
    return entity.physical_dataset if entity else ""
