"""Load a domain onboarding package from YAML. No source-system code paths."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aibi.factory.models import (
    BiHarvest,
    Contract,
    DataDictionary,
    DomainPackage,
    EntityRegistration,
    GlossaryTerm,
    MetricVersion,
    RegisteredJoin,
)
from aibi.settings import PROJECT_ROOT, load_yaml

ONBOARDING_ROOT = PROJECT_ROOT / "onboarding" / "domains"


def domain_dir(domain: str) -> Path:
    return ONBOARDING_ROOT / domain


def list_domains() -> list[str]:
    if not ONBOARDING_ROOT.exists():
        return []
    return sorted(
        p.name for p in ONBOARDING_ROOT.iterdir() if p.is_dir() and (p / "contract.yaml").exists()
    )


def _load(path: Path) -> Any:
    return load_yaml(path)


def load_domain(domain: str) -> DomainPackage:
    root = domain_dir(domain)
    if not root.exists():
        raise FileNotFoundError(f"Onboarding package not found: {root}")

    contract = Contract.model_validate(_load(root / "contract.yaml"))
    dictionary = DataDictionary.model_validate(_load(root / "dictionary.yaml"))
    entities_doc = _load(root / "entities.yaml") or {}
    entities = [EntityRegistration.model_validate(e) for e in entities_doc.get("entities") or []]
    joins_doc = _load(root / "joins.yaml") or {}
    joins = [RegisteredJoin.model_validate(j) for j in joins_doc.get("joins") or []]
    glossary_doc = _load(root / "glossary.yaml") or {}
    glossary = [GlossaryTerm.model_validate(t) for t in glossary_doc.get("terms") or []]
    harvest = None
    if (root / "harvest.yaml").exists():
        harvest = BiHarvest.model_validate(_load(root / "harvest.yaml"))
    metrics_doc = _load(root / "metrics.yaml") if (root / "metrics.yaml").exists() else {}
    metrics = [MetricVersion.model_validate(m) for m in (metrics_doc or {}).get("metrics") or []]
    pii_tags = list((_load(root / "pii_tags.yaml") or {}).get("tags") or [])
    return DomainPackage(
        contract=contract,
        dictionary=dictionary,
        entities=entities,
        joins=joins,
        glossary=glossary,
        harvest=harvest,
        metrics=metrics,
        pii_tags=pii_tags,
    )
