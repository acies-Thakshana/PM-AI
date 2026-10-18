"""Flow datasets in and out of a recipe.

Input classification and graph conversion are plain functions over DataFrames,
so they are tested without Dataiku.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ai4bi.config.errors import DataNotFoundError
from ai4bi.data.local_files import read_table, read_tables_in
from ai4bi.knowledge.graph import KnowledgeGraph
from ai4bi.knowledge.store import graph_from_records, graph_to_records
from ai4bi.logging import get_logger
from ai4bi.pipeline.batch import QUESTION_COLUMNS
from ai4bi.semantic.registry import SemanticRegistry
from ai4bi.utils.frames import find_column, is_missing

LOGGER = get_logger(__name__)
GRAPH_COLUMNS = ["record_type", "payload"]
REGISTRY_COLUMNS = [
    "domain",
    "semantic_version",
    "artifact_type",
    "artifact_id",
    "status",
    "source",
    "confidence",
    "payload",
    "created_at",
    "input_fingerprint",
    "validation_message",
]
MODEL_SQL_COLUMNS = ("LLM_generated_SQL", "llm_generated_sql", "generated_sql", "sql_query")


def norm(name: str) -> str:
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def short_name(name: str) -> str:
    """Drop the PROJECTKEY. prefix Dataiku adds to shared datasets."""
    text = str(name or "").strip()
    return text.split(".")[-1] if "." in text else text


def declared_names(kind: str) -> list[str]:
    """Dataset names wired to the recipe. ``kind`` is 'in' or 'out'."""
    from dataiku import recipe as dku_recipe

    roles = ("main", "input", "inputs", "datasets") if kind == "in" else ("main", "output", "outputs")
    getter = dku_recipe.get_input_names_for_role if kind == "in" else dku_recipe.get_output_names_for_role
    names: list[str] = []
    for role in roles:
        try:
            names.extend(getter(role) or [])
        except Exception:  # noqa: BLE001
            continue
    extra = getattr(dku_recipe, "get_incoming_names" if kind == "in" else "get_outgoing_names", None)
    if extra is not None:
        try:
            names.extend(extra() or [])
        except Exception:  # noqa: BLE001
            pass
    return list(dict.fromkeys(n for n in names if n))


def read_dataset(name: str) -> pd.DataFrame:
    """Read through Dataiku; fall back to the uploaded files behind the dataset."""
    import dataiku

    dataset = dataiku.Dataset(name)
    try:
        frame = dataset.get_dataframe()
        if frame is not None and len(frame.columns):
            LOGGER.info("Loaded %s rows=%s through Dataiku", name, len(frame))
            return frame
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Dataiku reader failed for %s: %s", name, exc)
    try:
        details = (dataset.get_location_info() or {}).get("info") or {}
    except Exception as exc:  # noqa: BLE001
        raise DataNotFoundError(f"Could not read {name}. Upload it in the Flow as CSV, Excel, or Parquet. {exc}") from exc
    root = details.get("path")
    if not root:
        raise DataNotFoundError(f"Could not read {name}. Upload it in the Flow as CSV, Excel, or Parquet.")
    folder = Path(root)
    chosen = details.get("file") or details.get("filename")
    candidate = folder / chosen if chosen and folder.is_dir() else folder
    if candidate.is_file():
        return read_table(candidate)
    found = read_tables_in(folder) if folder.is_dir() else {}
    if not found:
        raise DataNotFoundError(
            f"Could not read {name}. Upload a CSV, Excel, or Parquet file. "
            "Excel needs openpyxl in the code environment. Parquet needs pyarrow."
        )
    return next(iter(found.values())) if len(found) == 1 else pd.concat(list(found.values()), ignore_index=True)


def write_dataset(name: str, frame: pd.DataFrame) -> None:
    import dataiku

    dataiku.Dataset(name).write_with_schema(frame)
    LOGGER.info("Wrote %s rows=%s", name, len(frame))


def is_graph_frame(name: str, frame: pd.DataFrame) -> bool:
    return "knowledgegraph" in norm(short_name(name)) or (
        set(GRAPH_COLUMNS) <= set(map(str, frame.columns)) and not is_registry_frame(name, frame)
    )


def is_registry_frame(name: str, frame: pd.DataFrame) -> bool:
    columns = set(map(str, frame.columns))
    return "semanticregistry" in norm(short_name(name)) or {
        "artifact_type",
        "artifact_id",
        "payload",
        "input_fingerprint",
    } <= columns


def is_question_frame(name: str, frame: pd.DataFrame) -> bool:
    key = norm(short_name(name))
    named = key in {"questions", "semanticvalidationquestions", "kpicubevalidation"} or key.endswith("questions")
    if named and find_column(frame, QUESTION_COLUMNS) is not None:
        return True
    return find_column(frame, ("input_question",)) is not None and "record_type" not in frame.columns


def has_model_sql(frame: pd.DataFrame) -> bool:
    column = find_column(frame, MODEL_SQL_COLUMNS)
    if column is None:
        return False
    return any(not is_missing(v) and str(v).strip() for v in frame[column].tolist())


@dataclass
class RecipeInputs:
    facts: dict[str, pd.DataFrame] = field(default_factory=dict)
    questions: pd.DataFrame | None = None
    graph: pd.DataFrame | None = None
    results: pd.DataFrame | None = None
    registry: pd.DataFrame | None = None


def classify_inputs(frames: dict[str, pd.DataFrame], *, want_results: bool = False) -> RecipeInputs:
    """Sort recipe inputs into fact tables, the question table, the graph, and a results table."""
    out = RecipeInputs()
    for name, frame in frames.items():
        if is_registry_frame(name, frame):
            out.registry = frame
        elif is_graph_frame(name, frame):
            out.graph = frame
        elif want_results and out.results is None and has_model_sql(frame):
            out.results = frame
        elif out.questions is None and is_question_frame(name, frame):
            out.questions = frame
        else:
            out.facts[short_name(name)] = frame
    return out


def split_outputs(names: list[str]) -> tuple[str, str]:
    """(results dataset, knowledge_graph dataset or '')."""
    results, graph = "", ""
    for name in names:
        if "knowledgegraph" in norm(short_name(name)):
            graph = graph or name
        elif not results:
            results = name
    if not results:
        raise DataNotFoundError(f"Declare a results output dataset. Outputs: {names}")
    return results, graph


def graph_from_frame(domain: str, frame: pd.DataFrame | None) -> KnowledgeGraph:
    if frame is None or frame.empty or "payload" not in frame.columns:
        return KnowledgeGraph(domain)
    return graph_from_records(domain, frame.to_dict(orient="records"))


def graph_to_frame(graph: KnowledgeGraph) -> pd.DataFrame:
    return pd.DataFrame(graph_to_records(graph), columns=GRAPH_COLUMNS)


def registry_from_frame(frame: pd.DataFrame | None) -> SemanticRegistry:
    if frame is None or frame.empty:
        return SemanticRegistry()
    return SemanticRegistry.from_records(frame.to_dict(orient="records"))


def registry_to_frame(registry: SemanticRegistry) -> pd.DataFrame:
    return pd.DataFrame(registry.to_records(), columns=REGISTRY_COLUMNS)


def split_onboarding_outputs(names: list[str]) -> dict[str, str]:
    """Resolve onboarding outputs by stable names, independent of Flow order."""
    out = {"catalog": "", "registry": "", "graph": "", "audit": ""}
    for name in names:
        key = norm(short_name(name))
        if "semanticregistry" in key:
            out["registry"] = name
        elif "knowledgegraph" in key:
            out["graph"] = name
        elif "audit" in key:
            out["audit"] = name
        elif "catalog" in key or "metadata" in key:
            out["catalog"] = name
    missing = [key for key in ("catalog", "registry") if not out[key]]
    if missing:
        raise DataNotFoundError(
            "Onboarding needs outputs named dataset_catalog and semantic_registry. "
            f"Missing: {', '.join(missing)}; outputs={names}"
        )
    return out


def summary_frame(summary: dict) -> pd.DataFrame:
    return pd.DataFrame([{"metric": key, "value": json.dumps(value, default=str)} for key, value in summary.items()])
