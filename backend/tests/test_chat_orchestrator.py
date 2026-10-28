"""The bounded tool loop and the figure check, with a scripted stand-in for the model."""
import json
import unittest
from unittest import mock

from app.services.chat import orchestrator
from app.services.chat.tools import ToolContext
from app.services.common import audit_log

CTX = ToolContext("s1")

_log_patch = mock.patch.object(audit_log, "log_event")


def setUpModule():
    """The loop logs the tools it runs: these tests must not write to the real audit log."""
    _log_patch.start()


def tearDownModule():
    _log_patch.stop()


class FakeModel:
    """Answers from a script (one JSON object, or raw text, per call) and remembers every prompt it was given."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts: list[str] = []

    def __call__(self, system, user):
        self.prompts.append(user)
        answer = self.answers.pop(0) if self.answers else self.answers_last
        self.answers_last = answer
        return answer if isinstance(answer, str) else json.dumps(answer)


def calls(*names):
    return {"tool_calls": [{"name": n, "args": {}} for n in names]}


def final(reply="Done.", **extra):
    return {"reply": reply, **extra}


class RunTurnTest(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(orchestrator.tools, "run_tool", side_effect=lambda name, args, ctx: {"tool": name, "value": 42})
        self.run_tool = patch.start()
        self.addCleanup(patch.stop)

    def test_an_answer_without_tool_calls_ends_the_turn(self):
        model = FakeModel(final("Hi."))
        result = orchestrator.run_turn("S", "U", model, CTX)
        self.assertEqual(result.raw["reply"], "Hi.")
        self.assertEqual(result.tools_used, [])
        self.assertEqual(len(model.prompts), 1)

    def test_tool_results_are_shown_to_the_model_and_it_answers(self):
        model = FakeModel(calls("get_dataset_summary"), final("There are 42 rows."))
        result = orchestrator.run_turn("S", "U", model, CTX)
        self.assertEqual(result.raw["reply"], "There are 42 rows.")
        self.assertEqual(result.tools_used, ["get_dataset_summary"])
        self.assertIn("TOOL RESULTS (round 1)", model.prompts[1])
        self.assertIn('"value": 42', model.prompts[1])
        self.assertIn('"value": 42', result.evidence)

    def test_the_items_read_successfully_are_remembered(self):
        def tool(name, args, ctx):
            return {"error": "No analysis has that id."} if args.get("id") == "bad" else {"id": args["id"], "name": "n"}

        self.run_tool.side_effect = tool
        calls_ = [{"name": "get_analysis", "args": {"id": "a1"}}, {"name": "get_analysis", "args": {"id": "bad"}},
                  {"name": "get_feature", "args": {"id": "f1"}}, {"name": "find_item", "args": {"id": "x"}}]
        result = orchestrator.run_turn("S", "U", FakeModel({"tool_calls": calls_[:3]}, final()), CTX)
        self.assertEqual(result.looked_at, [("analysis", "a1"), ("feature", "f1")])

    def test_the_session_comes_from_the_server_not_the_model(self):
        model = FakeModel({"tool_calls": [{"name": "get_analysis", "args": {"id": "a1", "session_id": "someone-else"}}]}, final())
        orchestrator.run_turn("S", "U", model, CTX)
        self.assertIs(self.run_tool.call_args.args[2], CTX)

    def test_without_a_session_there_are_no_tools(self):
        model = FakeModel(calls("get_dataset_summary"))
        result = orchestrator.run_turn("S", "U", model, None)
        self.assertEqual(result.tools_used, [])
        self.assertEqual(len(model.prompts), 1)
        self.run_tool.assert_not_called()

    def test_at_most_three_calls_per_round(self):
        model = FakeModel(calls("a", "b", "c", "d", "e"), final())
        result = orchestrator.run_turn("S", "U", model, CTX)
        self.assertEqual(result.tools_used, ["a", "b", "c"])

    def test_at_most_six_calls_per_turn_then_the_model_must_answer(self):
        model = FakeModel(calls("a", "b", "c"), calls("d", "e", "f"), calls("g", "h", "i"))
        result = orchestrator.run_turn("S", "U", model, CTX)
        self.assertEqual(len(result.tools_used), orchestrator.MAX_CALLS_TOTAL)
        self.assertIn("answer now", model.prompts[-1])

    def test_at_most_four_rounds_then_the_model_must_answer(self):
        model = FakeModel(*[calls("a")] * 10)
        result = orchestrator.run_turn("S", "U", model, CTX)
        self.assertEqual(len(result.tools_used), orchestrator.MAX_ROUNDS)
        self.assertEqual(len(model.prompts), orchestrator.MAX_ROUNDS + 1)
        self.assertIn("answer now", model.prompts[-1])

    def test_the_time_budget_stops_further_rounds(self):
        ticks = iter([0.0, 0.0, 100.0, 100.0, 100.0])
        model = FakeModel(calls("a"), calls("b"), final("Late."))
        result = orchestrator.run_turn("S", "U", model, CTX, clock=lambda: next(ticks))
        self.assertEqual(result.tools_used, ["a"])
        self.assertIn("answer now", model.prompts[-1])

    def test_a_long_tool_result_is_cut(self):
        self.run_tool.side_effect = lambda name, args, ctx: {"blob": "x" * 50000}
        model = FakeModel(calls("a"), final())
        orchestrator.run_turn("S", "U", model, CTX)
        self.assertLess(len(model.prompts[1]), len("U") + orchestrator.MAX_RESULT_CHARS + 600)
        self.assertIn("cut: too long", model.prompts[1])

    def test_malformed_tool_calls_are_ignored(self):
        model = FakeModel({"tool_calls": ["get_analysis", {"args": {}}, {"name": 5}], "reply": "Plain."})
        result = orchestrator.run_turn("S", "U", model, CTX)
        self.assertEqual(result.raw["reply"], "Plain.")
        self.assertEqual(result.tools_used, [])

    def test_a_tool_error_goes_back_to_the_model_and_the_turn_continues(self):
        self.run_tool.side_effect = lambda name, args, ctx: {"error": "No analysis has that id."}
        model = FakeModel(calls("get_analysis"), final("I could not find it."))
        result = orchestrator.run_turn("S", "U", model, CTX)
        self.assertEqual(result.raw["reply"], "I could not find it.")
        self.assertIn("No analysis has that id", model.prompts[1])

    def test_one_answer_that_is_not_json_is_retried_once(self):
        model = FakeModel("here you go, no json", final("Fine."))
        result = orchestrator.run_turn("S", "U", model, CTX)
        self.assertEqual(result.raw["reply"], "Fine.")
        self.assertIn("not valid JSON", model.prompts[1])

    def test_two_answers_that_are_not_json_fail_the_turn(self):
        with self.assertRaises(ValueError):
            orchestrator.run_turn("S", "U", FakeModel("nope", "still nope"), CTX)

    def test_an_answer_that_is_not_an_object_counts_as_not_json(self):
        with self.assertRaises(ValueError):
            orchestrator.run_turn("S", "U", FakeModel("[1, 2]", "[3]"), CTX)


class PromiseTest(unittest.TestCase):
    """A reply that is only "I'll look that up" must not end the turn: the lookup it promised has to happen."""

    def test_only_a_short_reply_that_starts_with_a_promise_counts(self):
        for promise in ("I'll look up that analysis.", "Sure, let me check that for you.", "Okay! I will look into it", "Let me find it."):
            self.assertTrue(orchestrator.promises_lookup(promise), promise)
        for fine in (
            "Let me know if you want me to check more.",
            "I'll add that analysis for you.",
            "Carrier A is best. Let me know if you want me to check more.",
            "I'll get started.",
            "x" * 200,
            "",
        ):
            self.assertFalse(orchestrator.promises_lookup(fine), fine)

    def setUp(self):
        patch = mock.patch.object(orchestrator.tools, "run_tool", side_effect=lambda name, args, ctx: {"tool": name, "value": 42})
        self.run_tool = patch.start()
        self.addCleanup(patch.stop)

    def test_a_promise_gets_one_nudge_and_the_lookup_is_then_done(self):
        model = FakeModel(final("I'll look up that analysis."), calls("find_item"), final("It shows 42."))
        result = orchestrator.run_turn("S", "U", model, CTX)
        self.assertEqual(result.tools_used, ["find_item"])
        self.assertEqual(result.raw["reply"], "It shows 42.")
        self.assertIn("called no tool", model.prompts[1])

    def test_a_promise_can_also_be_answered_from_what_the_model_has(self):
        model = FakeModel(final("I'll check that."), final("Carrier B is the slowest."))
        result = orchestrator.run_turn("S", "U", model, CTX)
        self.assertEqual(result.raw["reply"], "Carrier B is the slowest.")
        self.assertEqual(result.tools_used, [])

    def test_a_second_promise_is_passed_on_not_nudged_again(self):
        model = FakeModel(final("I'll look it up."), final("Let me check."))
        result = orchestrator.run_turn("S", "U", model, CTX)
        self.assertEqual(len(model.prompts), 2)
        self.assertEqual(result.raw["reply"], "Let me check.")

    def test_a_normal_answer_is_never_nudged(self):
        model = FakeModel(final("Carrier B is the slowest. Let me know if you want me to check more."))
        orchestrator.run_turn("S", "U", model, CTX)
        self.assertEqual(len(model.prompts), 1)

    def test_a_reply_with_actions_is_not_a_bare_promise(self):
        model = FakeModel(final("Let me open that for you.", actions=[{"type": "navigate", "page": "analysis"}]))
        orchestrator.run_turn("S", "U", model, CTX)
        self.assertEqual(len(model.prompts), 1)

    def test_without_a_session_there_is_nothing_to_look_up_so_no_nudge(self):
        model = FakeModel(final("I'll look that up."))
        orchestrator.run_turn("S", "U", model, None)
        self.assertEqual(len(model.prompts), 1)


class GroundTest(unittest.TestCase):
    def _result(self, reply, evidence="rows: 303"):
        return orchestrator.TurnResult(raw={"reply": reply}, evidence=evidence, scratch="\n\n--- TOOL RESULTS ---\nrows: 303", tools_used=["get_dataset_summary"])

    def test_a_grounded_reply_is_left_alone(self):
        model = FakeModel()
        raw, bad = orchestrator.ground(self._result("There are 303 trips."), "S", "U", model)
        self.assertEqual((raw["reply"], bad), ("There are 303 trips.", []))
        self.assertEqual(model.prompts, [])  # no review call was needed

    def test_a_reply_with_an_invented_figure_gets_one_review(self):
        model = FakeModel(final("There are 303 trips."))
        raw, bad = orchestrator.ground(self._result("There are 4,200 trips."), "S", "U", model)
        self.assertEqual((raw["reply"], bad), ("There are 303 trips.", []))
        self.assertIn("4,200", model.prompts[0])
        self.assertIn("REVIEW", model.prompts[0])
        self.assertIn("rows: 303", model.prompts[0])  # the tool results are shown again

    def test_a_review_that_still_invents_a_figure_is_reported_not_hidden(self):
        model = FakeModel(final("Roughly 5,000 trips."))
        raw, bad = orchestrator.ground(self._result("There are 4,200 trips."), "S", "U", model)
        self.assertEqual(bad, ["5,000"])
        self.assertEqual(raw["reply"], "Roughly 5,000 trips.")

    def test_a_review_that_is_not_json_keeps_the_original_and_reports_it(self):
        raw, bad = orchestrator.ground(self._result("There are 4,200 trips."), "S", "U", FakeModel("garbage"))
        self.assertEqual((raw["reply"], bad), ("There are 4,200 trips.", ["4,200"]))

    def test_an_empty_review_reply_keeps_the_original(self):
        raw, bad = orchestrator.ground(self._result("There are 4,200 trips."), "S", "U", FakeModel({"reply": ""}))
        self.assertEqual((raw["reply"], bad), ("There are 4,200 trips.", ["4,200"]))


class PromptTest(unittest.TestCase):
    def test_the_tools_prompt_lists_every_tool_and_the_limits(self):
        text = orchestrator.tools_prompt()
        for name in orchestrator.tools.TOOLS:
            self.assertIn(name, text)
        self.assertIn(str(orchestrator.MAX_CALLS_PER_ROUND), text)
        self.assertIn("tool_calls", text)


if __name__ == "__main__":
    unittest.main()
