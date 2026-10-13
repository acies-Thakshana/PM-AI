"""Seed the knowledge graph from onboarding artifacts or a generic dataframe."""

from __future__ import annotations

from typing import Any

import pandas as pd

from aibi.factory.models import (
    ColumnSpec,
    Contract,
    DataDictionary,
    DictionaryKpi,
    DomainPackage,
    EntityRegistration,
    Steward,
)
from aibi.factory.security_tags import restricted_columns
from aibi.llmkg.graph import KnowledgeGraph


def seed_from_package(graph: KnowledgeGraph, pkg: DomainPackage) -> KnowledgeGraph:
    graph.upsert_node(
        f"domain.{pkg.contract.domain}",
        "domain",
        pkg.contract.domain,
        source_system=pkg.contract.source_system,
        historical_from=pkg.contract.historical_from,
        historical_to=pkg.contract.historical_to,
    )
    for entity in pkg.entities:
        eid = f"entity.{entity.logical_entity}"
        graph.upsert_node(
            eid,
            "entity",
            entity.logical_entity,
            source_system=entity.source_system,
            source_object=entity.source_object,
            physical_dataset=entity.physical_dataset,
            grain=entity.grain,
            is_custom_object=entity.is_custom_object,
            entity_kind=entity.entity_kind,
        )
        for col in entity.columns:
            if col.pii_tag == "restricted" or col.sensitive:
                continue
            cid = f"column.{entity.logical_entity}.{col.name}"
            graph.upsert_node(
                cid,
                "column",
                col.name,
                data_type=col.data_type,
                role=col.role,
                description=col.description,
                entity=entity.logical_entity,
            )
            graph.add_edge(eid, "has_column", cid)
    for join in pkg.joins:
        jid = f"join.{join.id}"
        graph.upsert_node(
            jid,
            "join",
            join.id,
            condition=join.condition,
            join_type=join.join_type,
            cardinality=join.cardinality,
            grain_note=join.grain_note,
            inferred=False,
        )
        graph.add_edge(f"entity.{join.left_entity}", "joins", f"entity.{join.right_entity}")
        graph.add_edge(f"entity.{join.left_entity}", "uses_join", jid)
    for kpi in pkg.dictionary.kpis:
        mid = f"metric.{kpi.family}"
        graph.upsert_node(
            mid,
            "metric",
            kpi.name,
            family=kpi.family,
            definition=kpi.business_definition,
            formula_hint=kpi.formula_hint,
            grain=kpi.grain,
            scopes=kpi.scopes,
            source="dictionary",
        )
        for syn in kpi.synonyms:
            tid = f"term.{_slug(syn)}"
            graph.upsert_node(
                tid, "glossary", syn, maps_to=kpi.family, term_kind="synonym", source="dictionary"
            )
            graph.add_edge(tid, "synonym_of", mid)
    for term in pkg.glossary:
        tid = f"term.{_slug(term.term)}"
        graph.upsert_node(
            tid,
            "glossary",
            term.term,
            term_kind=term.kind,
            maps_to=term.maps_to_id,
            source="glossary",
        )
    for blocked in restricted_columns(pkg):
        graph.upsert_node(f"pii.{blocked}", "pii", blocked, action="deny")
    return graph


def package_from_frame(
    domain: str,
    frame: pd.DataFrame,
    *,
    table_name: str = "KPI_data",
    pii_columns: list[str] | None = None,
) -> DomainPackage:
    """Generic onboarding from any tabular extract. No Salesforce objects."""
    blocked = {c.lower() for c in (pii_columns or [])}
    columns: list[ColumnSpec] = []
    for name in frame.columns:
        series = frame[name]
        role = "measure" if _is_numeric(series) else "attribute"
        tag = "restricted" if str(name).lower() in blocked else "none"
        columns.append(
            ColumnSpec(
                name=str(name),
                data_type=str(series.dtype),
                role=role,
                pii_tag=tag,  # type: ignore[arg-type]
                sensitive=tag == "restricted",
            )
        )
    entity = EntityRegistration(
        logical_entity=domain,
        source_system="other",
        source_object=table_name,
        physical_dataset=table_name,
        data_product_id=f"dp.{domain}.cube",
        grain="as provided by the data team",
        primary_keys=[str(frame.columns[0])],
        entity_kind="transactional",
        columns=columns,
        is_custom_object=False,
        notes="Seeded from extract. Joins are not inferred.",
    )
    dictionary = DataDictionary(
        domain=domain,
        kpis=[
            DictionaryKpi(
                family="primary_measure",
                name="Primary measure",
                business_definition="LLM chooses the measure from the dictionary and graph.",
                formula_hint="LLM proposes SUM/AVG/COUNT against measure columns",
                grain="cube",
                owner="metric.owner",
                synonyms=["kpi", "metric", "productivity"],
            )
        ],
    )
    contract = Contract(
        domain=domain,
        source_system="other",
        historical_from="",
        historical_to="",
        extracts=[table_name],
        master_entities=[domain],
        transactional_entities=[domain],
        owner=Steward(role="data.engineering", team="onboarding", contact=""),
        notes="Generic cube. Register joins in YAML before multi-table SQL.",
    )
    return DomainPackage(
        contract=contract,
        dictionary=dictionary,
        entities=[entity],
        joins=[],
        glossary=[],
        pii_tags=[{"column": c, "action": "restricted"} for c in (pii_columns or [])],
    )


def package_from_frames(domain: str, frames: dict[str, pd.DataFrame]) -> DomainPackage:
    """One entity per dataset. Joins stay empty until joins.yaml registers them."""
    if not frames:
        raise ValueError("frames are required")
    if len(frames) == 1:
        name, frame = next(iter(frames.items()))
        return package_from_frame(domain, frame, table_name=name)
    entities = []
    for name, frame in frames.items():
        one = package_from_frame(name, frame, table_name=name)
        entity = one.entities[0]
        entity.logical_entity = str(name)
        entity.physical_dataset = str(name)
        entity.source_object = str(name)
        entities.append(entity)
    first_name, first_frame = next(iter(frames.items()))
    package = package_from_frame(domain, first_frame, table_name=first_name)
    package.entities = entities
    package.joins = []
    package.contract.extracts = [str(name) for name in frames]
    package.contract.master_entities = [str(name) for name in frames]
    package.contract.transactional_entities = [str(name) for name in frames]
    package.contract.notes = (
        "Seeded from the recipe inputs. Register joins in joins.yaml before multi-table SQL."
    )
    return package


def schema_for_llm(pkg: DomainPackage) -> dict[str, Any]:
    blocked = {c.lower() for c in restricted_columns(pkg)}
    entities = []
    for entity in pkg.entities:
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
            "condition": j.condition,
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
        "join_rule": "Never invent a join. Only use registered_joins conditions.",
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
    }


def _is_numeric(series: pd.Series) -> bool:
    return str(series.dtype).startswith(("int", "float", "Float", "Int"))


def _slug(text: str) -> str:
    keep = []
    for ch in (text or "").lower():
        if ch.isalnum():
            keep.append(ch)
        elif keep and keep[-1] != "_":
            keep.append("_")
    return "".join(keep).strip("_")[:80]
