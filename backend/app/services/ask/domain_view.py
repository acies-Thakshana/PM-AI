"""Everything the pipeline needs to know about one domain, resolved once per request.

A view combines the live data (from the versioned cache), the semantic package (baseline YAML
pack or one inferred from the data) overlaid with what the registry has learned, and the
SQL-ready tables with restricted columns removed. Batch runs resolve a view once for all
their questions.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.errors import DataNotFoundError, DomainNotFoundError
from app.services.context import AppContext
from app.services.data.cache import PreparedData
from app.services.semantic.models import DomainPackage


@dataclass(frozen=True)
class DomainView:
    pkg: DomainPackage
    raw: dict[str, pd.DataFrame]
    prepared: PreparedData

    @property
    def tables(self) -> dict[str, pd.DataFrame]:
        return self.prepared.tables


def _table_names(ctx: AppContext, domain: str) -> list[str]:
    available = ctx.source.list_tables(domain)
    baseline = ctx.semantic.exists(domain)
    if not available:
        if baseline:
            raise DataNotFoundError(f"Domain {domain!r} is defined but has no datasets. Upload its files first.")
        raise DomainNotFoundError(f"Domain {domain!r} not found. Upload datasets to create it.")
    if baseline:
        required = {entity.physical_dataset for entity in ctx.semantic.load(domain).entities}
        missing = sorted(required - set(available))
        if missing:
            raise DataNotFoundError(f"Domain {domain!r} is missing datasets: {', '.join(missing)}.")
    return available


def resolve_domain(ctx: AppContext, domain: str) -> DomainView:
    names = _table_names(ctx, domain)
    raw = ctx.cache.raw(domain, names)
    registry = ctx.registry.load(domain)
    pkg = ctx.semantic.load_with_registry(domain, raw, registry, include_drafts=ctx.settings.include_drafts)
    prepared = ctx.cache.prepared(domain, names, pkg.restricted_columns())
    return DomainView(pkg=pkg, raw=raw, prepared=prepared)
