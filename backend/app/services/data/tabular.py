"""Read one table from a file or from uploaded bytes."""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from app.config import UPLOAD_EXTENSIONS
from app.errors import DataNotFoundError, InvalidInputError

LOGGER = logging.getLogger(__name__)

SUFFIXES = UPLOAD_EXTENSIONS
_EXCEL = {".xlsx", ".xlsm"}


def _first_sheet_with_columns(source: Path | BinaryIO, label: str) -> pd.DataFrame:
    book = pd.ExcelFile(source)
    for sheet in book.sheet_names:
        frame = pd.read_excel(book, sheet_name=sheet)
        if len(frame.columns):
            LOGGER.info("Using Excel sheet %s of %s (%d rows)", sheet, label, len(frame))
            return frame
    raise InvalidInputError(f"{label} has no sheet with columns.")


def _read(kind: str, source: Path | BinaryIO, label: str) -> pd.DataFrame:
    try:
        if kind == ".csv":
            return pd.read_csv(source)
        if kind == ".tsv":
            return pd.read_csv(source, sep="\t")
        if kind == ".parquet":
            return pd.read_parquet(source)
        if kind in _EXCEL:
            return _first_sheet_with_columns(source, label)
        if kind == ".jsonl":
            return pd.read_json(source, lines=True)
        if kind == ".json":
            return pd.read_json(source)
    except (ValueError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise InvalidInputError(f"{label} could not be read as {kind}: {exc}") from exc
    raise InvalidInputError(f"{label}: unsupported file type {kind!r}. Use one of {', '.join(SUFFIXES)}.")


def read_table(path: Path | str) -> pd.DataFrame:
    file_path = Path(path)
    if not file_path.is_file():
        raise DataNotFoundError(f"Table file not found: {file_path}")
    return _read(file_path.suffix.lower(), file_path, file_path.name)


def read_table_bytes(filename: str, data: bytes) -> pd.DataFrame:
    """Parse an uploaded file held in memory. The type comes from the file name."""
    return _read(Path(filename).suffix.lower(), io.BytesIO(data), filename)
