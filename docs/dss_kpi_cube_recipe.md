# Test the project in Dataiku

The Project Library is only the engine. You still create one Python recipe
in the Flow and paste `dataiku/recipes/aibi_batch_ask_recipe.py`.

## Flow

```
KPI_data ─────────────────┐
                          ├── Python recipe
kpi_cube_validation ──────┘
   input_question
   Expected_SQL_Query
        │
        ▼
kpi_cube_validation_llm_results
   question
   Expected_SQL_Query
   LLM_generated_SQL
   LLM_generated_answer
```

## How to test

1. Confirm Library contains `aibi/ask_service.py` under
   `lib/https:/github.com/.../enterprise-ai-for-bi-...`.
2. Code environment: `pandas`, `pyyaml`, `pydantic`, `pyarrow`.
3. Datasets exist: `KPI_dataset`, `kpi_cube_validation`, output dataset.
4. `kpi_cube_validation` has `input_question` and `Expected_SQL_Query`.
5. New Python recipe → 2 inputs + 1 output → paste the recipe file → Run.
6. Open `kpi_cube_validation_llm_results` and compare
   `Expected_SQL_Query` vs `LLM_generated_SQL`.

If import fails, set project variable `AIBI_PROJECT_ROOT` to the folder
that **contains** the `aibi` directory (the `enterprise-ai-for-bi-...` folder).
