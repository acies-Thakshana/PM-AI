"""
Dataiku Scenario Step: Audit Pipeline
======================================
Paste this entire file into the Python script step of the
AuditPipeline scenario in DSS (PM_AI project).

It reads a file from the 'uploads' managed folder, runs the
same data quality checks as the PM-AI backend, and writes
audit_result.json back to the folder for the backend to fetch.
"""
import io
import json
import math
import re
import uuid

import dataiku
import numpy as np
import pandas as pd

# ── Read job parameters set by the PM-AI backend ──────────────────────────
client = dataiku.api_client()
project = client.get_default_project()
variables = project.get_variables()
local = variables.get("local", {})

SESSION_ID = local.get("audit_session_id", "")
SOURCE = local.get("audit_source", "unknown")
FILENAME = local.get("audit_filename", "upload")

if not SESSION_ID:
    raise ValueError("audit_session_id not set — trigger this scenario via the PM-AI backend, not manually.")

print(f"[AuditPipeline] session={SESSION_ID}  source={SOURCE}  file={FILENAME}")

# ── Read uploaded file from managed folder ─────────────────────────────────
folder = dataiku.Folder("uploads")
file_path = f"{SESSION_ID}/{FILENAME}"

with folder.get_download_stream(file_path) as stream:
    file_bytes = stream.read()

try:
    df = pd.read_excel(io.BytesIO(file_bytes))
except Exception:
    df = pd.read_csv(io.BytesIO(file_bytes))

print(f"[AuditPipeline] Parsed {len(df)} rows × {len(df.columns)} columns")

# ── Audit constants ────────────────────────────────────────────────────────
HIGH_NULL_THRESHOLD_PCT = 50.0
OUTLIER_IQR_MULTIPLIER = 3.0
MEASUREMENT_COL_NAMES = {"Mean Value", "Min Value", "Max Value", "Standard Deviation"}
CORE_IDENTITY_COLS = ["Product", "Origin", "Destination"]
SAMPLE_ROWS = 5
SAMPLE_COLS = 8
NS = "::"


# ── Helpers ────────────────────────────────────────────────────────────────
def _to_jsonable(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def _sample(df, mask, n=SAMPLE_ROWS):
    sub = df[mask].head(n)
    cols = list(sub.columns)[:SAMPLE_COLS]
    return [{str(c): _to_jsonable(row[c]) for c in cols} for _, row in sub.iterrows()]


def _new_id():
    return uuid.uuid4().hex[:10]


def _is_measurement_col(name):
    if name in MEASUREMENT_COL_NAMES:
        return True
    if re.search(r"(hours|days)\s*\)?\s*$", name, re.I):
        return True
    if "segment length" in name.lower():
        return True
    return False


def detect_id_column(df):
    if "Trip ID" in df.columns and not df["Trip ID"].isna().all():
        return "Trip ID"
    candidates = [c for c in df.columns if re.search(r"\bid\b", c, re.I) and not df[c].isna().all()]
    return candidates[0] if candidates else None


def _differentiator_column(df, id_col):
    for c in ("Sensor Type", "Segment Start Date Time", "Segment Name", "Actual Departure Time CET"):
        if c in df.columns and c != id_col and not df[c].isna().all():
            return c
    return None


def _iqr_bounds(series):
    s = series.dropna()
    if s.empty:
        return None
    q1, q3 = float(s.quantile(0.25)), float(s.quantile(0.75))
    iqr = q3 - q1
    if iqr == 0:
        return None
    return q1, q3, q1 - OUTLIER_IQR_MULTIPLIER * iqr, q3 + OUTLIER_IQR_MULTIPLIER * iqr


def build_outlier_chart(df, col):
    series = df[col].dropna()
    bounds = _iqr_bounds(series)
    if bounds is None:
        return None
    q1, q3, lower, upper = bounds
    values = series.astype(float)
    outlier_values = sorted(values[(values < lower) | (values > upper)].tolist())
    if not outlier_values:
        return None
    return {
        "type": "boxplot", "column": col,
        "min": float(values.min()), "max": float(values.max()),
        "q1": q1, "median": float(values.median()), "q3": q3,
        "lower_bound": lower, "upper_bound": upper,
        "outlier_values": outlier_values,
    }


# ── Detectors ──────────────────────────────────────────────────────────────
def run_audit(df):
    issues = []

    empty_cols = [c for c in df.columns if df[c].isna().all()]
    if empty_cols:
        issues.append({
            "id": _new_id(), "category": "fully_empty_columns", "severity": "warning",
            "title": "Columns with no data at all",
            "description": f"{len(empty_cols)} column(s) contain zero non-null values across all {len(df)} rows.",
            "affected_row_count": len(empty_cols), "sample": [], "selectable_items": empty_cols,
            "requires_decision": True,
            "options": [{"id": "drop_selected", "label": "Drop selected columns"}, {"id": "keep", "label": "Keep all"}],
            "chart": None,
        })

    null_pct = (df.isna().mean() * 100).round(1)
    high_null = null_pct[(null_pct >= HIGH_NULL_THRESHOLD_PCT) & (~null_pct.index.isin(empty_cols))].sort_values(ascending=False)
    if not high_null.empty:
        cols = list(high_null.index)
        listing = ", ".join(f"{c} ({v:.0f}%)" for c, v in high_null.items())
        issues.append({
            "id": _new_id(), "category": "high_null_columns", "severity": "info",
            "title": "Columns that are mostly empty",
            "description": f"{len(cols)} column(s) are at least {HIGH_NULL_THRESHOLD_PCT:.0f}% missing values: {listing}.",
            "affected_row_count": len(cols), "sample": [], "selectable_items": cols,
            "requires_decision": True,
            "options": [{"id": "drop_selected", "label": "Drop selected columns"}, {"id": "keep", "label": "Keep all"}],
            "chart": None,
        })

    constant_cols = [c for c in df.columns if df[c].nunique(dropna=True) == 1]
    if constant_cols:
        samples_str = ", ".join(f"{c} = '{df[c].dropna().iloc[0]}'" for c in constant_cols)
        issues.append({
            "id": _new_id(), "category": "constant_value_columns", "severity": "info",
            "title": "Columns with only one distinct value",
            "description": f"{len(constant_cols)} column(s) hold the same single value in every row: {samples_str}.",
            "affected_row_count": len(constant_cols), "sample": [], "selectable_items": constant_cols,
            "requires_decision": True,
            "options": [{"id": "drop_selected", "label": "Drop selected columns"}, {"id": "keep", "label": "Keep all"}],
            "chart": None,
        })

    exact_dup_mask = df.duplicated(keep="first")
    if exact_dup_mask.any():
        n = int(exact_dup_mask.sum())
        issues.append({
            "id": _new_id(), "category": "exact_duplicate_rows", "severity": "warning",
            "title": "Exact duplicate rows",
            "description": f"{n} row(s) are byte-for-byte duplicates of another row.",
            "affected_row_count": n, "sample": _sample(df, exact_dup_mask), "selectable_items": [],
            "requires_decision": True,
            "options": [{"id": "remove_duplicates", "label": "Remove the duplicate rows"}, {"id": "keep", "label": "Keep them as-is"}],
            "chart": None,
        })

    id_col = detect_id_column(df)
    diff_col = _differentiator_column(df, id_col) if id_col else None
    if id_col and diff_col:
        key_mask = df.duplicated(subset=[id_col, diff_col], keep="first")
        if key_mask.any() and not key_mask.equals(exact_dup_mask):
            n = int(key_mask.sum())
            issues.append({
                "id": _new_id(), "category": "key_duplicate_rows", "severity": "warning",
                "title": "Repeated entries for the same record",
                "description": f"{n} row(s) share the same {id_col} + {diff_col} as an earlier row but differ elsewhere.",
                "affected_row_count": n, "sample": _sample(df, key_mask), "selectable_items": [],
                "requires_decision": True,
                "options": [{"id": "remove_duplicates", "label": "Remove the repeated rows"}, {"id": "keep", "label": "Keep them as-is"}],
                "chart": None,
            })

    range_mask = pd.Series(False, index=df.index)
    range_notes = []
    if "Min Value" in df.columns and "Max Value" in df.columns:
        bad = df["Min Value"] > df["Max Value"]
        if bad.any():
            range_notes.append(f"{int(bad.sum())} row(s) where Min Value exceeds Max Value")
            range_mask |= bad
    if "Actual Departure Time CET" in df.columns and "Actual Arrival Time CET" in df.columns:
        dep = pd.to_datetime(df["Actual Departure Time CET"], errors="coerce")
        arr = pd.to_datetime(df["Actual Arrival Time CET"], errors="coerce")
        bad = (arr < dep) & dep.notna() & arr.notna()
        if bad.any():
            range_notes.append(f"{int(bad.sum())} row(s) where arrival is before departure")
            range_mask |= bad
    for c in df.columns:
        if re.search(r"(hours|days)\s*\)?\s*$", c, re.I) and pd.api.types.is_numeric_dtype(df[c]):
            bad = df[c] < 0
            if bad.any():
                range_notes.append(f"{int(bad.sum())} row(s) with negative '{c}'")
                range_mask |= bad
    if range_mask.any():
        n = int(range_mask.sum())
        issues.append({
            "id": _new_id(), "category": "range_violations", "severity": "critical",
            "title": "Logically inconsistent values",
            "description": f"{n} row(s) fail basic sanity checks: " + "; ".join(range_notes) + ".",
            "affected_row_count": n, "sample": _sample(df, range_mask), "selectable_items": [],
            "requires_decision": True,
            "options": [{"id": "remove_affected_rows", "label": "Remove these rows"}, {"id": "keep", "label": "Keep them as-is"}],
            "chart": None,
        })

    for col in df.columns:
        if not (_is_measurement_col(col) and pd.api.types.is_numeric_dtype(df[col])):
            continue
        bounds = _iqr_bounds(df[col])
        if bounds is None:
            continue
        _, _, lower, upper = bounds
        mask = (df[col] < lower) | (df[col] > upper)
        if not mask.any():
            continue
        n = int(mask.sum())
        issues.append({
            "id": _new_id(), "category": f"statistical_outliers{NS}{col}", "severity": "warning",
            "title": col,
            "description": f"{n} row(s) fall far outside the typical range for '{col}'.",
            "affected_row_count": n, "sample": _sample(df, mask), "selectable_items": [],
            "requires_decision": True,
            "options": [{"id": "remove_affected_rows", "label": "Remove the outlier rows"}, {"id": "keep", "label": "Keep them as-is"}],
            "chart": build_outlier_chart(df, col),
        })

    check_cols = ([id_col] if id_col else []) + [c for c in CORE_IDENTITY_COLS if c in df.columns]
    for col in check_cols:
        n = int(df[col].isna().sum())
        if n == 0:
            continue
        mask = df[col].isna()
        issues.append({
            "id": _new_id(), "category": f"missing_identifier{NS}{col}",
            "severity": "critical" if col == id_col else "warning",
            "title": f"Rows missing '{col}'",
            "description": f"{n} row(s) have no value in '{col}'.",
            "affected_row_count": n, "sample": _sample(df, mask), "selectable_items": [],
            "requires_decision": True,
            "options": [{"id": "drop_rows", "label": "Remove these rows"}, {"id": "keep", "label": "Keep them as-is"}],
            "chart": None,
        })

    return issues


# ── Run and write results ──────────────────────────────────────────────────
issues = run_audit(df)
print(f"[AuditPipeline] Found {len(issues)} issue(s)")

result = {
    "session_id": SESSION_ID,
    "source": SOURCE,
    "filename": FILENAME,
    "row_count": len(df),
    "column_count": len(df.columns),
    "columns": [str(c) for c in df.columns],
    "issues": issues,
}

result_bytes = json.dumps(result).encode("utf-8")
result_path = f"{SESSION_ID}/audit_result.json"
folder.upload_stream(result_path, io.BytesIO(result_bytes))
print(f"[AuditPipeline] Result written to uploads/{result_path}")
