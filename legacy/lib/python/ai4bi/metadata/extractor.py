"""Table and column metadata from live datasets plus the semantic registration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ai4bi.semantic.models import DomainPackage
from ai4bi.sql.grounding import profile_frame

SAMPLE_VALUES = 10


def _column_entry(profile: Any, spec: Any, restricted: bool) -> dict[str, Any]:
    return {
        "name": profile.name,
        "dtype": profile.dtype,
        "role": spec.role if spec else profile.role,
        "description": (spec.description if spec and spec.description else profile.description),
        "null_fraction": round(profile.null_fraction, 4),
        "distinct_values": int(profile.nunique),
        "has_data": bool(profile.has_data),
        "restricted": restricted,
        "sample_values": [] if restricted else list(profile.values[:SAMPLE_VALUES]),
    }


def extract_metadata(pkg: DomainPackage, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    restricted = {c.lower() for c in pkg.restricted_columns()}
    datasets: list[dict[str, Any]] = []
    for table, frame in frames.items():
        entity = pkg.entity_for_dataset(table)
        specs = {c.name.lower(): c for c in (entity.columns if entity else [])}
        profiles = profile_frame(frame)
        datasets.append(
            {
                "dataset": table,
                "logical_entity": entity.logical_entity if entity else None,
                "data_product_id": entity.data_product_id if entity else None,
                "grain": entity.grain if entity else None,
                "primary_keys": entity.primary_keys if entity else [],
                "row_count": int(len(frame)),
                "columns": [
                    _column_entry(p, specs.get(p.name.lower()), p.name.lower() in restricted)
                    for p in profiles
                ],
            }
        )
    return {
        "domain": pkg.domain,
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_system": pkg.contract.source_system,
        "datasets": datasets,
        "relationships": [
            {
                "id": j.id,
                "left_entity": j.left_entity,
                "right_entity": j.right_entity,
                "condition": j.condition,
                "join_type": j.join_type,
                "cardinality": j.cardinality,
            }
            for j in pkg.joins
            if j.allowed_for_nlq
        ],
    }


def metadata_to_records(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """Flat rows, one per column, for a tabular output such as a Dataiku dataset."""
    rows: list[dict[str, Any]] = []
    for dataset in metadata.get("datasets") or []:
        for column in dataset.get("columns") or []:
            rows.append(
                {
                    "domain": metadata.get("domain"),
                    "dataset": dataset.get("dataset"),
                    "logical_entity": dataset.get("logical_entity"),
                    "row_count": dataset.get("row_count"),
                    "column": column.get("name"),
                    "dtype": column.get("dtype"),
                    "role": column.get("role"),
                    "description": column.get("description"),
                    "null_fraction": column.get("null_fraction"),
                    "distinct_values": column.get("distinct_values"),
                    "restricted": column.get("restricted"),
                    "sample_values": ", ".join(str(v) for v in column.get("sample_values") or []),
                    "extracted_at": metadata.get("extracted_at"),
                }
            )
    return rows
