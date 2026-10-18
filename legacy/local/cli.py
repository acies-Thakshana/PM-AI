"""Command line for local runs: ``python -m local <command>``.

Commands
  ask "question"        answer one question against storage/samples/<domain>
  batch QUESTIONS.csv   answer a question table, write a results CSV
  evaluate RESULTS.csv  execution-accuracy scoring of a results CSV
  refresh-metadata      write storage/metadata/<domain>/dataset_catalog.json
  validate              check config, data, chart bindings, and validated SQL
  graph-stats           show the stored knowledge graph (seed it with --seed)
  domains               list configured domains
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

import local  # noqa: F401  puts lib/python on sys.path

import pandas as pd

from ai4bi.config import ConfigError, DataNotFoundError, DomainNotFoundError, load_settings
from ai4bi.data.local_files import read_table
from ai4bi.data.preprocessing import prepare_frames
from ai4bi.evaluation.scoring import score_results
from ai4bi.knowledge.documents import ingest_documents
from ai4bi.knowledge.seed import seed_from_package
from ai4bi.metadata.extractor import extract_metadata
from ai4bi.pipeline import ask, build_context, run_batch
from ai4bi.pipeline.checks import check_domain
from ai4bi.semantic.loader import align_with_frames
from ai4bi.semantic.onboarding import onboard_domain
from ai4bi.semantic.registry import JsonSemanticRegistryStore

EXIT_OK, EXIT_FAILED, EXIT_CONFIG = 0, 1, 2


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


def _print_answer(result: dict[str, Any]) -> None:
    print(f"Status:   {result['status']}")
    print(f"Answer:   {result['answer']}")
    if result.get("sql_query"):
        print(f"SQL:      {result['sql_query']}")
    table = result.get("table") or {}
    if table.get("rows"):
        print(f"Rows:     {table.get('n')} (showing {len(table['rows'])})")
        print(pd.DataFrame(table["rows"], columns=table.get("columns")).to_string(index=False))
    chart = result.get("chart") or {}
    if chart:
        print(f"Chart:    {chart.get('template')} ({chart.get('chart_type')})")
    for item in result.get("follow_up_questions") or []:
        print(f"Follow-up: {item}")
    if result.get("warnings"):
        print(f"Warnings: {', '.join(result['warnings'])}")


def _learned_semantics(ctx, domain: str):
    registry = JsonSemanticRegistryStore(ctx.settings.semantic_registry_root).load(domain)
    if not registry.artifacts:
        return None, None
    base = ctx.semantic.load(domain) if ctx.semantic.exists(domain) else None
    names = [e.physical_dataset for e in base.entities] if base else None
    frames = ctx.data.load(domain, names)
    package = ctx.semantic.load_with_registry(
        domain, frames, registry, include_drafts=ctx.settings.include_drafts
    )
    return frames, package


def _cmd_ask(args: argparse.Namespace) -> int:
    ctx = build_context(history=not args.no_persist)
    domain = args.domain or ctx.settings.default_domain
    frames, package = _learned_semantics(ctx, domain)
    result = ask(
        args.question,
        context=ctx,
        domain=domain,
        session_id=args.session,
        persist=not args.no_persist,
        frames=frames,
        semantic_package=package,
    )
    _print_json(result) if args.json else _print_answer(result)
    return EXIT_OK if result["status"] != "error" else EXIT_FAILED


def _cmd_batch(args: argparse.Namespace) -> int:
    ctx = build_context(history=False)
    domain = args.domain or ctx.settings.default_domain
    questions = read_table(args.questions)
    frames, package = _learned_semantics(ctx, domain)
    results, graph = run_batch(
        questions, context=ctx, domain=domain, frames=frames, semantic_package=package
    )
    output = Path(args.output or Path(args.questions).with_name(Path(args.questions).stem + "_results.csv"))
    results.to_csv(output, index=False)
    if not args.no_persist:
        ctx.graphs.save(graph)
    print(f"Wrote {len(results)} rows to {output}")
    print(results["status"].value_counts().to_string())
    return EXIT_OK


def _cmd_evaluate(args: argparse.Namespace) -> int:
    ctx = build_context(history=False)
    domain = args.domain or ctx.settings.default_domain
    pkg = ctx.semantic.load(domain)
    frames = prepare_frames(ctx.data.load(domain, [e.physical_dataset for e in pkg.entities]))
    detail, summary = score_results(read_table(args.results), frames, ctx.executor)
    output = Path(args.output or Path(args.results).with_name(Path(args.results).stem + "_metrics.csv"))
    detail.to_csv(output, index=False)
    _print_json(summary)
    print(f"Wrote {output}")
    return EXIT_OK


def _cmd_refresh_metadata(args: argparse.Namespace) -> int:
    ctx = build_context(history=False)
    domain = args.domain or ctx.settings.default_domain
    pkg = ctx.semantic.load(domain)
    frames = ctx.data.load(domain, [e.physical_dataset for e in pkg.entities])
    metadata = extract_metadata(align_with_frames(pkg, frames), frames)
    path = ctx.metadata.save(metadata)
    print(f"Wrote {path} ({len(metadata['datasets'])} datasets)")
    return EXIT_OK


def _cmd_onboard(args: argparse.Namespace) -> int:
    ctx = build_context(history=False)
    domain = args.domain or ctx.settings.default_domain
    base = ctx.semantic.load(domain) if ctx.semantic.exists(domain) else None
    names = [e.physical_dataset for e in base.entities] if base else None
    frames = ctx.data.load(domain, names)
    store = JsonSemanticRegistryStore(ctx.settings.semantic_registry_root)
    result = onboard_domain(
        domain,
        frames,
        llm=ctx.llm,
        settings=ctx.settings,
        registry=store.load(domain),
        base_package=base,
        force=args.force,
    )
    registry_path = store.save(domain, result.registry)
    metadata_path = ctx.metadata.save(result.metadata)
    graph = ctx.graphs.load(domain)
    seed_from_package(graph, result.package)
    graph_path = ctx.graphs.save(graph)
    print(
        f"{'Updated' if result.changed else 'Unchanged'} semantic version {result.semantic_version}; "
        f"registry={registry_path}; metadata={metadata_path}; graph={graph_path}"
    )
    for row in result.audit:
        print(f"  {'ACTIVE' if row['active'] else 'DRAFT'} {row['artifact_type']} {row['artifact_id']}: {row['detail']}")
    return EXIT_OK


def _cmd_validate(args: argparse.Namespace) -> int:
    ctx = build_context(history=False)
    domains = [args.domain] if args.domain else ctx.semantic.list_domains()
    failed = False
    for domain in domains:
        print(f"[{domain}]")
        for check in check_domain(ctx, domain):
            failed |= not check.ok
            print(f"  {'PASS' if check.ok else 'FAIL'}  {check.name}: {check.detail}")
    return EXIT_FAILED if failed else EXIT_OK


def _cmd_graph_stats(args: argparse.Namespace) -> int:
    ctx = build_context(history=False)
    domain = args.domain or ctx.settings.default_domain
    graph = ctx.graphs.load(domain)
    if args.seed:
        pkg = ctx.semantic.load(domain)
        seed_from_package(graph, pkg)
        added = ingest_documents(graph, ctx.semantic.domain_dir(domain) / "documents")
        path = ctx.graphs.save(graph)
        print(f"Seeded {path} ({added} document facts)")
    kinds: dict[str, int] = {}
    for node in graph.nodes.values():
        kinds[node.get("kind", "?")] = kinds.get(node.get("kind", "?"), 0) + 1
    _print_json({"domain": domain, **graph.stats(), "node_kinds": dict(sorted(kinds.items()))})
    return EXIT_OK


def _cmd_domains(args: argparse.Namespace) -> int:
    ctx = build_context(history=False, configure_logging=False)
    for domain in ctx.semantic.list_domains():
        print(domain)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m local", description="AI4BI local runner")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ask", help="answer one question")
    p.add_argument("question")
    p.add_argument("--domain")
    p.add_argument("--session", help="session id for follow-up context")
    p.add_argument("--json", action="store_true", help="print the full response")
    p.add_argument("--no-persist", action="store_true", help="do not update the graph or history")
    p.set_defaults(func=_cmd_ask)

    p = sub.add_parser("batch", help="answer a question table")
    p.add_argument("questions", help="CSV, Excel, or Parquet with column input_question")
    p.add_argument("--domain")
    p.add_argument("--output")
    p.add_argument("--no-persist", action="store_true", help="do not save the updated graph")
    p.set_defaults(func=_cmd_batch)

    p = sub.add_parser("evaluate", help="score a results table")
    p.add_argument("results", help="results file with Expected_SQL_Query and LLM_generated_SQL")
    p.add_argument("--domain")
    p.add_argument("--output")
    p.set_defaults(func=_cmd_evaluate)

    p = sub.add_parser("refresh-metadata", help="write the dataset catalog JSON")
    p.add_argument("--domain")
    p.set_defaults(func=_cmd_refresh_metadata)

    p = sub.add_parser("onboard", help="learn and persist semantics from connected local datasets")
    p.add_argument("--domain")
    p.add_argument("--force", action="store_true", help="create a new version even when the schema is unchanged")
    p.set_defaults(func=_cmd_onboard)

    p = sub.add_parser("validate", help="check configuration, data, and validated SQL")
    p.add_argument("--domain")
    p.set_defaults(func=_cmd_validate)

    p = sub.add_parser("graph-stats", help="show the stored knowledge graph")
    p.add_argument("--domain")
    p.add_argument("--seed", action="store_true", help="seed from the semantic package and documents")
    p.set_defaults(func=_cmd_graph_stats)

    p = sub.add_parser("domains", help="list configured domains")
    p.set_defaults(func=_cmd_domains)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (ConfigError, DomainNotFoundError, DataNotFoundError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())
