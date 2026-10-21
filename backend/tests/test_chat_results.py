"""The chat's tools must see an analysis's RUN RESULT, which lives on the session, not in the repository definitions."""
import unittest
from types import SimpleNamespace
from unittest import mock

from app.services.chat import tools

CTX = tools.ToolContext("s1")

DEFINITION = {
    "id": "a1", "name": "Carrier Compliance Ranking", "status": "approved", "source": "predefined",
    "description": "Rank carriers.", "input_columns": ["Carrier", "In Spec"], "filters": [{"column": "Origin"}],
}
RESULT = SimpleNamespace(
    run_status="done", plan_text="Group by carrier.", result_table=[{"Carrier": "A", "Rate": 0.9}], result_columns=["Carrier", "Rate"],
    chart_type="bar", interpretation="Carrier A is best.", error=None, filters=None,
)


def _session(results):
    return SimpleNamespace(analysis_results=results)


class AnalysisResultTests(unittest.TestCase):
    def _run(self, results, tool, args):
        with mock.patch.object(tools.analysis_repository, "get_repository", return_value=[dict(DEFINITION)]), \
                mock.patch.object(tools, "get_or_404", return_value=_session(results)):
            return tools.run_tool(tool, args, CTX)

    def test_an_analysis_that_ran_shows_its_result_and_what_it_shows(self):
        out = self._run({"a1": RESULT}, "get_analysis", {"id": "a1"})
        self.assertEqual(out["run_status"], "done")
        self.assertEqual(out["what_it_shows"], "Carrier A is best.")
        self.assertEqual(out["result_rows_shown"], [{"Carrier": "A", "Rate": 0.9}])
        self.assertEqual(out["inputs"], {"columns": ["Carrier", "In Spec"], "filters": ["Origin"]})

    def test_the_overview_lists_it_as_done(self):
        with mock.patch.object(tools.analysis_repository, "get_repository", return_value=[dict(DEFINITION)]), \
                mock.patch.object(tools.feature_repository, "get_repository", return_value=[]), \
                mock.patch.object(tools, "get_or_404", return_value=SimpleNamespace(
                    analysis_results={"a1": RESULT}, issues=[], df=[], session_id="s1")):
            out = tools.run_tool("get_report_overview", {}, CTX)
        self.assertEqual(out["analyses"][0]["run_status"], "done")

    def test_an_analysis_with_no_result_is_not_run(self):
        out = self._run({}, "get_analysis", {"id": "a1"})
        self.assertEqual(out["run_status"], "not_run")
        self.assertEqual(out["result_rows_shown"], [])


if __name__ == "__main__":
    unittest.main()
