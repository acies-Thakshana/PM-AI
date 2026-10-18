"""Load a baseline domain package from YAML files, or infer one from the supplied frames."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from pydantic import ValidationError

from app.errors import ConfigError, DomainNotFoundError
from app.services.semantic.models import (
    BiHarvest,
    BusinessRule,
    BusinessUnitContext,
    ColumnSpec,
    Contract,
    DataDictionary,
    DictionaryKpi,
    DomainPackage,
    EntityRegistration,
    GlossaryTerm,
    MetricVersion,
    QueryExample,
    RegisteredJoin,
    Steward,
    ValidatedSql,
)
from app.services.semantic.pii import inferred_restricted_columns

REQUIRED_FILES = ("contract.yaml", "dictionary.yaml", "entities.yaml")


def read_yaml(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc


def _items(root: Path, filename: str, key: str) -> list[Any]:
    payload = read_yaml(root / filename)
    if not isinstance(payload, dict):
        raise ConfigError(f"{root / filename} must contain a mapping with key {key!r}")
    return list(payload.get(key) or [])


def _validate(model: Any, payload: Any, path: Path) -> Any:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(f"{path} does not match the {model.__name__} contract:\n{exc}") from exc


def load_domain_package(root: Path) -> DomainPackage:
    if not root.is_dir():
        raise DomainNotFoundError(f"Semantic domain package not found: {root}")
    missing = [name for name in REQUIRED_FILES if not (root / name).exists()]
    if missing:
        raise ConfigError(f"Domain package {root} is missing required files: {', '.join(missing)}")

    contract = _validate(Contract, read_yaml(root / "contract.yaml"), root / "contract.yaml")
    dictionary = _validate(DataDictionary, read_yaml(root / "dictionary.yaml"), root / "dictionary.yaml")
    entities = [
        _validate(EntityRegistration, e, root / "entities.yaml") for e in _items(root, "entities.yaml", "entities")
    ]
    joins = [_validate(RegisteredJoin, j, root / "joins.yaml") for j in _items(root, "joins.yaml", "joins")]
    glossary = [_validate(GlossaryTerm, t, root / "glossary.yaml") for t in _items(root, "glossary.yaml", "terms")]
    harvest = None
    if (root / "harvest.yaml").exists():
        harvest = _validate(BiHarvest, read_yaml(root / "harvest.yaml"), root / "harvest.yaml")
    metrics = [_validate(MetricVersion, m, root / "metrics.yaml") for m in _items(root, "metrics.yaml", "metrics")]
    business_unit = None
    bu_payload = read_yaml(root / "business_unit.yaml")
    if bu_payload:
        business_unit = _validate(
            BusinessUnitContext, bu_payload.get("business_unit") or bu_payload, root / "business_unit.yaml"
        )
    rules = [_validate(BusinessRule, r, root / "rules.yaml") for r in _items(root, "rules.yaml", "rules")]
    examples = [
        _validate(QueryExample, q, root / "query_examples.yaml")
        for q in _items(root, "query_examples.yaml", "examples")
    ]
    validated = [
        _validate(ValidatedSql, v, root / "validated_sql.yaml") for v in _items(root, "validated_sql.yaml", "queries")
    ]
    package = DomainPackage(
        contract=contract,
        dictionary=dictionary,
        entities=entities,
        joins=joins,
        glossary=glossary,
        harvest=harvest,
        metrics=metrics,
        pii_tags=_items(root, "pii_tags.yaml", "tags"),
        business_unit=business_unit,
        rules=rules,
        query_examples=examples,
        validated_sql=validated,
        visuals=_items(root, "visuals.yaml", "bindings"),
        drills=read_yaml(root / "drills.yaml") or {},
        explainability=read_yaml(root / "explainability.yaml") or {},
    )
    _check_references(package, root)
    return package


def _check_references(pkg: DomainPackage, root: Path) -> None:
    entity_names = {e.logical_entity for e in pkg.entities}
    for join in pkg.joins:
        for side in (join.left_entity, join.right_entity):
            if side not in entity_names:
                raise ConfigError(f"{root / 'joins.yaml'}: join {join.id} references unknown entity {side!r}")
    products = {e.data_product_id for e in pkg.entities}
    for metric in pkg.metrics:
        if metric.data_product_id not in products:
            raise ConfigError(
                f"{root / 'metrics.yaml'}: metric {metric.id} uses unknown data product {metric.data_product_id!r}"
            )


def _is_numeric(series: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)


def _infer_role(name: str, series: pd.Series) -> str:
    lowered = name.lower()
    if _is_numeric(series):
        if lowered.endswith("_id") or lowered == "id":
            return "key"
        return "measure"
    if lowered.endswith(("_at", "_date")) or "date" in lowered or "time" in lowered:
        return "timestamp"
    return "attribute"


def columns_from_frame(frame: pd.DataFrame, restricted: set[str] | None = None) -> list[ColumnSpec]:
    blocked = {c.lower() for c in (restricted or set())}
    columns: list[ColumnSpec] = []
    for name in frame.columns:
        tag = "restricted" if str(name).lower() in blocked else "none"
        columns.append(
            ColumnSpec(
                name=str(name),
                data_type=str(frame[name].dtype),
                role=_infer_role(str(name), frame[name]),  # type: ignore[arg-type]
                pii_tag=tag,  # type: ignore[arg-type]
                sensitive=tag == "restricted",
            )
        )
    return columns


def package_from_frames(
    domain: str,
    frames: dict[str, pd.DataFrame],
    *,
    pii_columns: list[str] | None = None,
) -> DomainPackage:
    """Generic package from tabular extracts.

    Joins stay empty until onboarding validates them or a steward adds them.
    """
    if not frames:
        raise DomainNotFoundError(f"Domain {domain!r} has no semantic package and no datasets to infer one from.")
    restricted = set(pii_columns or [])
    entities: list[EntityRegistration] = []
    for name, frame in frames.items():
        entities.append(
            EntityRegistration(
                logical_entity=str(name) if len(frames) > 1 else domain,
                source_system="other",
                source_object=str(name),
                physical_dataset=str(name),
                data_product_id=f"dp.{domain}.{name}",
                grain="as provided by the data team",
                primary_keys=[str(frame.columns[0])] if len(frame.columns) else ["row"],
                entity_kind="transactional",
                columns=columns_from_frame(frame, restricted)
                or [ColumnSpec(name="row", data_type="string", role="key")],
                notes="Seeded from the supplied datasets. Joins are not inferred.",
            )
        )
    names = [str(n) for n in frames]
    return DomainPackage(
        contract=Contract(
            domain=domain,
            source_system="other",
            historical_from="",
            historical_to="",
            extracts=names,
            master_entities=names,
            transactional_entities=names,
            owner=Steward(role="data.engineering", team="onboarding"),
            notes="Inferred package. Joins are added by onboarding (after validation) or by a steward.",
        ),
        dictionary=DataDictionary(
            domain=domain,
            kpis=[
                DictionaryKpi(
                    family="primary_measure",
                    name="Primary measure",
                    business_definition="The model chooses the measure from the columns and the knowledge graph.",
                    formula_hint="SUM, AVG, or COUNT over a measure column",
                    grain="as provided",
                    owner="metric.owner",
                    synonyms=["kpi", "metric"],
                )
            ],
        ),
        entities=entities,
        pii_tags=[{"column": c, "action": "restricted"} for c in sorted(restricted)],
        inferred=True,
    )


def align_with_frames(pkg: DomainPackage, frames: dict[str, pd.DataFrame]) -> DomainPackage:
    """Add columns and datasets present in the live data but missing from the registration.

    Registered descriptions, roles, and PII tags always win. Unregistered datasets
    become inferred entities so they can be queried alone; joins still need to be registered.
    Columns whose names look personal are restricted even when nobody has tagged them yet.
    """
    updated = pkg.model_copy(deep=True)
    restricted = updated.restricted_columns() | inferred_restricted_columns(frames)
    for name, frame in frames.items():
        entity = updated.entity_for_dataset(name)
        if entity is None:
            updated.entities.append(
                EntityRegistration(
                    logical_entity=str(name),
                    source_system="other",
                    source_object=str(name),
                    physical_dataset=str(name),
                    data_product_id=f"dp.{updated.domain}.{name}",
                    grain="as provided by the data team",
                    primary_keys=[str(frame.columns[0])] if len(frame.columns) else ["row"],
                    entity_kind="transactional",
                    columns=columns_from_frame(frame, restricted)
                    or [ColumnSpec(name="row", data_type="string", role="key")],
                    notes="Not part of the registered package. Columns were read from the dataset.",
                )
            )
            continue
        known = {c.name.lower() for c in entity.columns}
        extra = [c for c in columns_from_frame(frame, restricted) if c.name.lower() not in known]
        entity.columns.extend(extra)
    return updated
