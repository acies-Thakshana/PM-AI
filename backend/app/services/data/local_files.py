"""Datasets stored as files: ``<root>/<domain>/<table>.<ext>``."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pandas as pd

from app.services.common.naming import validate_domain
from app.services.data.source import select_tables
from app.services.data.tabular import SUFFIXES, read_table

LOGGER = logging.getLogger(__name__)


class LocalFileSource:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def _folder(self, domain: str) -> Path:
        return self._root / validate_domain(domain)

    def _files(self, domain: str) -> dict[str, Path]:
        """Table name to file. When one table exists in two formats the earlier suffix wins."""
        folder = self._folder(domain)
        if not folder.is_dir():
            return {}
        files: dict[str, Path] = {}
        for suffix in SUFFIXES:
            for path in sorted(folder.glob(f"*{suffix}")):
                if path.is_file() and not path.name.startswith("."):
                    files.setdefault(path.stem, path)
        return files

    def list_domains(self) -> list[str]:
        if not self._root.is_dir():
            return []
        return sorted(p.name for p in self._root.iterdir() if p.is_dir() and self._files(p.name))

    def list_tables(self, domain: str) -> list[str]:
        return sorted(self._files(domain))

    def version(self, domain: str) -> str:
        digest = hashlib.sha1(usedforsecurity=False)
        for name, path in sorted(self._files(domain).items()):
            stat = path.stat()
            digest.update(f"{name}:{path.suffix}:{stat.st_size}:{stat.st_mtime_ns};".encode())
        return digest.hexdigest()

    def load(self, domain: str, table_names: list[str] | None = None) -> dict[str, pd.DataFrame]:
        files = self._files(domain)
        names = select_tables(domain, sorted(files), table_names)
        frames = {name: read_table(files[name]) for name in names}
        LOGGER.info("Loaded %s for domain %s from %s", sorted(frames), domain, self._root)
        return frames
