"""Read datasets from local files: CSV, TSV, Excel, Parquet, JSON, Feather, ORC."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ai4bi.config.errors import DataNotFoundError
from ai4bi.logging import get_logger

LOGGER = get_logger(__name__)

SUFFIXES = (
    ".csv", ".tsv", ".txt", ".parquet", ".pq", ".xlsx", ".xlsm", ".xls",
    ".json", ".jsonl", ".feather", ".orc",
)


def read_table(path: Path | str) -> pd.DataFrame:
    file_path = Path(path)
    kind = file_path.suffix.lower()
    try:
        if kind == ".csv":
            return pd.read_csv(file_path)
        if kind == ".tsv":
            return pd.read_csv(file_path, sep="\t")
        if kind == ".txt":
            return pd.read_csv(file_path, sep=None, engine="python")
        if kind in {".parquet", ".pq"}:
            return pd.read_parquet(file_path)
        if kind in {".xlsx", ".xlsm", ".xls"}:
            book = pd.ExcelFile(file_path)
            for sheet in book.sheet_names:
                frame = pd.read_excel(book, sheet_name=sheet)
                if len(frame.columns):
                    LOGGER.info("Excel sheet %s from %s rows %s", sheet, file_path.name, len(frame))
                    return frame
            return pd.read_excel(file_path)
        if kind == ".jsonl":
            return pd.read_json(file_path, lines=True)
        if kind == ".json":
            return pd.read_json(file_path)
        if kind == ".feather":
            return pd.read_feather(file_path)
        if kind == ".orc":
            return pd.read_orc(file_path)
    except ImportError as exc:
        raise DataNotFoundError(
            f"Reading {file_path.name} needs an extra package: {exc}. "
            "Install requirements-optional.txt."
        ) from exc
    raise DataNotFoundError(f"Unsupported table file: {file_path}")


def read_tables_in(folder: Path | str) -> dict[str, pd.DataFrame]:
    root = Path(folder)
    frames: dict[str, pd.DataFrame] = {}
    if not root.is_dir():
        return frames
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in SUFFIXES:
            continue
        frames[path.stem] = read_table(path)
    return frames


class LocalFileSource:
    """Datasets under ``<samples_root>/<domain>/<table>.<ext>``."""

    def __init__(self, samples_root: Path) -> None:
        self.samples_root = Path(samples_root)

    def folder(self, domain: str) -> Path:
        return self.samples_root / domain

    def load(self, domain: str, table_names: list[str] | None = None) -> dict[str, pd.DataFrame]:
        root = self.folder(domain)
        if not root.is_dir():
            raise DataNotFoundError(
                f"No local datasets for domain {domain!r}. Expected files under {root}"
            )
        frames: dict[str, pd.DataFrame] = {}
        missing: list[str] = []
        for name in table_names or []:
            path = next((root / f"{name}{s}" for s in SUFFIXES if (root / f"{name}{s}").exists()), None)
            if path is None:
                missing.append(name)
            else:
                frames[name] = read_table(path)
        if frames and missing:
            raise DataNotFoundError(
                f"Missing datasets {missing} for domain {domain!r}. Expected files like {root / (missing[0] + '.csv')}"
            )
        if not frames:
            frames = read_tables_in(root)
        if not frames:
            raise DataNotFoundError(
                f"Folder {root} has no readable tables. Add CSV, Excel, or Parquet files."
            )
        LOGGER.info("Loaded local tables %s from %s", sorted(frames), root)
        return frames
