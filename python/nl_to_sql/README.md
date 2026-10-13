# python/nl_to_sql — integration boundary

This package is a **bridge** to the existing NL-to-SQL implementation in `src/nlq/`.

## Contract (design)

1. Upstream orchestration builds a `semantic_query_plan.v1` (see `docs/architecture.md`).
2. A future adapter maps that plan into the existing entrypoints.
3. Today, `bridge.ask` / `bridge.ask_debug` call the current engine without changing SQL logic.

## Do not

- Duplicate LangGraph nodes
- Bypass SQL validation / security
- Query raw tables
- Invent KPI formulas

## Entrypoints (bridged)

| Bridge symbol | Existing implementation |
|---|---|
| `ask` | `nlq.notebook_runner.ask_nlq` |
| `ask_debug` | `nlq.notebook_runner.ask_nlq_debug` |
| `run_nlq` | `nlq.graph.runner.run_nlq` |
| `NLQRunner` | `nlq.graph.runner.NLQRunner` |
