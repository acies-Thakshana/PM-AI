# data/ — local curated fixtures

Put **curated / approved** local datasets here for laptop hosting (CSV, parquet, SQLite, etc.).

Rules:

- Do not treat raw source extracts as NLQ-queryable.
- Prefer names that match semantic `physical_dataset` placeholders once certified.
- Large binaries should stay gitignored; document the expected filename in PRs.

Example (not committed unless approved):

```text
data/
  curated_cases.parquet
  KPI_data.parquet          # only if this is the certified local fixture
```
