from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ai4bi.config.errors import DataNotFoundError
from ai4bi.data.local_files import LocalFileSource, read_table
from ai4bi.data.preprocessing import build_catalog, drop_restricted, prepare_frames, safe_table_name
from ai4bi.utils.frames import coerce_flags, preview
from ai4bi.utils.text import extract_json, phrase_in, quote_ident, sql_literal


def test_flags_become_integers():
    frame = coerce_flags(pd.DataFrame({"f": ["yes", "no", None], "t": ["a", "b", "c"], "b": [True, False, True]}))
    assert frame["f"].tolist()[:2] == [1, 0]
    assert frame["t"].tolist() == ["a", "b", "c"]
    assert frame["b"].tolist() == [1, 0, 1]


def test_table_names_must_be_sql_safe():
    assert safe_table_name("KPI_data") == "KPI_data"
    with pytest.raises(DataNotFoundError):
        safe_table_name("my table")
    with pytest.raises(DataNotFoundError):
        prepare_frames({})


def test_restricted_columns_are_dropped_case_insensitively():
    frames = drop_restricted({"t": pd.DataFrame({"Email": ["x"], "v": [1]})}, {"email"})
    assert list(frames["t"].columns) == ["v"]


def test_catalog_lists_members_and_notes():
    frames = {"t": pd.DataFrame({"region": ["EMEA", "APAC"], "v": [1.0, 2.0]})}
    catalog = build_catalog(frames, "EMEA total", notes={"v": "Value in hours."}, aliases=[])
    assert "EMEA" in catalog.text and "Value in hours." in catalog.text
    assert catalog.profiles


def test_local_source_reads_a_domain_folder(settings):
    frames = LocalFileSource(settings.samples_root).load("service_ops", ["cases"])
    assert list(frames) == ["cases"]


def test_local_source_names_the_missing_folder(settings):
    with pytest.raises(DataNotFoundError, match="nope"):
        LocalFileSource(settings.samples_root).load("nope")


def test_read_table_formats(tmp_path: Path):
    path = tmp_path / "x.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    assert read_table(path)["b"].tolist() == [2]
    with pytest.raises(Exception):
        read_table(tmp_path / "x.unknown")


def test_preview_is_json_safe():
    out = preview(pd.DataFrame({"a": [1, None], "b": [pd.Timestamp("2026-01-01"), None]}), 1)
    assert out["n"] == 2 and len(out["rows"]) == 1


def test_text_helpers():
    assert phrase_in("What is EMEA FRT?", "emea")
    assert not phrase_in("remeasure", "emea")
    assert quote_ident("Site Name") == '"Site Name"'
    assert sql_literal("O'Brien") == "'O''Brien'"
    assert extract_json('noise {"a": 1} more') == {"a": 1}
