"""Read one table from CSV, Excel, Parquet, or another tabular file."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

SUFFIXES = (
    ".csv",
    ".tsv",
    ".txt",
    ".parquet",
    ".pq",
    ".xlsx",
    ".xlsm",
    ".xls",
    ".json",
    ".jsonl",
    ".feather",
    ".orc",
)


def read_table(path: Path | str) -> pd.DataFrame:
    file_path = Path(path)
    kind = file_path.suffix.lower()
    if kind in {".csv"}:
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
                print("Excel sheet", sheet, "from", file_path.name, "rows", len(frame))
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
    raise ValueError("Unsupported table file: {0}".format(file_path.name))


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
