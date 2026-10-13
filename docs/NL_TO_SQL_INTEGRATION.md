# External NL-to-SQL integration (local)

This standalone project **does not** contain the NL-to-SQL engine.

## Recommended link

Set an environment variable to the existing engine project:

```powershell
$env:AI_BI_NL2SQL_ROOT = "C:\Users\BharadNa\dataiku-langgraph-nlq"
$env:PYTHONPATH = "$env:AI_BI_NL2SQL_ROOT\src;C:\Users\BharadNa\enterprise-ai-for-bi"
```

Then the bridge can import `nlq` from that codebase without copying it.

## Rules

- Do not rewrite NL-to-SQL inside this folder.
- Pass a semantic query plan before SQL generation (see `docs/architecture.md`).
- Query curated products only.
- Security remains independent of the LLM.
