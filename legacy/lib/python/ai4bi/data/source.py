"""Dataset access contract. Platforms implement it; the pipeline only sees frames."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd

from ai4bi.config.errors import DataNotFoundError


@runtime_checkable
class DatasetSource(Protocol):
    """Return the fact tables for one domain, keyed by SQL table name."""

    def load(self, domain: str, table_names: list[str] | None = None) -> dict[str, pd.DataFrame]:
        ...


class InMemorySource:
    """Frames supplied by the caller: a recipe, a notebook, or a test."""

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = dict(frames)

    def load(self, domain: str, table_names: list[str] | None = None) -> dict[str, pd.DataFrame]:
        if not self._frames:
            raise DataNotFoundError(f"No in-memory datasets were supplied for domain {domain!r}.")
        if not table_names:
            return dict(self._frames)
        chosen = {name: frame for name, frame in self._frames.items() if name in table_names}
        return chosen or dict(self._frames)
