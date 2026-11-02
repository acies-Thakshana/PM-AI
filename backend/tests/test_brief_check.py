"""Is this text a client brief? The word rule, and what the chat endpoint does with the model's verdict.

Run from backend/:  python -m unittest discover -s tests
"""
import unittest

from app.routers import chat
from app.services.common.brief_rules import brief_quality

SET_BRIEF = {"type": "set_brief", "text": "Show excursions by carrier for the Kiwi shipments"}
GOOD = "Show temperature excursions by carrier for the Kiwi shipments last season"


class BriefQualityTest(unittest.TestCase):
    def test_text_with_no_real_word_is_junk(self):
        for text in ("xxx", "qwrt", "....", "12345", "", "   ", "xxx yyy zzz", "aaa bbb ccc ddd eee"):
            self.assertEqual(brief_quality(text), "junk", text)

    def test_a_few_words_are_short_and_left_to_the_assistant_to_judge(self):
        # "asdf" has a vowel, so only the assistant (and the PM) can tell it is a keyboard smash.
        for text in ("hi", "asdf", "hello there", "compare carriers by excursion"):
            self.assertEqual(brief_quality(text), "short", text)

    def test_five_real_words_are_enough(self):
        self.assertEqual(brief_quality(GOOD), "ok")
        self.assertEqual(brief_quality("show me carrier excursion rates"), "ok")

    def test_one_real_word_among_junk_is_not_junk(self):
        self.assertEqual(brief_quality("xxx carriers"), "short")

    def test_other_scripts_are_not_judged_by_vowels(self):
        self.assertEqual(brief_quality("वाहक के अनुसार तापमान विचलन दिखाएं"), "ok")


class VerdictTest(unittest.TestCase):
    def verdict(self, raw, **state):
        return chat._brief_verdict(raw, state)[0]

    def test_no_candidate_nothing_to_judge(self):
        self.assertEqual(self.verdict({"brief_check": "not_brief"}), "na")

    def test_junk_is_never_a_brief_whatever_the_model_says(self):
        self.assertEqual(self.verdict({"brief_check": "ok"}, brief_candidate="xxx"), "not_brief")

    def test_a_short_text_is_never_ok(self):
        self.assertEqual(self.verdict({"brief_check": "ok"}, brief_candidate="carrier excursions"), "unsure")

    def test_the_models_verdict_stands_for_a_proper_text(self):
        for said in ("ok", "unsure", "not_brief", "na"):
            self.assertEqual(self.verdict({"brief_check": said}, brief_candidate=GOOD, brief_candidate_source="message"), said)

    def test_a_missing_or_odd_verdict_goes_by_the_words(self):
        self.assertEqual(self.verdict({}, brief_candidate=GOOD), "ok")
        self.assertEqual(self.verdict({"brief_check": "maybe"}, brief_candidate="carrier excursions"), "unsure")

    def test_the_brief_itself_is_never_not_applicable(self):
        self.assertEqual(self.verdict({"brief_check": "na"}, brief_candidate=GOOD, brief_candidate_source="brief"), "ok")


class NormaliseWithBriefCheckTest(unittest.TestCase):
    def reply(self, raw, **state):
        return chat._normalise({"reply": "Got it.", "intent": "interview", **raw}, state)

    def test_an_unsure_brief_is_asked_about_and_nothing_else_moves(self):
        out = self.reply(
            {"brief_check": "unsure", "phase": "readback", "actions": [SET_BRIEF], "assumptions": [{"id": "a1", "text": "x"}]},
            brief_candidate="carrier excursions", phase="interview",
        )
        self.assertEqual(out["brief_check"], "unsure")
        self.assertEqual(out["phase"], "interview")
        self.assertEqual(out["actions"], [])
        self.assertEqual(out["assumptions"], [])
        self.assertEqual(out["quick_replies"], chat.BRIEF_CONFIRM_REPLIES)
        self.assertIn("carrier excursions", out["reply"])
        self.assertIn("Is this your client brief?", out["reply"])

    def test_a_text_that_is_not_a_brief_is_said_so_with_no_buttons(self):
        out = self.reply({"brief_check": "not_brief", "actions": [SET_BRIEF]}, brief_candidate="xxx")
        self.assertEqual(out["brief_check"], "not_brief")
        self.assertEqual(out["reply"], chat.BRIEF_NOT_A_BRIEF)
        self.assertEqual(out["quick_replies"], [])
        self.assertEqual(out["actions"], [])

    def test_what_was_understood_so_far_is_kept(self):
        out = self.reply({"brief_check": "unsure"}, brief_candidate="carrier excursions", understanding={"goal": "Find spoilage"})
        self.assertEqual(out["understanding"]["goal"], "Find spoilage")

    def test_a_long_candidate_is_shortened_in_the_question(self):
        out = self.reply({"brief_check": "unsure"}, brief_candidate="word " * 200)
        self.assertLess(len(out["reply"]), 400)
        self.assertIn("…", out["reply"])

    def test_an_ok_brief_goes_on_as_before_and_may_be_stored(self):
        out = self.reply({"brief_check": "ok", "actions": [SET_BRIEF]}, brief_candidate=GOOD, brief_candidate_source="message")
        self.assertEqual(out["brief_check"], "ok")
        self.assertEqual([a["type"] for a in out["actions"]], ["set_brief"])
        self.assertEqual(out["reply"], "Got it.")

    def test_a_greeting_is_answered_and_never_stored_as_the_brief(self):
        out = self.reply({"brief_check": "na", "actions": [SET_BRIEF]}, brief_candidate="hello there my friend how are you", brief_candidate_source="message")
        self.assertEqual(out["brief_check"], "na")
        self.assertEqual(out["actions"], [])
        self.assertEqual(out["reply"], "Got it.")

    def test_without_a_candidate_nothing_changes(self):
        out = self.reply({"brief_check": "unsure", "actions": [SET_BRIEF]})
        self.assertEqual(out["brief_check"], "na")
        self.assertEqual([a["type"] for a in out["actions"]], ["set_brief"])


if __name__ == "__main__":
    unittest.main()
