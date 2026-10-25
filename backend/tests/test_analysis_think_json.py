"""Regression for "analysis_agent.think -> JSONDecodeError: Extra data": the model answered with the plan JSON and
then more content (a second object or a closing note). The plan must still be read, from the first JSON value.

Only the network call is replaced: the answer goes through the real chat_json and the shared JSON reader."""
import json
import unittest
from unittest import mock

from app.services.analysis import analysis_agent
from app.services.common import llm
from app.services.features import feature_agent

ENTRY = {"name": "Carrier ranking", "description": "d", "calculation_intent": "rank carriers", "input_columns": ["Carrier"]}
PLAN = {"steps": ["Group the trips by carrier.", "Count the trips."], "columns_used": ["Carrier"]}


def think_with(model_text: str) -> dict:
    with mock.patch.object(llm, "_converse", return_value=(model_text, "end_turn")):
        return analysis_agent.think(ENTRY, "COLUMNS")


class ThinkReadsTheFirstJsonValueTest(unittest.TestCase):
    def test_a_clean_answer_is_read(self):
        out = think_with(json.dumps(PLAN))
        self.assertEqual(out["steps"], PLAN["steps"])
        self.assertIn("1. Group the trips by carrier.", out["plan"])

    def test_a_second_object_after_the_plan_does_not_break_it(self):
        out = think_with(json.dumps(PLAN) + "\n" + json.dumps({"alternative": "ignored"}))
        self.assertEqual(out["steps"], PLAN["steps"])
        self.assertNotIn("alternative", out)

    def test_a_closing_note_after_the_plan_does_not_break_it(self):
        out = think_with(json.dumps(PLAN, indent=2) + "\n\nNote: I used {Carrier} as the key.")
        self.assertEqual(out["steps"], PLAN["steps"])

    def test_a_sentence_before_the_plan_does_not_break_it(self):
        out = think_with("Here is the plan:\n```json\n" + json.dumps(PLAN) + "\n```\nHope this helps.")
        self.assertEqual(out["steps"], PLAN["steps"])


class OneSharedJsonReaderTest(unittest.TestCase):
    """The agents used to carry weaker private copies of the reader; they all use the shared one now."""

    def test_the_analysis_and_feature_agents_use_the_shared_reader(self):
        self.assertIs(analysis_agent.strip_json_fence, llm.strip_json_fence)
        self.assertIs(feature_agent._strip_json_fence, llm.strip_json_fence)

    def test_the_feature_agent_reads_a_plan_followed_by_more_content(self):
        text = json.dumps({"steps": ["a"], "columns_used": []}) + '\n{"x": 1}'
        with mock.patch.object(llm, "_converse", return_value=(text, "end_turn")):
            out = feature_agent.think({"name": "n", "description": "d", "calculation_intent": "c", "output_column": "o", "input_columns": []}, "COLUMNS")
        self.assertEqual(out["steps"], ["a"])


if __name__ == "__main__":
    unittest.main()
