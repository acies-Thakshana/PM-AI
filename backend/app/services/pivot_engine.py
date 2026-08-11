"""
Deterministic pivot-table engine. Pivot specs (group-by columns, metrics,
optional filters/sort/top-N) come entirely from whatever "Analysis Profile"
JSON the user uploaded (see pivot_definitions_store.py) -- there is no
bundled backend default. Every pivot is computed against the CURRENT
session dataframe passed in by the caller (post-audit, post-feature-
engineering), so group-by/metric columns can reference either raw source
columns or engineered ones (e.g. "Country of Origin", "% In Spec").

No LLM involved -- groupby/aggregation arithmetic needs to be reliable, not
a plausible-sounding guess.
"""
import pandas as pd

from app.schemas import PivotResult

MAX_GROUP_ROWS = 500  # hard ceiling so a high-cardinality group_by can't blow up the response


def _coerce_filter_value(series: pd.Series, value):
    """Numeric filters compare on the numeric-coerced series; everything
    else compares as trimmed strings so 'Road' matches 'Road ' etc."""
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().any():
        try:
            return numeric, float(value)
        except (TypeError, ValueError):
            pass
    return series.astype(str).str.strip(), str(value).strip()


def _apply_filters(df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame | None:
    working = df
    for f in filters:
        col = f["column"]
        if col not in working.columns:
            return None
        op = f["op"]
        if op == "in":
            # Multi-select slicer, e.g. "Origin is one of [these 6 growers]".
            wanted = {str(v).strip() for v in f["value"]}
            mask = working[col].astype(str).str.strip().isin(wanted)
            working = working[mask.fillna(False)]
            continue
        series, value = _coerce_filter_value(working[col], f["value"])
        if op == "eq":
            mask = series == value
        elif op == "neq":
            mask = series != value
        elif op == "gt":
            mask = series > value
        elif op == "gte":
            mask = series >= value
        elif op == "lt":
            mask = series < value
        elif op == "lte":
            mask = series <= value
        else:
            return None
        working = working[mask.fillna(False)]
    return working


def _metric_series(df: pd.DataFrame, column: str, agg: str) -> pd.Series | None:
    if column not in df.columns:
        return None
    if agg in {"sum", "mean", "min", "max", "median", "pct_of_total"}:
        return pd.to_numeric(df[column], errors="coerce")
    return df[column]  # count / distinct_count work on the raw values


def _aggregate(grouped_series: pd.core.groupby.SeriesGroupBy, agg: str) -> pd.Series:
    if agg == "sum":
        return grouped_series.sum(min_count=1)
    if agg == "mean":
        return grouped_series.mean()
    if agg == "median":
        return grouped_series.median()
    if agg == "min":
        return grouped_series.min()
    if agg == "max":
        return grouped_series.max()
    if agg == "count":
        return grouped_series.count()
    if agg == "distinct_count":
        return grouped_series.nunique()
    raise ValueError(f"Unhandled agg '{agg}' -- pct_of_total is computed separately.")


def _round_value(v):
    if isinstance(v, float):
        if pd.isna(v):
            return None
        return round(v, 2)
    if pd.isna(v) if not isinstance(v, (list, dict)) else False:
        return None
    return v


def _filter_options(df: pd.DataFrame, columns: list[str], max_values: int = 500) -> dict[str, list[str]]:
    """Distinct values for each declared filterable column, computed against
    the FULL (pre-filter) dataframe so the slicer always shows every real
    choice regardless of the pivot's own current filter state."""
    options: dict[str, list[str]] = {}
    for col in columns:
        if col not in df.columns:
            continue
        values = df[col].dropna().astype(str).str.strip().unique().tolist()
        values.sort()
        options[col] = values[:max_values]
    return options


def _filter_combinations(df: pd.DataFrame, columns: list[str], max_rows: int = 2000) -> list[dict[str, str]]:
    """Deduplicated real combinations of the filterable columns, from the
    FULL (pre-filter) dataframe -- lets the frontend narrow one slicer's
    options to whatever actually co-occurs with the other slicers' current
    selections, without a backend round-trip per checkbox click."""
    present = [c for c in columns if c in df.columns]
    if not present:
        return []
    subset = df[present].dropna(how="any")
    if subset.empty:
        return []
    subset = subset.astype(str).apply(lambda s: s.str.strip())
    subset = subset.drop_duplicates()
    return subset.head(max_rows).to_dict(orient="records")


def _compute_pivot(df: pd.DataFrame, spec: dict, runtime_filters: list[dict] | None = None) -> PivotResult | str:
    """Returns a PivotResult, or a skip-reason string on failure."""
    pivot_id, name = spec["id"], spec["name"]
    group_by = spec["group_by"]
    metrics = spec["metrics"]
    filterable_columns = spec.get("filterable_columns", [])
    filter_options = _filter_options(df, filterable_columns)
    filter_combinations = _filter_combinations(df, filterable_columns)

    missing_group_cols = [c for c in group_by if c not in df.columns]
    if missing_group_cols:
        return f"{name}: skipped -- group-by column(s) not present in the current data: {', '.join(missing_group_cols)}."

    filters = spec.get("filters", []) + (runtime_filters or [])
    working = _apply_filters(df, filters) if filters else df
    if working is None:
        bad = [f["column"] for f in filters if f["column"] not in df.columns]
        return f"{name}: skipped -- filter column(s) not present in the current data: {', '.join(bad)}."
    # An empty result after filtering (e.g. the user narrowed a slicer down
    # to nothing) is a normal, valid state to show in the UI -- not a
    # configuration error -- so it falls through to produce a zero-row
    # PivotResult rather than being reported as skipped.
    group_keys = [working[c] for c in group_by]
    metric_columns: dict[str, pd.Series] = {}

    for metric in metrics:
        column, agg, label = metric["column"], metric["agg"], metric["output_label"]
        series = _metric_series(working, column, agg)
        if series is None:
            return f"{name}: skipped -- metric column '{column}' not present in the current data."

        if agg == "pct_of_total":
            # Share of non-null ROW COUNT in this column, per group, against
            # the filtered dataset total -- this is what "% of shipments" /
            # "% of total" means in practice, and it's the only definition
            # that always sums to 100% regardless of which column is picked.
            group_counts = _aggregate(series.groupby(group_keys, dropna=False), "count")
            total_count = int(series.notna().sum())
            if not total_count:
                metric_columns[label] = group_counts * 0
            else:
                metric_columns[label] = (group_counts / total_count * 100).round(2)
        else:
            metric_columns[label] = _aggregate(series.groupby(group_keys, dropna=False), agg)

    if not metric_columns:
        return f"{name}: skipped -- no metrics could be computed."

    result_df = pd.DataFrame(metric_columns)
    result_df = result_df.reset_index()
    # groupby on a single column names the index column after that column;
    # on multiple columns it's already a MultiIndex expanded by reset_index.
    if len(group_by) == 1 and group_by[0] not in result_df.columns:
        result_df = result_df.rename(columns={result_df.columns[0]: group_by[0]})

    sort_by = spec.get("sort_by")
    if sort_by and sort_by["metric"] in result_df.columns:
        result_df = result_df.sort_values(
            sort_by["metric"], ascending=sort_by.get("direction", "desc") == "asc", na_position="last"
        )

    top_n = spec.get("top_n")
    if top_n:
        result_df = result_df.head(top_n)
    result_df = result_df.head(MAX_GROUP_ROWS)

    rows = []
    for record in result_df.to_dict(orient="records"):
        rows.append({k: _round_value(v) for k, v in record.items()})

    return PivotResult(
        id=pivot_id,
        name=name,
        description=spec["description"],
        group_by=group_by,
        metric_labels=[m["output_label"] for m in metrics],
        rows=rows,
        row_count=len(rows),
        filterable_columns=filterable_columns,
        filter_options=filter_options,
        filter_combinations=filter_combinations,
    )


def apply_pivots(
    df: pd.DataFrame, definitions: list[dict], pivot_filters: dict[str, list[dict]] | None = None
) -> tuple[list[PivotResult], list[str]]:
    """Returns (computed pivot results, notes explaining any pivots that
    were skipped). `definitions` is whatever was uploaded to the Analysis
    Profile slot plus any accepted AI suggestions / manually built pivots.
    `pivot_filters` is an optional map of pivot id -> runtime slicer filters
    (e.g. from the frontend's filter picker), applied on top of whatever
    filters that pivot's own definition already has."""
    results: list[PivotResult] = []
    skipped_notes: list[str] = []
    pivot_filters = pivot_filters or {}

    for spec in definitions:
        outcome = _compute_pivot(df, spec, runtime_filters=pivot_filters.get(spec["id"]))
        if isinstance(outcome, str):
            skipped_notes.append(outcome)
        else:
            results.append(outcome)

    return results, skipped_notes
