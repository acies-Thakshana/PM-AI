"""
Feature engineering by reusable, JSON-driven templates. Each entry in
`_APPLIERS` is a template for one calculation shape (lookup, month
extraction, ratio, duration, custom formula); a feature spec is just JSON
that fills in that template's inputs (source/target columns, mappings,
formula text, ...) -- see feature_definitions_store.py for where that JSON
comes from. Adding a new feature of an already-supported type only
requires editing/re-uploading the JSON, no code change.

Every feature is computed against the dataframe passed in by the caller,
which is always the CURRENT audited session dataframe (see routers/audit.py)
-- this module never reads the original uploaded file. If a feature's source
column was removed during the audit's HITL review, that feature is skipped
(and reported as skipped) rather than silently recomputed from data the user
already chose to drop.

The templates above are deterministic -- no LLM involved, since
lookup/date-extraction/ratio arithmetic needs to be reliable, not a
plausible-sounding guess. The one exception is the "ai_generated" type: a
fallback for when a requested calculation doesn't fit any existing
template, where an LLM writes the pandas code itself (see
ai_feature_generator.py) and it runs through a restricted sandbox (see
ai_code_executor.py) rather than being trusted outright.
"""
import re

import pandas as pd

from app.schemas import FeatureResult
from app.services import ai_code_executor

TOP_N_DISTRIBUTION = 12

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _numeric_stats(series: pd.Series) -> dict[str, float]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return {}
    return {
        "mean": round(float(clean.mean()), 1),
        "median": round(float(clean.median()), 1),
        "min": round(float(clean.min()), 1),
        "max": round(float(clean.max()), 1),
    }


def _distribution(series: pd.Series, top_n: int = TOP_N_DISTRIBUTION) -> dict[str, int]:
    counts = series.dropna().astype(str).value_counts().head(top_n)
    return {str(k): int(v) for k, v in counts.items()}


def _apply_lookup(df: pd.DataFrame, spec: dict) -> pd.Series | None:
    source = spec["source_column"]
    if source not in df.columns:
        return None
    mapping = spec.get("mapping", {})
    default = spec.get("default_value", "Unknown")
    return df[source].map(lambda v: mapping.get(str(v).strip(), default) if pd.notna(v) else None)


def _apply_extract_month(df: pd.DataFrame, spec: dict) -> pd.Series | None:
    """Returns calendar month NAMES (January-December) as an ordered
    Categorical, not month numbers -- so charts/tables read as "March" while
    sorting (see pivot_engine's `observed=True` groupby) still follows
    calendar order rather than alphabetical."""
    candidates = [c for c in spec["source_columns"] if c in df.columns]
    if not candidates:
        return None
    combined = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    for c in candidates:
        parsed = pd.to_datetime(df[c], errors="coerce")
        combined = combined.fillna(parsed)
    month_names = combined.dt.month.map(lambda m: MONTH_NAMES[int(m) - 1] if pd.notna(m) else pd.NA)
    return pd.Series(pd.Categorical(month_names, categories=MONTH_NAMES, ordered=True), index=df.index)


def _apply_duration_hours(df: pd.DataFrame, spec: dict) -> pd.Series | None:
    start_col, end_col = spec["start_column"], spec["end_column"]
    if start_col not in df.columns or end_col not in df.columns:
        return None
    start = pd.to_datetime(df[start_col], errors="coerce")
    end = pd.to_datetime(df[end_col], errors="coerce")
    hours = (end - start).dt.total_seconds() / 3600
    if spec.get("unit") == "days":
        hours = hours / 24
    return hours.round(2)


def _apply_ratio(df: pd.DataFrame, spec: dict) -> pd.Series | None:
    # require every denominator column to be present -- a partial sum would
    # silently misrepresent the ratio, which is worse than not computing it
    if set(spec["denominator_columns"]) - set(df.columns):
        return None
    if set(spec["numerator_columns"]) - set(df.columns):
        return None
    numerator = df[spec["numerator_columns"]].sum(axis=1, skipna=False)
    denominator = df[spec["denominator_columns"]].sum(axis=1, skipna=False)
    pct = (numerator / denominator) * 100
    return pct.where(denominator != 0).round(1)


def _autoquote_columns(formula: str, columns: list[str]) -> str:
    """Wraps a bare column name in backticks (pandas' own eval() syntax for
    an identifier with spaces/special characters) so a hand-typed formula
    doesn't require the user to know that syntax themselves -- longest names
    first so e.g. "Time Below Ideal Hours" isn't half-matched by a shorter
    "Time Below" column. Skips names already backtick-quoted or that are
    already valid bare identifiers."""
    for col in sorted(columns, key=len, reverse=True):
        if col.isidentifier():
            continue
        pattern = re.escape(col)
        formula = re.sub(rf"(?<!`){pattern}(?!`)", f"`{col}`", formula)
    return formula


def _apply_custom_formula(df: pd.DataFrame, spec: dict) -> pd.Series | None:
    """Evaluates a user-authored arithmetic formula referencing column names
    via pandas' own eval() -- a restricted expression grammar (arithmetic/
    comparison only; no function calls, imports, or attribute access), not a
    general Python eval, so a hand-typed formula can't run arbitrary code."""
    formula = (spec.get("formula") or "").strip()
    if not formula:
        return None
    try:
        result = df.eval(_autoquote_columns(formula, list(df.columns)), engine="python")
    except Exception:
        return None
    if not isinstance(result, pd.Series):
        return None
    return pd.to_numeric(result, errors="coerce")


def _apply_ai_generated(df: pd.DataFrame, spec: dict) -> pd.Series | None:
    """Fallback for a calculation that doesn't fit any template above.
    Groq writes pandas code for it once; that code is cached onto `spec`
    (the same dict object the store/session extra_features list holds) so
    re-applying features later in the session replays the cached code
    instead of calling the LLM again. On any failure -- unavailable LLM,
    unsafe/malformed code, a runtime error against this particular data --
    the reason is stashed on `spec["_ai_error"]` for apply_features() to
    surface as a skip note, since "a required column is missing" (the
    generic skip message below) wouldn't be accurate here."""
    cached_code = spec.get("generated_code")
    if cached_code:
        try:
            return ai_code_executor.run_generated_code(cached_code, df)
        except Exception as exc:
            spec["_ai_error"] = str(exc)
            return None

    from app.services import ai_feature_generator  # lazy: avoid requiring GROQ_API_KEY unless this type is actually used

    try:
        code = ai_feature_generator.generate_code(spec, df)
        values = ai_code_executor.run_generated_code(code, df)
    except Exception as exc:
        spec["_ai_error"] = f"AI-generated calculation failed: {exc}"
        return None

    spec["generated_code"] = code
    return values


_APPLIERS = {
    "lookup": _apply_lookup,
    "extract_month": _apply_extract_month,
    "ratio": _apply_ratio,
    "duration_hours": _apply_duration_hours,
    "custom_formula": _apply_custom_formula,
    "ai_generated": _apply_ai_generated,
}


def apply_features(df: pd.DataFrame, definitions: list[dict]) -> tuple[pd.DataFrame, list[FeatureResult], list[str]]:
    """Returns (df with feature columns appended, computed feature results,
    notes explaining any features that were skipped). `definitions` is
    whatever was uploaded to the Customer KPI Profile slot -- the caller is
    responsible for making sure that actually happened."""
    working = df.copy()
    results: list[FeatureResult] = []
    skipped_notes: list[str] = []

    for spec in definitions:
        applier = _APPLIERS.get(spec["type"])
        if applier is None:
            skipped_notes.append(f"{spec['name']}: unknown feature type '{spec['type']}'.")
            continue

        values = applier(working, spec)
        if values is None:
            if spec["type"] == "ai_generated" and spec.get("_ai_error"):
                skipped_notes.append(f"{spec['name']}: {spec['_ai_error']}")
            else:
                skipped_notes.append(
                    f"{spec['name']}: skipped -- a required source column isn't present in the "
                    f"current data (likely removed during the audit review), or its formula couldn't be evaluated."
                )
            continue

        output_col = spec["output_column"]
        working[output_col] = values
        non_null = int(values.notna().sum())
        summary = spec.get("summary", "distribution")

        results.append(FeatureResult(
            id=spec["id"], name=spec["name"], description=spec["description"],
            output_column=output_col, non_null_count=non_null, null_count=len(values) - non_null,
            distribution=_distribution(values) if summary == "distribution" else {},
            stats=_numeric_stats(values) if summary == "stats" else {},
            generated_code=spec.get("generated_code") if spec["type"] == "ai_generated" else None,
        ))

    return working, results, skipped_notes
