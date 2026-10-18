"""Where the fact tables come from. The pipeline only ever sees dataframes."""

from __future__ import annotations

from typing import Protocol

import pandas as pd

from app.errors import DataNotFoundError


class DatasetSource(Protocol):
    def list_domains(self) -> list[str]:
        """Domains that have at least one dataset."""
        ...

    def list_tables(self, domain: str) -> list[str]:
        """Table names available for the domain, sorted. Empty when the domain has no data."""
        ...

    def version(self, domain: str) -> str:
        """A cheap token that changes whenever the domain's data changes."""
        ...

    def load(self, domain: str, table_names: list[str] | None = None) -> dict[str, pd.DataFrame]:
        """The named tables, or every table of the domain when no names are given.

        Raises ``DataNotFoundError`` when a requested table or the domain's data is missing.
        """
        ...


class ChainedSource:
    """Several sources searched in order. The first one that has data for a domain serves it.

    This lets bundled sample data sit behind uploaded data without the two mixing.
    """

    def __init__(self, sources: list[DatasetSource]) -> None:
        self._sources = list(sources)

    def _owner(self, domain: str) -> DatasetSource | None:
        return next((source for source in self._sources if source.list_tables(domain)), None)

    def list_domains(self) -> list[str]:
        return sorted({domain for source in self._sources for domain in source.list_domains()})

    def list_tables(self, domain: str) -> list[str]:
        owner = self._owner(domain)
        return owner.list_tables(domain) if owner else []

    def version(self, domain: str) -> str:
        owner = self._owner(domain)
        return owner.version(domain) if owner else ""

    def load(self, domain: str, table_names: list[str] | None = None) -> dict[str, pd.DataFrame]:
        owner = self._owner(domain)
        if owner is None:
            raise DataNotFoundError(f"No datasets for domain {domain!r}. Upload files for it first.")
        return owner.load(domain, table_names)


def select_tables(domain: str, available: list[str], requested: list[str] | None) -> list[str]:
    """The tables to load: all of them, or the requested ones (every one must exist)."""
    if not requested:
        return available
    missing = sorted(set(requested) - set(available))
    if missing:
        raise DataNotFoundError(
            f"Domain {domain!r} has no dataset named {', '.join(missing)}. Available: {', '.join(available)}."
        )
    return list(requested)
