"""The chat endpoint's action rules: what the model may ask the app to do, and when.

Run from backend/:  python -m unittest discover -s tests
"""
import unittest
from types import SimpleNamespace
from unittest import mock

from app.routers import chat


def _issue(requires_decision: bool, status: str):
    return SimpleNamespace(requires_decision=requires_decision, status=status)


def _request(session_id="s1", **state):
    return chat.ChatTurnRequest(
        session_id=session_id,
        messages=[chat.ChatMessage(role="user", content="hi")],
        state=state,
    )


ADD = {"type": "add_analysis", "name": "Alarm rate", "description": "Alarms per carrier"}


class CleanActionsTest(unittest.TestCase):
    def test_add_actions_pass_once_the_data_is_audited(self):
        out = chat._clean_actions([ADD], audited=True)
        self.assertEqual([a["type"] for a in out.actions], ["add_analysis"])
        self.assertEqual(out.needs_audit, [])

    def test_add_actions_are_refused_before_the_audit_is_done(self):
        out = chat._clean_actions(
            [ADD, {"type": "add_feature", "name": "Hours", "description": "Transit hours"}], audited=False
        )
        self.assertEqual(out.actions, [])
        self.assertEqual(out.needs_audit, ["add_analysis", "add_feature"])

    def test_navigation_and_other_actions_are_never_blocked_by_the_audit(self):
        out = chat._clean_actions([{"type": "navigate", "page": "audit"}, {"type": "check_ready"}], audited=False)
        self.assertEqual([a["type"] for a in out.actions], ["navigate", "check_ready"])
        self.assertEqual(out.needs_audit, [])

    def test_the_planner_page_is_a_known_page(self):
        self.assertEqual(chat._clean_actions([{"type": "navigate", "page": "planner"}]).actions, [{"type": "navigate", "page": "planner"}])

    def test_unknown_types_pages_and_the_removed_explain_action_are_dropped(self):
        out = chat._clean_actions(
            [{"type": "delete_everything"}, {"type": "navigate", "page": "nowhere"}, {"type": "explain", "target": "x"}, "x"]
        )
        self.assertEqual(out.actions, [])

    def test_up_to_six_actions_in_one_answer(self):
        many = [dict(ADD, name=f"Analysis {i}") for i in range(8)]
        self.assertEqual(len(chat._clean_actions(many).actions), chat.MAX_ACTIONS)
        self.assertEqual(chat.MAX_ACTIONS, 6)


class IntentTest(unittest.TestCase):
    """A question can never change the report, whatever else the model wrote."""

    def test_an_ask_may_navigate_but_not_add(self):
        out = chat._clean_actions([ADD, {"type": "navigate", "page": "analysis"}], intent="ask")
        self.assertEqual([a["type"] for a in out.actions], ["navigate"])
        self.assertEqual(out.off_intent, ["add_analysis"])

    def test_a_change_may_add(self):
        out = chat._clean_actions([ADD], intent="change")
        self.assertEqual([a["type"] for a in out.actions], ["add_analysis"])

    def test_the_interview_may_set_the_brief_but_not_add(self):
        out = chat._clean_actions([{"type": "set_brief", "text": "Brief."}, ADD], intent="interview")
        self.assertEqual([a["type"] for a in out.actions], ["set_brief"])
        self.assertEqual(out.off_intent, ["add_analysis"])

    def test_an_off_intent_action_is_explained_after_the_reply(self):
        out = chat._normalise({"reply": "Here it is.", "intent": "ask", "actions": [ADD]}, {})
        self.assertEqual(out["actions"], [])
        self.assertIn("I have not changed anything", out["reply"])

    def test_a_missing_intent_follows_the_phase(self):
        self.assertEqual(chat._intent_of({}, "readback"), "interview")
        self.assertEqual(chat._intent_of({}, "refine"), "other")
        self.assertEqual(chat._intent_of({"intent": "bogus"}, "refine"), "other")
        self.assertEqual(chat._intent_of({"intent": "ask"}, "interview"), "ask")


class OpenItemTest(unittest.TestCase):
    KNOWN = {"a1": "analysis", "f1": "feature"}

    def _nav(self, page, target):
        return chat._clean_actions([{"type": "navigate", "page": page, "open": target}], known_items=self.KNOWN).actions[0]

    def test_an_existing_analysis_opens_on_the_analysis_page(self):
        self.assertEqual(self._nav("analysis", "a1"), {"type": "navigate", "page": "analysis", "open": "a1"})

    def test_an_existing_calculation_opens_on_the_features_page(self):
        self.assertEqual(self._nav("features", "f1"), {"type": "navigate", "page": "features", "open": "f1"})

    def test_an_id_that_does_not_exist_is_dropped_but_the_page_still_opens(self):
        self.assertEqual(self._nav("analysis", "nope"), {"type": "navigate", "page": "analysis"})

    def test_an_id_of_the_wrong_kind_for_the_page_is_dropped(self):
        self.assertEqual(self._nav("analysis", "f1"), {"type": "navigate", "page": "analysis"})
        self.assertEqual(self._nav("features", "a1"), {"type": "navigate", "page": "features"})

    def test_other_pages_never_carry_an_item(self):
        self.assertEqual(self._nav("report", "a1"), {"type": "navigate", "page": "report"})


class OpenWhatWasReadTest(unittest.TestCase):
    """Explaining an analysis opens that analysis even when the model leaves the id out of its navigate action."""
    KNOWN = {"a1": "analysis", "f1": "feature"}

    def _out(self, actions, looked_at, intent="ask"):
        raw = {"reply": "Here it is.", "intent": intent, "actions": actions}
        return chat._normalise(raw, {}, known_items=self.KNOWN, looked_at=looked_at)["actions"]

    def test_a_navigate_without_an_id_gets_the_item_that_was_read(self):
        self.assertEqual(self._out([{"type": "navigate", "page": "analysis"}], [("analysis", "a1")]),
                         [{"type": "navigate", "page": "analysis", "open": "a1"}])

    def test_a_wrong_id_that_was_dropped_is_replaced_by_the_item_that_was_read(self):
        self.assertEqual(self._out([{"type": "navigate", "page": "analysis", "open": "made-up"}], [("analysis", "a1")]),
                         [{"type": "navigate", "page": "analysis", "open": "a1"}])

    def test_no_navigate_at_all_still_opens_the_item(self):
        self.assertEqual(self._out([], [("feature", "f1")]), [{"type": "navigate", "page": "features", "open": "f1"}])

    def test_reading_the_same_item_twice_is_still_one_item(self):
        self.assertEqual(self._out([], [("analysis", "a1"), ("analysis", "a1")]),
                         [{"type": "navigate", "page": "analysis", "open": "a1"}])

    def test_several_items_read_means_no_guessing(self):
        self.assertEqual(self._out([{"type": "navigate", "page": "analysis"}], [("analysis", "a1"), ("feature", "f1")]),
                         [{"type": "navigate", "page": "analysis"}])

    def test_a_navigate_to_another_page_is_left_alone(self):
        self.assertEqual(self._out([{"type": "navigate", "page": "report"}], [("analysis", "a1")]),
                         [{"type": "navigate", "page": "report"}])

    def test_nothing_is_opened_when_nothing_was_read(self):
        self.assertEqual(self._out([], []), [])

    def test_an_id_the_model_gave_is_kept(self):
        self.assertEqual(self._out([{"type": "navigate", "page": "analysis", "open": "a1"}], [("analysis", "a1")]),
                         [{"type": "navigate", "page": "analysis", "open": "a1"}])

    def test_adding_something_never_opens_an_item_by_this_rule(self):
        self.assertEqual(self._out([], [("analysis", "a1")], intent="change"), [])


class NextQuestionsTest(unittest.TestCase):
    def test_short_distinct_questions_the_pm_has_not_asked(self):
        out = chat._clean_questions(["Why is X high?", "why is x high?", "What about Y?", "", 5, "Z" * 200, "A?", "B?"], ["What about Y?"])
        self.assertEqual(out[0], "Why is X high?")
        self.assertNotIn("What about Y?", out)
        self.assertLessEqual(len(out), chat.MAX_NEXT_QUESTIONS)
        self.assertTrue(all(len(q) <= 90 for q in out))

    def test_not_a_list_gives_none(self):
        self.assertEqual(chat._clean_questions("a question", []), [])

    def test_none_are_offered_during_the_interview(self):
        out = chat._normalise({"reply": "x", "intent": "interview", "next_questions": ["Q?"]}, {})
        self.assertEqual(out["next_questions"], [])

    def test_they_are_offered_after_an_answer_about_the_report(self):
        out = chat._normalise({"reply": "x", "intent": "ask", "next_questions": ["Which carrier is slowest?"]}, {"phase": "refine"})
        self.assertEqual(out["next_questions"], ["Which carrier is slowest?"])


class NormaliseTest(unittest.TestCase):
    def test_a_refused_action_is_explained_after_the_reply(self):
        raw = {"reply": "I'll add it.", "intent": "change", "actions": [ADD]}
        out = chat._normalise(raw, {}, audited=False, pending=2)
        self.assertEqual(out["actions"], [])
        self.assertIn("I'll add it.", out["reply"])
        self.assertIn("2 decisions left", out["reply"])

    def test_without_data_the_note_asks_for_the_data(self):
        out = chat._normalise({"reply": "OK.", "intent": "change", "actions": [ADD]}, {}, audited=False, pending=None)
        self.assertIn("load the data", out["reply"])

    def test_with_data_loaded_the_note_does_not_ask_for_it_again(self):
        # Data is loaded but the audit is not done (no standard issues exist yet): only the audit is missing.
        out = chat._normalise({"reply": "OK.", "intent": "change", "actions": [ADD]}, {}, audited=False, pending=0)
        self.assertIn("finish the data audit first", out["reply"])
        self.assertNotIn("load the data", out["reply"])

    def test_nothing_is_added_to_a_reply_when_nothing_was_refused(self):
        out = chat._normalise({"reply": "Hello."}, {}, audited=False)
        self.assertEqual(out["reply"], "Hello.")

    def test_unverified_figures_are_flagged_in_the_reply(self):
        out = chat._normalise({"reply": "It is 87%.", "intent": "ask"}, {}, unverified=["87%"])
        self.assertIn("87%", out["reply"].split("\n\n")[-1])
        self.assertIn("could not check", out["reply"])


class PhaseTest(unittest.TestCase):
    """The chat only interviews. The Planner step plans, so there is no plan phase and no plan in the answer."""

    def test_ready_is_a_phase_and_plan_is_not(self):
        self.assertIn("ready", chat.PHASES)
        self.assertNotIn("plan", chat.PHASES)

    def test_a_ready_answer_is_kept(self):
        self.assertEqual(chat._normalise({"reply": "Done.", "phase": "ready"}, {"phase": "readback"})["phase"], "ready")

    def test_an_unknown_phase_falls_back_to_the_previous_one(self):
        self.assertEqual(chat._normalise({"reply": "x", "phase": "plan"}, {"phase": "readback"})["phase"], "readback")

    def test_the_answer_has_no_plan(self):
        out = chat._normalise({"reply": "x", "plan": {"analyses": [{"name": "A", "description": "b"}]}}, {})
        self.assertNotIn("plan", out)

    def test_approve_plan_is_no_longer_an_action(self):
        self.assertEqual(chat._clean_actions([{"type": "approve_plan"}]).actions, [])


class AuditStatusTest(unittest.TestCase):
    def _status(self, issues, reviewed, session_id="s1"):
        session = SimpleNamespace(issues=issues)
        with mock.patch.object(chat, "get_or_404", return_value=session):
            return chat._audit_status(_request(session_id=session_id, audit_reviewed=reviewed))

    def test_no_session_means_not_ready(self):
        self.assertEqual(chat._audit_status(_request(session_id=None, audit_reviewed=True)), (False, None))

    def test_open_decisions_block_even_when_the_browser_says_reviewed(self):
        self.assertEqual(self._status([_issue(True, "pending"), _issue(True, "resolved")], reviewed=True), (False, 1))

    def test_ready_only_when_the_browser_says_so_and_nothing_is_pending(self):
        self.assertEqual(self._status([_issue(True, "resolved"), _issue(False, "pending")], reviewed=True), (True, 0))

    def test_an_audit_that_has_not_run_is_not_ready(self):
        # No issues at all looks "reviewed" on the server; the browser knows the audit has not run.
        self.assertEqual(self._status([], reviewed=False), (False, 0))


class UserPromptTest(unittest.TestCase):
    def test_the_model_is_told_whether_the_audit_is_done(self):
        with mock.patch.object(chat, "_data_block", return_value="DATA"):
            prompt = chat._user_prompt(_request(), audited=False, pending=3)
        self.assertIn('"audit_reviewed": false', prompt)
        self.assertIn('"pending_audit_decisions": 3', prompt)


class PlannerInterviewTest(unittest.TestCase):
    """The Planner reads the interview the chat saved, before it suggests anything."""

    def _block(self, record):
        from app.services.planner import planner

        with mock.patch.object(planner.doc_store, "get", return_value=record):
            return planner._interview_block("s1")

    def test_no_interview_means_no_block(self):
        self.assertEqual(self._block(None), "")
        self.assertEqual(self._block({"understanding": {}, "assumptions": []}), "")

    def test_answers_and_assumptions_reach_the_planner(self):
        block = self._block({
            "understanding": {"goal": "Spoilage by carrier", "limits": "0 to 2 C"},
            "assumptions": [{"id": "a1", "text": "Road only"}],
        })
        self.assertIn("Goal: Spoilage by carrier", block)
        self.assertIn("Limits and definitions: 0 to 2 C", block)
        self.assertIn("Assumption (not confirmed by the client): Road only", block)

    def test_a_plan_left_in_an_old_record_is_ignored(self):
        block = self._block({"understanding": {"goal": "G"}, "plan": {"analyses": [{"name": "Old", "description": "x"}]}})
        self.assertNotIn("Old", block)


if __name__ == "__main__":
    unittest.main()
