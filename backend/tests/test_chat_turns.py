"""Recording a chat turn: the recorder, the chat's events, the turn endpoints, and `POST /turn` with and without ids."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from pydantic import ValidationError

from app.routers import chat, chat_turns
from app.routers.deps import User
from app.services.chat import chat_events, chat_store, orchestrator
from app.services.chat.orchestrator import TurnResult
from app.services.chat.turn_recorder import TurnRecorder, reads_of
from app.services.common import audit_log, request_context, token_usage

USER = "pm.user@example.com"


class _Env(unittest.TestCase):
    """Local-file chat store in a temp folder, the caller set to USER, and the audit log captured."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.events = mock.MagicMock()
        for patch in (
            mock.patch.object(chat_store, "_CHATS_DIR", self.tmp / "chats"),
            mock.patch.object(chat_store, "DDB_CHATS", ""),
            mock.patch.object(audit_log, "log_event", self.events),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        token = request_context.current_user_id.set(USER)
        self.addCleanup(request_context.current_user_id.reset, token)

    def logged(self):
        """[(event_type, payload)] in the order they were logged."""
        return [(c.args[2], c.args[3]) for c in self.events.call_args_list]


class ReadsTest(unittest.TestCase):
    def test_items_read_come_first_with_their_ids_then_the_other_tools(self):
        reads = reads_of(["find_item", "get_analysis", "get_analysis", "get_dataset_summary"], [("analysis", "a3"), ("analysis", "a3")])
        self.assertEqual(reads, [{"tool": "get_analysis", "id": "a3"}, {"tool": "find_item"}, {"tool": "get_dataset_summary"}])

    def test_nothing_read_is_an_empty_list(self):
        self.assertEqual(reads_of([], []), [])

    def test_a_failed_lookup_of_an_item_is_not_listed_as_read(self):
        self.assertEqual(reads_of(["get_feature"], []), [])


class RecorderTest(_Env):
    def test_without_ids_nothing_is_recorded_and_nothing_is_tagged(self):
        recorder = TurnRecorder.begin(chat_id=None, turn_id=None, user_text="hi")
        self.assertFalse(recorder.active)
        recorder.complete({"reply": "x"}, tools_used=[], looked_at=[])
        recorder.fail("X", 502, "boom")
        recorder.close()
        self.assertEqual(self.logged(), [])
        self.assertFalse((self.tmp / "chats").exists())
        self.assertIsNone(request_context.current_turn_id.get())

    def test_unusable_ids_are_treated_as_missing(self):
        self.assertFalse(TurnRecorder.begin(chat_id="../x", turn_id="t_1", user_text="hi").active)

    def test_begin_stores_the_message_and_tags_events_until_close(self):
        recorder = TurnRecorder.begin(
            chat_id="c_1", turn_id="t_1", user_text="Explain it.", session_id="s_1", state={"stage": "features", "phase": "refine"},
        )
        self.assertTrue(recorder.active)
        self.assertEqual((request_context.current_chat_id.get(), request_context.current_turn_id.get()), ("c_1", "t_1"))
        turn = chat_store.get_turn("c_1", "t_1")
        self.assertEqual((turn["page"], turn["phase"], turn["session_id"], turn["handled_by"]), ("features", "refine", "s_1", "chat_model"))
        self.assertEqual(self.logged(), [("chat_message", {"role": "user", "chars": 11, "handled_by": "chat_model"})])
        recorder.close()
        self.assertIsNone(request_context.current_chat_id.get())

    def test_complete_keeps_the_answer_the_reads_and_the_refused_actions(self):
        recorder = TurnRecorder.begin(chat_id="c_1", turn_id="t_1", user_text="Add one.")
        response = {
            "reply": "Done.", "intent": "change", "phase": "refine", "next_questions": ["Q?"],
            "understanding": {"goal": "", "scope": ""}, "assumptions": [],
            "actions": [
                {"type": "navigate", "page": "analysis", "open": "a3"},
                {"type": "set_brief", "text": "The brief the PM typed."},
            ],
        }
        recorder.complete(
            response, tools_used=["get_analysis"], looked_at=[("analysis", "a3")],
            refusals={"needs_audit": ["add_analysis"], "off_intent": []}, state={},
        )
        recorder.close()
        turn = chat_store.get_turn("c_1", "t_1")
        self.assertEqual(turn["status"], "completed")
        self.assertEqual(turn["reads"], [{"tool": "get_analysis", "id": "a3"}])
        self.assertEqual([(a["type"], a["status"]) for a in turn["actions"]],
                         [("navigate", "proposed"), ("set_brief", "proposed"), ("add_analysis", "refused_audit")])
        self.assertEqual(turn["actions"][1], {"type": "set_brief", "chars": 23, "source": "model", "status": "proposed"})
        self.assertNotIn("understanding", turn)  # nothing was learned this turn
        self.assertNotIn("assumptions", turn)
        types = [t for t, _ in self.logged()]
        self.assertEqual(types, ["chat_message", "chat_action", "chat_action", "chat_action", "chat_message"])

    def test_understanding_is_kept_only_when_the_turn_changed_it(self):
        learned = {"goal": "spoilage", "scope": ""}
        recorder = TurnRecorder.begin(chat_id="c_1", turn_id="t_1", user_text="spoilage")
        recorder.complete({"reply": "ok", "understanding": learned, "assumptions": [{"id": "a1", "text": "x"}], "actions": []},
                          tools_used=[], looked_at=[], state={"understanding": {"goal": "", "scope": ""}})
        recorder.close()
        turn = chat_store.get_turn("c_1", "t_1")
        self.assertEqual((turn["understanding"], turn["assumptions"]), (learned, [{"id": "a1", "text": "x"}]))

        again = TurnRecorder.begin(chat_id="c_1", turn_id="t_2", user_text="more")
        again.complete({"reply": "ok", "understanding": learned, "assumptions": [{"id": "a1", "text": "x"}], "actions": []},
                       tools_used=[], looked_at=[], state={"understanding": learned, "assumptions": [{"id": "a1", "text": "x"}]})
        again.close()
        second = chat_store.get_turn("c_1", "t_2")
        self.assertNotIn("understanding", second)
        self.assertNotIn("assumptions", second)

    def test_fail_marks_the_turn_and_logs_the_error(self):
        recorder = TurnRecorder.begin(chat_id="c_1", turn_id="t_1", user_text="hi")
        recorder.fail("LLM_ERROR", 502, "boom")
        recorder.close()
        turn = chat_store.get_turn("c_1", "t_1")
        self.assertEqual((turn["status"], turn["error_code"]), ("failed", "LLM_ERROR"))
        self.assertEqual(self.logged()[-1][0], "chat_error")

    def test_a_broken_store_never_breaks_the_turn(self):
        with mock.patch.object(chat_store, "complete_turn", side_effect=RuntimeError("down")):
            recorder = TurnRecorder.begin(chat_id="c_1", turn_id="t_1", user_text="hi")
            recorder.complete({"reply": "x", "actions": []}, tools_used=[], looked_at=[])  # must not raise
            recorder.close()


class ChatEventsTest(_Env):
    def test_a_tool_call_names_the_record_it_read(self):
        chat_events.tool_call("get_analysis", {"id": "a3"}, {"id": "a3", "name": "X"}, 85)
        _, payload = self.logged()[0]
        self.assertEqual((payload["tool"], payload["ok"], payload["ms"]), ("get_analysis", True, 85))
        self.assertEqual(self.events.call_args.kwargs, {"target": "ANALYSES#a3", "result": "ok"})

    def test_a_tool_that_returned_an_error_is_a_failed_event_with_the_reason(self):
        chat_events.tool_call("get_feature", {"id": "zz"}, {"error": "No calculation has that id."}, 3)
        _, payload = self.logged()[0]
        self.assertEqual((payload["ok"], payload["error"]), (False, "No calculation has that id."))
        self.assertEqual(self.events.call_args.kwargs, {"target": "FEATURES#zz", "result": "failed"})

    def test_tools_without_an_item_have_no_target(self):
        chat_events.tool_call("get_dataset_summary", {}, {"rows": 3}, 1)
        self.assertIsNone(self.events.call_args.kwargs["target"])

    def test_an_action_on_a_page_item_targets_that_item(self):
        chat_events.action({"type": "navigate", "page": "features", "open": "f1"}, "proposed")
        self.assertEqual(self.events.call_args.kwargs["target"], "FEATURES#f1")
        chat_events.action({"type": "add_analysis", "entry_id": "a7", "name": "N"}, "applied")
        self.assertEqual(self.events.call_args.kwargs["target"], "ANALYSES#a7")

    def test_a_failed_action_is_a_failed_event(self):
        chat_events.action({"type": "add_feature"}, "failed")
        self.assertEqual(self.events.call_args.kwargs["result"], "failed")

    def test_the_events_are_classified_as_chat_events(self):
        for event in ("chat_message", "chat_tool_call", "chat_action", "chat_grounding_review", "chat_error"):
            self.assertEqual(audit_log.classify(event, {"role": "user", "tool": "t", "action": "a", "status": "s", "error_code": "E"})[0], "chat")

    def test_the_interview_event_is_filed_under_the_planner_step_with_its_record(self):
        self.assertEqual(
            audit_log.classify("interview_saved", {"assumptions": 2}),
            ("session", 2, "INTERVIEW", "Saved the interview (2 assumptions)"),
        )
        self.assertEqual(audit_log.classify("interview_saved", {"assumptions": 0})[3], "Saved the interview (0 assumptions)")


class AuditLogTaggingTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "audit_log.jsonl"
        for patch in (mock.patch.object(audit_log, "LOCAL_LOG_PATH", self.path), mock.patch.object(audit_log, "DDB_AUDIT", "")):
            patch.start()
            self.addCleanup(patch.stop)

    def lines(self):
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]

    def test_an_event_made_during_a_turn_carries_the_turn(self):
        tokens = (request_context.current_chat_id.set("c_1"), request_context.current_turn_id.set("t_1"))
        try:
            audit_log.log_event("s_1", USER, "chat_message", {"role": "user"})
        finally:
            request_context.current_chat_id.reset(tokens[0])
            request_context.current_turn_id.reset(tokens[1])
        event = self.lines()[0]
        self.assertEqual((event["chat_id"], event["turn_id"], event["turn_key"]), ("c_1", "t_1", "c_1#t_1"))

    def test_other_events_are_exactly_as_before(self):
        audit_log.log_event("s_1", USER, "upload", {"filename": "f.xlsx", "rows": 3})
        event = self.lines()[0]
        for name in ("chat_id", "turn_id", "turn_key"):
            self.assertNotIn(name, event)


class TokenUsageTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.events = mock.MagicMock()
        for patch in (
            mock.patch.object(token_usage, "LOG_PATH", Path(tmp.name) / "token_usage.jsonl"),
            mock.patch.object(audit_log, "log_event", self.events),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_a_chat_call_is_logged_with_its_tokens(self):
        token_usage.record("chat_agent", "model-x", {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15})
        self.assertEqual(self.events.call_count, 1)
        event_type, payload = self.events.call_args.args[2:4]
        self.assertEqual(event_type, "llm_call")
        self.assertEqual(payload, {"call_name": "chat_agent", "model": "model-x", "input_tokens": 10, "output_tokens": 5, "total_tokens": 15})

    def test_the_other_calls_are_not_logged_as_before(self):
        token_usage.record("planner_agent", "model-x", {"inputTokens": 10, "outputTokens": 5})
        self.events.assert_not_called()


class TurnEndpointTest(_Env):
    """`POST /turn` with the model stood in for."""

    RAW = {"reply": "It is the days in transit.", "intent": "ask", "phase": "refine",
           "actions": [{"type": "navigate", "page": "features"}], "next_questions": ["How is it calculated?"]}

    def setUp(self):
        super().setUp()
        self.seen = {}

        def run_turn(system, user, ask, ctx):
            self.seen["turn"] = request_context.current_turn_id.get()
            return TurnResult(raw=dict(self.RAW), evidence="", scratch="", tools_used=["get_feature"], looked_at=[("feature", "f1")])

        for patch in (
            mock.patch.object(chat.llm, "system_prompt", return_value="SYS"),
            mock.patch.object(orchestrator, "run_turn", side_effect=run_turn),
            mock.patch.object(orchestrator, "ground", side_effect=lambda result, *a: (result.raw, [])),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def request(self, **extra):
        return chat.ChatTurnRequest(
            messages=[chat.ChatMessage(role="user", content="Explain Transit Days.")],
            state={"stage": "features", "phase": "refine"}, **extra,
        )

    def test_a_turn_with_ids_is_recorded_and_the_events_are_tagged_while_it_runs(self):
        response = chat.turn(self.request(chat_id="c_1", turn_id="t_1"))
        self.assertEqual(self.seen["turn"], "t_1")
        self.assertIsNone(request_context.current_turn_id.get())  # closed again
        turn = chat_store.get_turn("c_1", "t_1")
        self.assertEqual(turn["status"], "completed")
        self.assertEqual([m["content"] for m in turn["messages"]], ["Explain Transit Days.", response["reply"]])
        self.assertEqual(turn["reads"], [{"tool": "get_feature", "id": "f1"}])
        self.assertEqual(turn["actions"][0]["open"], "f1")  # the opened item the server added to the model's action
        self.assertEqual(turn["next_questions"], ["How is it calculated?"])
        self.assertEqual((turn["intent"], turn["page"], turn["handled_by"]), ("ask", "features", "chat_model"))

    def test_the_answer_is_exactly_the_same_with_and_without_recording(self):
        with_ids = chat.turn(self.request(chat_id="c_1", turn_id="t_1"))
        without = chat.turn(self.request())
        self.assertEqual(with_ids, without)
        self.assertEqual(sorted(p.name for p in (self.tmp / "chats").iterdir()), ["c_1.json"])  # the second left no record

    def test_a_turn_without_ids_is_not_recorded(self):
        chat.turn(self.request())
        self.assertFalse((self.tmp / "chats").exists())
        self.assertEqual([t for t, _ in self.logged() if t.startswith("chat_")], [])

    def test_a_failed_model_call_marks_the_turn_failed_and_still_answers_502(self):
        with mock.patch.object(orchestrator, "run_turn", side_effect=ValueError("not json")):
            with self.assertRaises(HTTPException) as caught:
                chat.turn(self.request(chat_id="c_1", turn_id="t_1"))
        self.assertEqual(caught.exception.status_code, 502)
        turn = chat_store.get_turn("c_1", "t_1")
        self.assertEqual((turn["status"], turn["error_code"]), ("failed", "LLM_ERROR"))
        self.assertEqual(len(turn["messages"]), 1)  # the PM's message survived
        self.assertEqual(self.logged()[-1][0], "chat_error")

    def test_a_service_error_is_503_and_marked(self):
        with mock.patch.object(orchestrator, "run_turn", side_effect=RuntimeError("no model configured")):
            with self.assertRaises(HTTPException) as caught:
                chat.turn(self.request(chat_id="c_1", turn_id="t_1"))
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(chat_store.get_turn("c_1", "t_1")["error_code"], "UNAVAILABLE")

    def test_the_hidden_interview_prompt_is_marked_hidden(self):
        chat.turn(self.request(chat_id="c_1", turn_id="t_1", hidden=True))
        self.assertEqual(chat_store.get_turn("c_1", "t_1")["messages"][0]["kind"], "hidden")

    def test_refused_actions_are_kept_on_the_turn(self):
        refused ={"reply": "Added.", "intent": "change", "actions": [{"type": "add_analysis", "name": "A", "description": "d"}]}
        with mock.patch.object(orchestrator, "run_turn", return_value=TurnResult(raw=refused, evidence="", scratch="", tools_used=[])):
            chat.turn(self.request(chat_id="c_1", turn_id="t_1"))  # no session: the data is not audited
        turn = chat_store.get_turn("c_1", "t_1")
        self.assertEqual([(a["type"], a["status"]) for a in turn["actions"]], [("add_analysis", "refused_audit")])
        self.assertIn("finish the data audit first", turn["messages"][-1]["content"])


class TurnRoutesTest(_Env):
    def setUp(self):
        super().setUp()
        self.user = User(id=USER, name="PM")

    def start(self, **extra):
        body = dict(chat_id="c_1", turn_id="t_1", user_text="Suggest an analysis", handled_by="shortcut_suggest", page="analysis", phase="refine")
        body.update(extra)
        return chat_turns.start_turn(chat_turns.TurnStartIn(**body), user=self.user)

    def test_the_routes_exist_at_the_paths_the_browser_uses(self):
        paths = {route.path for route in chat_turns.router.routes}
        self.assertEqual(paths, {
            "/api/chat/turns",
            "/api/chat/turns/{chat_id}/{turn_id}/finish",
            "/api/chat/turns/{chat_id}/{turn_id}/suggestions/{entry_id}",
        })

    def test_a_turn_the_browser_answered_itself_is_stored(self):
        self.assertEqual(self.start(), {"ok": True})
        turn = chat_store.get_turn("c_1", "t_1")
        self.assertEqual((turn["handled_by"], turn["page"], turn["status"]), ("shortcut_suggest", "analysis", "processing"))
        self.assertIsNone(request_context.current_turn_id.get())

    def test_finishing_adds_the_notes_the_outcomes_and_the_suggestions(self):
        self.start()
        body = chat_turns.TurnFinishIn(
            status="completed",
            notes=[chat_turns.NoteIn(content="3 analyses suggested.")],
            app_actions=[chat_turns.AppActionIn(type="navigate", status="applied", page="analysis")],
            suggestions=[chat_turns.SuggestionIn(kind="analysis", entry_id="a9", name="Average transit days")],
        )
        self.assertEqual(chat_turns.finish_turn(body, chat_id="c_1", turn_id="t_1"), {"ok": True})
        turn = chat_store.get_turn("c_1", "t_1")
        self.assertEqual(turn["status"], "completed")
        self.assertEqual(turn["messages"][-1]["content"], "3 analyses suggested.")
        self.assertEqual(turn["suggestions"][0]["entry_id"], "a9")
        self.assertIn("chat_action", [t for t, _ in self.logged()])

    def test_a_decision_on_a_suggestion_is_recorded(self):
        self.start()
        chat_turns.finish_turn(chat_turns.TurnFinishIn(suggestions=[chat_turns.SuggestionIn(kind="analysis", entry_id="a9", name="N")]),
                               chat_id="c_1", turn_id="t_1")
        result = chat_turns.decide_suggestion(chat_turns.DecisionIn(status="accepted"), entry_id="a9", chat_id="c_1", turn_id="t_1")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(chat_store.get_turn("c_1", "t_1")["suggestions"][0]["status"], "accepted")

    def test_somebody_elses_turn_cannot_be_changed_through_the_endpoints(self):
        self.start()
        token = request_context.current_user_id.set("someone.else@example.com")
        try:
            self.assertEqual(chat_turns.finish_turn(chat_turns.TurnFinishIn(notes=[chat_turns.NoteIn(content="x")]), chat_id="c_1", turn_id="t_1"), {"ok": False})
            self.assertEqual(chat_turns.decide_suggestion(chat_turns.DecisionIn(status="accepted"), entry_id="a9", chat_id="c_1", turn_id="t_1"), {"ok": False})
        finally:
            request_context.current_user_id.reset(token)
        self.assertEqual(len(chat_store.get_turn("c_1", "t_1")["messages"]), 1)

    def test_a_turn_that_was_never_started_answers_not_ok(self):
        self.assertEqual(chat_turns.finish_turn(chat_turns.TurnFinishIn(), chat_id="c_1", turn_id="t_missing"), {"ok": False})

    def test_bad_bodies_are_refused(self):
        with self.assertRaises(ValidationError):
            chat_turns.TurnStartIn(chat_id="../x", turn_id="t_1", user_text="hi", handled_by="shortcut_own")
        with self.assertRaises(ValidationError):
            chat_turns.TurnStartIn(chat_id="c_1", turn_id="t_1", user_text="hi", handled_by="chat_model")  # /turn records those
        with self.assertRaises(ValidationError):
            chat_turns.TurnFinishIn(notes=[chat_turns.NoteIn(content="x" * 2001)])


if __name__ == "__main__":
    unittest.main()
