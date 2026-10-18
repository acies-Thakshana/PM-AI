"""Recipe bodies. Each Dataiku recipe file calls exactly one of these.

They only move data between Flow datasets and the platform-independent core.
"""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from ai4bi.config.errors import DataNotFoundError
from ai4bi.data.source import InMemorySource
from ai4bi.evaluation.scoring import score_results
from ai4bi.knowledge.store import MemoryGraphStore
from ai4bi.knowledge.seed import seed_from_package
from ai4bi.logging import get_logger
from ai4bi.metadata.extractor import extract_metadata, metadata_to_records
from ai4bi.pipeline.batch import run_batch
from ai4bi.pipeline.context import AppContext, build_context
from ai4bi.semantic.loader import align_with_frames
from ai4bi.semantic.onboarding import onboard_domain
from ai4bi_dataiku import io
from ai4bi_dataiku.variables import load_dataiku_settings

LOGGER = get_logger(__name__)
Reader = Callable[[str], pd.DataFrame]
Writer = Callable[[str, pd.DataFrame], None]


def _context(facts: dict[str, pd.DataFrame]) -> AppContext:
    settings = load_dataiku_settings()
    return build_context(
        settings,
        data_source=InMemorySource(facts),
        graph_store=MemoryGraphStore(),
        history=False,
    )


def _read_all(names: list[str], reader: Reader) -> dict[str, pd.DataFrame]:
    frames = {}
    for name in names:
        frames[name] = reader(name)
        LOGGER.info("Input %s rows=%s columns=%s", name, len(frames[name]), list(frames[name].columns))
    return frames


def run_ask_recipe(
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    *,
    reader: Reader = io.read_dataset,
    writer: Writer = io.write_dataset,
) -> dict[str, Any]:
    """Fact datasets + question dataset (+ previous knowledge_graph) -> results + knowledge_graph."""
    inputs = io.declared_names("in") if inputs is None else inputs
    outputs = io.declared_names("out") if outputs is None else outputs
    split = io.classify_inputs(_read_all(inputs, reader))
    if not split.facts:
        raise DataNotFoundError("Connect at least one fact dataset. The question dataset is separate.")
    if split.questions is None:
        raise DataNotFoundError("Connect a question dataset with column input_question.")
    special = {name: io.norm(io.short_name(name)) for name in outputs}
    graph_name = next((name for name, key in special.items() if "knowledgegraph" in key), "")
    registry_name = next((name for name, key in special.items() if "semanticregistry" in key), "")
    catalog_name = next(
        (name for name, key in special.items() if "datasetcatalog" in key or "metadatacatalog" in key), ""
    )
    results_name = next(
        (
            name
            for name in outputs
            if name not in {graph_name, registry_name, catalog_name}
        ),
        "",
    )
    if not results_name:
        raise DataNotFoundError("Declare a results output dataset.")

    previous = split.graph
    if previous is None and graph_name:
        try:
            previous = reader(graph_name)
        except Exception as exc:  # noqa: BLE001
            LOGGER.info("No previous knowledge graph in %s yet: %s", graph_name, exc)
    previous_registry = split.registry
    if previous_registry is None and registry_name:
        try:
            previous_registry = reader(registry_name)
        except Exception as exc:  # noqa: BLE001
            LOGGER.info("No previous semantic registry in %s yet: %s", registry_name, exc)

    ctx = _context(split.facts)
    domain = ctx.settings.default_domain
    registry = io.registry_from_frame(previous_registry)
    package = ctx.semantic.load_or_infer(domain, split.facts)
    onboarding = None
    if ctx.settings.auto_onboard:
        onboarding = onboard_domain(
            domain,
            split.facts,
            llm=ctx.llm,
            settings=ctx.settings,
            registry=registry,
            base_package=package,
        )
        package, registry = onboarding.package, onboarding.registry
    else:
        package = ctx.semantic.load_with_registry(
            domain, split.facts, registry, include_drafts=ctx.settings.include_drafts
        )
    graph = io.graph_from_frame(domain, previous)
    seed_from_package(graph, package)
    LOGGER.info("Domain %s, fact tables %s, graph %s", domain, list(split.facts), graph.stats())
    results, graph = run_batch(
        split.questions,
        context=ctx,
        domain=domain,
        frames=split.facts,
        graph=graph,
        semantic_package=package,
    )

    writer(results_name, results)
    if graph_name:
        writer(graph_name, io.graph_to_frame(graph))
    if registry_name:
        writer(registry_name, io.registry_to_frame(registry))
    if catalog_name and onboarding is not None:
        records = pd.DataFrame(metadata_to_records(onboarding.metadata))
        records["semantic_version"] = onboarding.semantic_version
        writer(catalog_name, records)
    summary = {
        "ok": True,
        "domain": domain,
        "rows": len(results),
        "llm": getattr(ctx.llm, "name", ""),
        "answer_path": "llm_kg",
        "tables": list(split.facts),
        "semantic_version": onboarding.semantic_version if onboarding else "",
        "semantic_changed": onboarding.changed if onboarding else False,
        **{f"kg_{k}": v for k, v in graph.stats().items()},
    }
    LOGGER.info("Ask recipe finished: %s", summary)
    return summary


def run_onboarding_recipe(
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    *,
    reader: Reader = io.read_dataset,
    writer: Writer = io.write_dataset,
    force: bool = False,
) -> dict[str, Any]:
    """Fact datasets -> versioned registry, catalog, graph, and validation audit."""
    inputs = io.declared_names("in") if inputs is None else inputs
    outputs = io.declared_names("out") if outputs is None else outputs
    split = io.classify_inputs(_read_all(inputs, reader))
    if not split.facts:
        raise DataNotFoundError("Connect at least one fact dataset to the onboarding recipe.")
    names = io.split_onboarding_outputs(outputs)
    previous_registry = split.registry
    if previous_registry is None:
        try:
            previous_registry = reader(names["registry"])
        except Exception as exc:  # noqa: BLE001
            LOGGER.info("No previous semantic registry yet: %s", exc)
    previous_graph = split.graph
    if previous_graph is None and names["graph"]:
        try:
            previous_graph = reader(names["graph"])
        except Exception as exc:  # noqa: BLE001
            LOGGER.info("No previous knowledge graph yet: %s", exc)

    ctx = _context(split.facts)
    domain = ctx.settings.default_domain
    result = onboard_domain(
        domain,
        split.facts,
        llm=ctx.llm,
        settings=ctx.settings,
        registry=io.registry_from_frame(previous_registry),
        base_package=ctx.semantic.load_or_infer(domain, split.facts),
        force=force,
    )
    records = pd.DataFrame(metadata_to_records(result.metadata))
    records["semantic_version"] = result.semantic_version
    writer(names["catalog"], records)
    writer(names["registry"], io.registry_to_frame(result.registry))
    if names["graph"]:
        graph = io.graph_from_frame(domain, previous_graph)
        seed_from_package(graph, result.package)
        writer(names["graph"], io.graph_to_frame(graph))
    if names["audit"]:
        audit = pd.DataFrame(
            result.audit,
            columns=["artifact_type", "artifact_id", "active", "detail"],
        )
        audit.insert(0, "semantic_version", result.semantic_version)
        audit.insert(0, "domain", domain)
        writer(names["audit"], audit)
    return {
        "ok": True,
        "domain": domain,
        "semantic_version": result.semantic_version,
        "changed": result.changed,
        "artifacts": len(result.registry.artifacts),
        "active": len(result.registry.latest(domain)),
        "drafts": len(result.registry.latest(domain, include_drafts=True)) - len(result.registry.latest(domain)),
        "datasets": len(result.metadata.get("datasets") or []),
    }


def run_evaluation_recipe(
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    *,
    reader: Reader = io.read_dataset,
    writer: Writer = io.write_dataset,
) -> dict[str, Any]:
    """Results dataset + fact datasets -> per-question scores (+ optional summary dataset)."""
    inputs = io.declared_names("in") if inputs is None else inputs
    outputs = io.declared_names("out") if outputs is None else outputs
    split = io.classify_inputs(_read_all(inputs, reader), want_results=True)
    if split.results is None:
        raise DataNotFoundError(
            "Connect the results dataset written by the ask recipe (it has column LLM_generated_SQL)."
        )
    if not split.facts:
        raise DataNotFoundError("Connect the fact datasets the questions were asked against.")
    if not outputs:
        raise DataNotFoundError("Declare an output dataset for the evaluation detail.")
    detail_name = next((o for o in outputs if "summary" not in io.norm(o)), outputs[0])
    summary_name = next((o for o in outputs if "summary" in io.norm(o) and o != detail_name), "")

    ctx = _context(split.facts)
    detail, summary = score_results(split.results, split.facts, ctx.executor)
    writer(detail_name, detail)
    if summary_name:
        writer(summary_name, io.summary_frame(summary))
    LOGGER.info("Evaluation accuracy %s over %s questions", summary["accuracy"], summary["questions"])
    return summary


def run_metadata_recipe(
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    *,
    reader: Reader = io.read_dataset,
    writer: Writer = io.write_dataset,
) -> dict[str, Any]:
    """Fact datasets -> one row per column with role, description, profile, and restriction flag."""
    inputs = io.declared_names("in") if inputs is None else inputs
    outputs = io.declared_names("out") if outputs is None else outputs
    facts = {io.short_name(n): f for n, f in _read_all(inputs, reader).items() if not io.is_graph_frame(n, f)}
    if not facts:
        raise DataNotFoundError("Connect at least one fact dataset.")
    if not outputs:
        raise DataNotFoundError("Declare an output dataset for the dataset catalog.")
    ctx = _context(facts)
    domain = ctx.settings.default_domain
    pkg = align_with_frames(ctx.semantic.load_or_infer(domain, facts), facts)
    metadata = extract_metadata(pkg, facts)
    records = pd.DataFrame(metadata_to_records(metadata))
    writer(outputs[0], records)
    return {"ok": True, "domain": domain, "datasets": len(metadata["datasets"]), "columns": len(records)}
