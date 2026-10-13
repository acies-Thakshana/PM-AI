# local_data/ — optional host mounts

Use this folder for machine-local mounts that should not clutter `data/`:

- Copies of certified parquet extracts
- Local DuckDB / SQLite files
- Cache directories

Keep secrets out of this folder. Point `config/settings.yaml` or env vars at paths under `local_data/` when needed.

Example:

```text
local_data/
  fixtures/
    <CURATED_PRIMARY_FACT_DATASET>.parquet
  cache/
```
