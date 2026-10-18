"""Seed the knowledge graph from a domain package."""

from __future__ import annotations

from ai4bi.knowledge.graph import KnowledgeGraph
from ai4bi.semantic.models import DomainPackage
from ai4bi.utils.text import slug


def seed_from_package(graph: KnowledgeGraph, pkg: DomainPackage) -> KnowledgeGraph:
    graph.upsert_node(
        f"domain.{pkg.contract.domain}",
        "domain",
        pkg.contract.domain,
        source_system=pkg.contract.source_system,
        historical_from=pkg.contract.historical_from,
        historical_to=pkg.contract.historical_to,
    )
    blocked = {c.lower() for c in pkg.restricted_columns()}
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
        graph.add_edge(f"domain.{pkg.contract.domain}", "has_entity", eid)
        for col in entity.columns:
            if col.name.lower() in blocked or col.pii_tag == "restricted" or col.sensitive:
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
            inferred=join.inferred,
            allowed_for_nlq=join.allowed_for_nlq,
            approved_by=join.approved_by,
        )
        graph.add_edge(f"entity.{join.left_entity}", "joins", f"entity.{join.right_entity}")
        graph.add_edge(f"entity.{join.left_entity}", "uses_join", jid)
    for kpi in pkg.dictionary.kpis:
        family_id = f"metric.{kpi.family}"
        graph.upsert_node(
            family_id,
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
            tid = f"term.{slug(syn)}"
            graph.upsert_node(tid, "glossary", syn, maps_to=kpi.family, term_kind="synonym", source="dictionary")
            graph.add_edge(tid, "synonym_of", family_id)
    for metric in pkg.metrics:
        graph.upsert_node(
            metric.id,
            "metric",
            metric.name,
            family=metric.family,
            scope=metric.scope,
            version=metric.version,
            status=metric.status,
            sql_expression=metric.sql_expression,
            filter_sql=metric.filter_sql,
            grain=metric.grain,
            source="catalog",
        )
        graph.add_edge(metric.id, "variant_of", f"metric.{metric.family}")
        entity = pkg.entity_for_product(metric.data_product_id)
        if entity:
            graph.add_edge(metric.id, "computed_on", f"entity.{entity.logical_entity}")
    for term in pkg.glossary:
        tid = f"term.{slug(term.term)}"
        graph.upsert_node(
            tid,
            "glossary",
            term.term,
            term_kind=term.kind,
            maps_to=term.maps_to_id,
            canonical_value=term.canonical_value or None,
            source="glossary",
        )
    for rule in pkg.rules:
        graph.upsert_node(
            f"rule.{rule.id}",
            "business_rule",
            rule.description[:240],
            rule_type=rule.rule_type,
            applies_to=rule.applies_to,
            sql_hint=rule.sql_hint or None,
            source="rules",
        )
        for target in rule.applies_to:
            if target in graph.nodes:
                graph.add_edge(f"rule.{rule.id}", "applies_to", target)
    for entry in pkg.validated_sql:
        sid = f"sql.validated.{slug(entry.id)}"
        graph.upsert_node(
            sid, "sql_pattern", entry.question[:240], full_sql=entry.sql, status="validated", source="validated_sql"
        )
    if pkg.business_unit:
        bu = pkg.business_unit
        graph.upsert_node(
            f"bu.{slug(bu.code)}",
            "business_unit",
            bu.name,
            code=bu.code,
            description=bu.description,
            currency=bu.currency,
            default_filters=bu.default_filters,
        )
        graph.add_edge(f"bu.{slug(bu.code)}", "owns", f"domain.{pkg.contract.domain}")
    for column in sorted(pkg.restricted_columns()):
        graph.upsert_node(f"pii.{column}", "pii", column, action="deny")
    return graph
