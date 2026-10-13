"""Fail closed if the onboarding contract is incomplete.

Joins are never optional when more than one entity is registered.
The AI engine must not infer them later.
"""

from __future__ import annotations

from aibi.factory.loader import load_domain
from aibi.factory.models import DomainPackage


class OnboardingError(ValueError):
    """Contract, dictionary, join, or security gap."""


def _fail(errors: list[str]) -> None:
    if errors:
        raise OnboardingError("Onboarding incomplete:\n- " + "\n- ".join(errors))


def validate_package(pkg: DomainPackage) -> list[str]:
    errors: list[str] = []
    entity_ids = {e.logical_entity for e in pkg.entities}
    col_index = {
        e.logical_entity: {c.name for c in e.columns} for e in pkg.entities
    }

    if not pkg.contract.extracts:
        errors.append("contract.extracts is required")
    if not pkg.contract.historical_from or not pkg.contract.historical_to:
        errors.append("contract must declare a historical window")

    for name in pkg.contract.master_entities + pkg.contract.transactional_entities:
        if name not in entity_ids:
            errors.append(f"contract entity {name!r} is not registered")

    dict_entities = {e.logical_entity for e in pkg.dictionary.entities}
    for eid in entity_ids:
        if eid not in dict_entities:
            errors.append(f"data dictionary missing business definition for {eid}")

    if len(entity_ids) > 1 and not pkg.joins:
        errors.append(
            "multiple entities registered but join registry is empty — "
            "the AI engine will not infer joins"
        )

    for join in pkg.joins:
        if join.inferred:
            errors.append(f"join {join.id} is marked inferred; inferred joins are forbidden")
        if join.left_entity not in entity_ids:
            errors.append(f"join {join.id} left entity {join.left_entity} is not registered")
        if join.right_entity not in entity_ids:
            errors.append(f"join {join.id} right entity {join.right_entity} is not registered")
        for key in join.keys:
            left_cols = col_index.get(key.left_entity, set())
            right_cols = col_index.get(key.right_entity, set())
            if key.left_column not in left_cols:
                errors.append(
                    f"join {join.id} left column {key.left_column} "
                    f"not on {key.left_entity}"
                )
            if key.right_column not in right_cols:
                errors.append(
                    f"join {join.id} right column {key.right_column} "
                    f"not on {key.right_entity}"
                )

    kpi_families = {k.family for k in pkg.dictionary.kpis}
    for metric in pkg.metrics:
        if metric.family not in kpi_families:
            errors.append(f"metric {metric.id} family {metric.family} is not in the dictionary")

    tagged = {(t.get("entity"), t.get("column")) for t in pkg.pii_tags}
    for entity in pkg.entities:
        for col in entity.columns:
            if col.pii_tag == "restricted" and (entity.logical_entity, col.name) not in tagged:
                errors.append(
                    f"restricted column {entity.logical_entity}.{col.name} "
                    "must also appear in pii_tags.yaml"
                )
    return errors


def validate_domain(domain: str) -> DomainPackage:
    pkg = load_domain(domain)
    _fail(validate_package(pkg))
    return pkg
