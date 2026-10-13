"""Generic data-product registry: maps semantic IDs to local datasets.

Reusable across dashboards. Add a new curated dataset by:
  1. Registering it here (or in config/data_products.yaml)
  2. Declaring it under data_products: in a semantic YAML
  3. Pointing metrics at that data_product_id
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from aibi.settings import PROJECT_ROOT, get_settings, load_yaml


def _registry_path() -> Path:
    return get_settings().project_root / "config" / "data_products.yaml"


@lru_cache(maxsize=1)
def load_data_product_registry() -> dict[str, Any]:
    doc = load_yaml(_registry_path())
    products = {p["id"]: p for p in (doc.get("data_products") or []) if p.get("id")}
    return {
        "version": doc.get("version") or "1",
        "products": products,
        "default_product_id": doc.get("default_product_id"),
    }


def resolve_product_path(entry: dict[str, Any]) -> Path:
    raw = entry.get("path") or ""
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def list_registered_products() -> list[dict[str, Any]]:
    reg = load_data_product_registry()
    return list(reg["products"].values())


@lru_cache(maxsize=8)
def load_frame_for_product(product_id: str) -> pd.DataFrame:
    """Load any registered curated dataset by semantic data_product id."""
    reg = load_data_product_registry()
    entry = reg["products"].get(product_id)
    if not entry:
        # Fallback: try KPI cube for backward compatibility
        default_id = reg.get("default_product_id")
        if default_id and default_id in reg["products"]:
            entry = reg["products"][default_id]
            product_id = default_id
        else:
            raise KeyError(f"Data product not registered: {product_id}")
    path = resolve_product_path(entry)
    if not path.exists():
        raise FileNotFoundError(f"Dataset file missing for {product_id}: {path}")
    frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    for column in frame.select_dtypes(include=["object"]).columns:
        frame[column] = (
            frame[column]
            .astype("string")
            .str.replace("\xa0", " ", regex=False)
            .str.strip()
        )
    return frame


def product_for_metric(model: dict[str, Any], metric: dict[str, Any] | None) -> dict[str, Any]:
    """Resolve the physical product binding for a metric."""
    reg = load_data_product_registry()
    product_ids = list((metric or {}).get("data_product_ids") or [])
    for pid in product_ids:
        if pid in reg["products"]:
            return reg["products"][pid]
    # Match by physical_dataset name declared in semantic YAML
    for dp in model.get("data_products") or []:
        if dp.get("id") in product_ids or not product_ids:
            pid = dp.get("id")
            if pid in reg["products"]:
                return reg["products"][pid]
    default_id = reg.get("default_product_id")
    if default_id and default_id in reg["products"]:
        return reg["products"][default_id]
    raise KeyError("No registered data product available for metric")


def bu_column_for_product(entry: dict[str, Any]) -> str:
    return str(entry.get("bu_column") or "BU")


def clear_registry_cache() -> None:
    load_data_product_registry.cache_clear()
    load_frame_for_product.cache_clear()
