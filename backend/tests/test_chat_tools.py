"""The assistant's read-only tools, against a small made-up session."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd

from app.services.chat import tools
from app.services.chat.tools import ToolContext

CTX = ToolContext("s1")

ANALYSES = [
    {"id": "a1", "source": "ai_suggested", "status": "approved", "name": "Alarm rate by carrier", "description": "Alarms per carrier",
     "run_status": "done", "plan_text": "Count alarms per carrier, divide by trips.", "interpretation": "Carrier B is highest.",
     "chart_type": "bar", "result_columns": ["Carrier", "Rate"], "result_table": [{"Carrier": "A", "Rate": 0.1234567}, {"Carrier": "B", "Rate": 0.31}] ,
     "required_features": [{"name": "Hours out of range", "state": "computed"}]},
    {"id": "a2", "source": "custom", "status": "approved", "name": "Transit time by origin", "description": "d", "run_status": "not_run"},
    {"id": "a3", "source": "drilldown", "status": "approved", "name": "Drill of a1", "description": "d"},
    {"id": "a4", "source": "custom", "status": "rejected", "name": "Dropped analysis", "description": "d"},
]
FEATURES = [
    {"id": "f1", "source": "custom", "status": "approved", "name": "Hours out of range", "description": "Hours above limit",
     "output_column": "hours_out", "calculation_intent": "Sum of hours above the limit", "formula": "x", "input_columns": ["Temp"],
     "required_for_analysis": ["Alarm rate by carrier"]},
    {"id": "f2", "source": "custom", "status": "pending", "name": "Not computed yet", "description": "d", "output_column": "nope"},
]


def _session():
    df = pd.DataFrame({
        "Carrier": ["A", "B", "A", "B"],
        "Hours": [1.5, 2.5, None, 4.0],
        "Empty": [None, None, None, None],
        "One": ["x", "x", "x", "x"],
        "hours_out": [0.0, 3.0, 5.0, None],
    })
    issues = [
        SimpleNamespace(id="i1", title="Empty columns", severity="warning", status="resolved", requires_decision=True, description="d" * 400),
        SimpleNamespace(id="i2", title="Duplicates", severity="critical", status="pending", requires_decision=True, description="dup"),
    ]
    return SimpleNamespace(df=df, issues=issues, summary="Looks fine.", source="upload", filename="trips.xlsx")


class ToolsTest(unittest.TestCase):
    def setUp(self):
        patches = [
            mock.patch.object(tools.analysis_repository, "get_repository", return_value=ANALYSES),
            mock.patch.object(tools.feature_repository, "get_repository", return_value=FEATURES),
            mock.patch.object(tools, "get_or_404", return_value=_session()),
            mock.patch.object(tools.doc_store, "get", side_effect=self._doc),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    def _doc(session_id, name):
        if name == "BRIEF":
            return {"client_brief": {"final_text": "Check how our fruit shipments performed."}}
        if name == "INTERVIEW":
            return {"understanding": {"goal": "Spoilage"}, "assumptions": [{"text": "Road only"}]}
        return None

    def test_overview_lists_live_items_only(self):
        out = tools.run_tool("get_report_overview", {}, CTX)
        self.assertEqual([a["id"] for a in out["analyses"]], ["a1", "a2"])  # no drill-down, no rejected
        self.assertEqual(out["audit"], {"decisions_pending": 1, "issues": 2})
        self.assertEqual(out["rows"], 4)
        self.assertIn("fruit", out["brief"])

    def test_find_item_matches_by_name_words(self):
        out = tools.run_tool("find_item", {"query": "alarms by carrier"}, CTX)
        self.assertEqual(out["matches"][0]["id"], "a1")
        self.assertEqual(out["matches"][0]["kind"], "analysis")

    def test_find_item_finds_calculations_too_and_says_when_nothing_matches(self):
        self.assertEqual(tools.run_tool("find_item", {"query": "hours out of range"}, CTX)["matches"][0]["kind"], "calculation")
        self.assertEqual(tools.run_tool("find_item", {"query": "zzz qqq"}, CTX)["matches"], [])
        self.assertIn("error", tools.run_tool("find_item", {"query": "  "}, CTX))

    def test_get_analysis_explains_and_rounds(self):
        out = tools.run_tool("get_analysis", {"id": "a1"}, CTX)
        self.assertEqual(out["how_it_was_calculated"], "Count alarms per carrier, divide by trips.")
        self.assertEqual(out["what_it_shows"], "Carrier B is highest.")
        self.assertEqual(out["result_rows_shown"][0], {"Carrier": "A", "Rate": 0.1235})
        self.assertEqual(out["result_rows_total"], 2)
        self.assertEqual(out["needs_calculations"], [{"name": "Hours out of range", "state": "computed"}])

    def test_get_analysis_caps_the_rows_shown(self):
        big = [dict(ANALYSES[0], result_table=[{"n": i} for i in range(100)])]
        with mock.patch.object(tools.analysis_repository, "get_repository", return_value=big):
            out = tools.run_tool("get_analysis", {"id": "a1"}, CTX)
        self.assertEqual(out["result_rows_total"], 100)
        self.assertEqual(len(out["result_rows_shown"]), tools.MAX_ROWS)

    def test_an_analysis_that_has_not_run_says_so(self):
        out = tools.run_tool("get_analysis", {"id": "a2"}, CTX)
        self.assertEqual(out["run_status"], "not_run")
        self.assertEqual(out["result_rows_shown"], [])

    def test_unknown_ids_answer_with_the_known_ones(self):
        out = tools.run_tool("get_analysis", {"id": "zz"}, CTX)
        self.assertIn("error", out)
        self.assertEqual(out["known_ids"], ["a1", "a2"])

    def test_get_feature_describes_and_summarises_computed_values(self):
        out = tools.run_tool("get_feature", {"id": "f1"}, CTX)
        self.assertTrue(out["computed"])
        self.assertEqual(out["values"]["min"], 0.0)
        self.assertEqual(out["values"]["max"], 5.0)
        self.assertEqual(out["values"]["empty"], 1)
        self.assertEqual(out["needed_by_analyses"], ["Alarm rate by carrier"])

    def test_a_feature_that_is_not_computed_has_no_values(self):
        out = tools.run_tool("get_feature", {"id": "f2"}, CTX)
        self.assertFalse(out["computed"])
        self.assertNotIn("values", out)

    def test_dataset_summary_describes_the_data_as_it_is_now(self):
        out = tools.run_tool("get_dataset_summary", {}, CTX)
        self.assertEqual((out["rows"], out["columns_total"]), (4, 5))
        by_name = {c["name"]: c for c in out["columns"]}
        self.assertEqual(by_name["Hours"]["missing_pct"], 25.0)
        self.assertEqual((by_name["Hours"]["min"], by_name["Hours"]["max"]), (1.5, 4.0))
        self.assertEqual(by_name["Carrier"]["top_values"], ["A", "B"])
        stands_out = " ".join(out["things_that_stand_out"])
        self.assertIn("completely empty: Empty", stands_out)
        self.assertIn("single value: One", stands_out)

    def test_a_wide_dataset_summary_fits_the_prompt_and_keeps_the_highlights_first(self):
        import json

        wide = pd.DataFrame({f"Column {i:03d}": [f"value {i}", "x", None, "y"] for i in range(100)})
        wide["Always empty"] = None
        with mock.patch.object(tools, "get_or_404", return_value=SimpleNamespace(df=wide, issues=[], summary="", source="upload", filename="w.xlsx")):
            out = tools.run_tool("get_dataset_summary", {}, CTX)
        self.assertLess(len(json.dumps(out)), 6000)  # orchestrator.MAX_RESULT_CHARS: nothing important is cut off
        self.assertEqual(out["columns_total"], 101)
        self.assertEqual(len(out["columns"]), tools.MAX_COLUMNS)
        self.assertLessEqual(len(out["other_columns"]), tools.MAX_OTHER_COLUMN_NAMES)
        self.assertIn("Always empty", " ".join(out["things_that_stand_out"]))  # judged over every column, not just the first ones
        keys = list(out)
        self.assertLess(keys.index("things_that_stand_out"), keys.index("columns"))

    def test_audit_summary_trims_long_descriptions(self):
        out = tools.run_tool("get_audit_summary", {}, CTX)
        self.assertEqual(out["decisions_pending"], 1)
        self.assertEqual(len(out["findings"]), 2)
        self.assertLessEqual(len(out["findings"][0]["what"]), 240)

    def test_brief_includes_what_the_interview_settled(self):
        out = tools.run_tool("get_brief", {}, CTX)
        self.assertIn("fruit", out["brief"])
        self.assertEqual(out["interview"]["assumptions"], ["Road only"])

    def test_history_is_the_newest_events_only(self):
        events = [{"ts_event": f"2026-10-21T10:00:{i:02d}#x", "event_type": "analysis_added", "result": "ok", "summary": f"event {i}"} for i in range(40)]
        with mock.patch.object(tools.audit_log, "events_for_session", return_value=events):
            out = tools.run_tool("get_history", {}, CTX)
        self.assertEqual(len(out["events"]), tools.MAX_EVENTS)
        self.assertEqual(out["events"][-1]["summary"], "event 39")

    def test_known_items_names_the_kind_of_every_live_entry(self):
        self.assertEqual(tools.known_items("s1"), {"f1": "feature", "f2": "feature", "a1": "analysis", "a2": "analysis"})


class RunToolTest(unittest.TestCase):
    def test_an_unknown_tool_answers_with_the_list(self):
        out = tools.run_tool("drop_table", {}, CTX)
        self.assertIn("Unknown tool", out["error"])
        self.assertIn("get_analysis", out["tools"])

    def test_wrong_arguments_are_reported_not_raised(self):
        out = tools.run_tool("get_analysis", {"wrong": 1}, CTX)
        self.assertIn("Wrong arguments", out["error"])

    def test_a_tool_that_fails_answers_with_an_error(self):
        with mock.patch.object(tools, "get_or_404", side_effect=RuntimeError("boom")):
            out = tools.run_tool("get_dataset_summary", {}, CTX)
        self.assertIn("boom", out["error"])

    def test_the_session_cannot_be_chosen_by_the_model(self):
        # An argument named session_id is not accepted: the session is fixed by the server.
        self.assertIn("Wrong arguments", tools.run_tool("get_dataset_summary", {"session_id": "other"}, CTX)["error"])

    def test_every_tool_is_described_for_the_model(self):
        text = tools.describe_tools()
        for name in tools.TOOLS:
            self.assertIn(name, text)

    def test_no_tool_writes(self):
        # Read-only by construction: the module imports no writer from the repositories or stores.
        source = Path(tools.__file__).read_text(encoding="utf-8")
        for writer in ("add_custom_entry", "doc_store.put", "save_frame", ".put(", "accept_entry", "reject_entry"):
            self.assertNotIn(writer, source)


if __name__ == "__main__":
    unittest.main()
