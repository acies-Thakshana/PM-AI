"""Load and cache the curated KPI cube for local hosting."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import pandas as pd

from aibi.settings import get_settings

# Canonical business columns used by the semantic model.
BU_COL = "BU"
PILLAR_COL = "Pillar Type"
SITE_COL = "Site Name"
YEAR_COL = "Year RPT"
QUARTER_COL = "Quarter RPT"
MONTH_COL = "Month RPT"
REGION_COL = "Region"
CATEGORY_COL = "Category (L1)"
INIT_ID_COL = "Initiative ID"
INIT_NAME_COL = "Initiative name"
ACTUAL_COL = "Actual Productivity"
FORECAST_COL = "Forecast Productivity Plan"
AGG_COL = "Agg Productivity"
FRESH_COL = "Data Updated Date"


def default_kpi_path() -> Path:
    settings = get_settings()
    env_path = os.environ.get("AIBI_KPI_PARQUET") or os.environ.get("NLQ_DATA_PATHS")
    candidates = [
        Path(env_path.split(",")[0]) if env_path else None,
        settings.project_root / "local_data" / "fixtures" / "KPI_data.parquet",
        Path(r"C:\Users\BharadNa\Downloads\KPI_data.parquet"),
        settings.nl2sql_root / "data" / "KPI_data.parquet",
    ]
    for path in candidates:
        if path is not None and path.exists():
            return path
    raise FileNotFoundError(
        "KPI_data.parquet not found. Place it under local_data/fixtures/KPI_data.parquet"
    )


@lru_cache(maxsize=1)
def load_kpi_frame(path: str | None = None) -> pd.DataFrame:
    parquet = Path(path) if path else default_kpi_path()
    frame = pd.read_parquet(parquet)
    # Normalize whitespace / NBSP in string columns used for filters.
    for column in frame.select_dtypes(include=["object"]).columns:
        frame[column] = (
            frame[column]
            .astype("string")
            .str.replace("\xa0", " ", regex=False)
            .str.strip()
        )
    if YEAR_COL in frame.columns:
        frame[YEAR_COL] = pd.to_numeric(frame[YEAR_COL], errors="coerce")
    return frame


def unique_values(frame: pd.DataFrame, column: str, limit: int = 80) -> list[str]:
    if column not in frame.columns:
        return []
    values = (
        frame[column]
        .dropna()
        .astype(str)
        .str.strip()
        .replace("", pd.NA)
        .dropna()
        .drop_duplicates()
        .tolist()
    )
    values = [v for v in values if v]
    values.sort()
    return values[:limit]
