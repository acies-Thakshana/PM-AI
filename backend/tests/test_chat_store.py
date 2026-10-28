"""The chat's turn record: the local-file backend and the DynamoDB backend (with a stand-in for the client)."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

from boto3.dynamodb.types import TypeDeserializer

from app.services.chat import chat_store

USER = "pm.user@example.com"
OTHER = "someone.else@example.com"


def start(chat="c_1", turn="t_1", **extra):
    kwargs = dict(user_id=USER, user_text="Explain Transit Days.", handled_by="chat_model")
    kwargs.update(extra)
    return chat_store.start_turn(chat, turn, **kwargs)


class LocalBackendTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for patch in (
            mock.patch.object(chat_store, "_CHATS_DIR", Path(tmp.name)),
            mock.patch.object(chat_store, "DDB_CHATS", ""),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_a_started_turn_keeps_the_pms_message_and_is_processing(self):
        self.assertTrue(start(session_id="s_8f21", page="features", phase="refine"))
        turn = chat_store.get_turn("c_1", "t_1")
        self.assertEqual(turn["status"], "processing")
        self.assertEqual(turn["messages"], [{"role": "user", "source": "user", "kind": "text", "content": "Explain Transit Days."}])
        self.assertEqual((turn["user_id"], turn["session_id"], turn["page"], turn["phase"]), (USER, "s_8f21", "features", "refine"))
        self.assertEqual(turn["schema_version"], chat_store.SCHEMA_VERSION)
        self.assertGreater(turn["ttl"], 0)

    def test_unknown_optional_fields_are_left_out(self):
        start()
        turn = chat_store.get_turn("c_1", "t_1")
        for name in ("session_id", "page", "phase"):
            self.assertNotIn(name, turn)  # an index key may not be empty: absent, not ""

    def test_a_hidden_prompt_is_marked(self):
        start(hidden=True)
        self.assertEqual(chat_store.get_turn("c_1", "t_1")["messages"][0]["kind"], "hidden")

    def test_starting_the_same_turn_twice_never_overwrites_it(self):
        start()
        self.assertFalse(start(user_text="something else"))
        self.assertEqual(chat_store.get_turn("c_1", "t_1")["messages"][0]["content"], "Explain Transit Days.")

    def test_ids_that_cannot_be_keys_are_refused(self):
        self.assertFalse(start(chat="../evil"))
        self.assertFalse(start(turn="a/b"))
        self.assertIsNone(chat_store.get_turn("../evil", "t_1"))
        self.assertEqual(chat_store.list_turns("../evil"), [])

    def test_a_very_long_message_is_cut_and_marked(self):
        start(user_text="x" * (chat_store.MAX_MESSAGE_CHARS + 5))
        message = chat_store.get_turn("c_1", "t_1")["messages"][0]
        self.assertEqual(len(message["content"]), chat_store.MAX_MESSAGE_CHARS)
        self.assertTrue(message["truncated"])

    def test_completing_a_turn_adds_the_reply_and_what_was_read(self):
        start()
        done = chat_store.complete_turn(
            "c_1", "t_1", user_id=USER, reply="It is the days in transit.", intent="ask", phase="refine",
            reads=[{"tool": "get_feature", "id": "transit_days"}],
            actions=[{"type": "navigate", "source": "model", "status": "proposed"}],
            next_questions=["How is it calculated?"],
        )
        self.assertTrue(done)
        turn = chat_store.get_turn("c_1", "t_1")
        self.assertEqual(turn["status"], "completed")
        self.assertEqual([m["source"] for m in turn["messages"]], ["user", "model"])
        self.assertEqual(turn["messages"][1]["content"], "It is the days in transit.")
        self.assertEqual((turn["intent"], turn["phase"]), ("ask", "refine"))
        self.assertEqual(turn["reads"], [{"tool": "get_feature", "id": "transit_days"}])
        self.assertIn("completed_at", turn)
        self.assertNotIn("understanding", turn)  # given only when the turn changed it

    def test_understanding_and_assumptions_are_kept_when_given(self):
        start()
        chat_store.complete_turn(
            "c_1", "t_1", user_id=USER, reply="ok", intent="interview", phase="readback", reads=[], actions=[],
            next_questions=[], understanding={"goal": "spoilage"}, assumptions=[{"id": "a1", "text": "0-2 C"}],
        )
        turn = chat_store.get_turn("c_1", "t_1")
        self.assertEqual(turn["understanding"], {"goal": "spoilage"})
        self.assertEqual(turn["assumptions"], [{"id": "a1", "text": "0-2 C"}])

    def test_a_failed_turn_keeps_the_message_and_the_reason(self):
        start()
        self.assertTrue(chat_store.fail_turn("c_1", "t_1", user_id=USER, error_code="LLM_ERROR"))
        turn = chat_store.get_turn("c_1", "t_1")
        self.assertEqual((turn["status"], turn["error_code"]), ("failed", "LLM_ERROR"))
        self.assertEqual(len(turn["messages"]), 1)

    def test_finish_adds_notes_outcomes_actions_and_suggestions(self):
        start()
        chat_store.complete_turn(
            "c_1", "t_1", user_id=USER, reply="Adding it.", intent="change", phase="refine", reads=[],
            actions=[{"type": "add_analysis", "name": "A", "source": "model", "status": "proposed"}], next_questions=[],
        )
        done = chat_store.finish_turn(
            "c_1", "t_1", user_id=USER,
            notes=[{"content": "I added it.", "kind": "notice"}],
            outcomes=[{"index": 0, "status": "applied", "entry_id": "a7"}, {"index": 9, "status": "applied"}],
            app_actions=[{"type": "navigate", "status": "applied", "page": "analysis"}],
            suggestions=[{"kind": "analysis", "entry_id": "a9", "name": "B"}],
        )
        self.assertTrue(done)
        turn = chat_store.get_turn("c_1", "t_1")
        self.assertEqual(turn["messages"][-1], {"role": "assistant", "source": "app", "kind": "notice", "content": "I added it."})
        self.assertEqual((turn["actions"][0]["status"], turn["actions"][0]["entry_id"]), ("applied", "a7"))
        self.assertEqual(len(turn["actions"]), 2)  # the out-of-range outcome is ignored
        self.assertEqual((turn["actions"][1]["source"], turn["actions"][1]["page"]), ("app", "analysis"))
        self.assertEqual(turn["suggestions"], [{"kind": "analysis", "entry_id": "a9", "name": "B", "status": "pending"}])
        self.assertEqual(turn["status"], "completed")  # the server had settled it: finish does not move it

    def test_finish_settles_a_turn_the_browser_answered_itself(self):
        start(handled_by="shortcut_suggest")
        chat_store.finish_turn("c_1", "t_1", user_id=USER, status="completed")
        self.assertEqual(chat_store.get_turn("c_1", "t_1")["status"], "completed")

    def test_finish_does_not_list_a_suggestion_twice(self):
        start(handled_by="shortcut_suggest")
        suggestion = {"kind": "analysis", "entry_id": "a9", "name": "B"}
        chat_store.finish_turn("c_1", "t_1", user_id=USER, suggestions=[suggestion])
        chat_store.finish_turn("c_1", "t_1", user_id=USER, suggestions=[suggestion])
        self.assertEqual(len(chat_store.get_turn("c_1", "t_1")["suggestions"]), 1)

    def test_a_decision_is_recorded_on_the_suggestion(self):
        start(handled_by="shortcut_suggest")
        chat_store.finish_turn("c_1", "t_1", user_id=USER, suggestions=[{"kind": "analysis", "entry_id": "a9", "name": "B"}])
        self.assertTrue(chat_store.mark_suggestion("c_1", "t_1", user_id=USER, entry_id="a9", status="rejected"))
        suggestion = chat_store.get_turn("c_1", "t_1")["suggestions"][0]
        self.assertEqual(suggestion["status"], "rejected")
        self.assertIn("decided_at", suggestion)
        self.assertFalse(chat_store.mark_suggestion("c_1", "t_1", user_id=USER, entry_id="nope", status="accepted"))

    def test_only_the_owner_may_change_a_turn(self):
        start()
        self.assertFalse(chat_store.fail_turn("c_1", "t_1", user_id=OTHER, error_code="X"))
        self.assertFalse(chat_store.finish_turn("c_1", "t_1", user_id=OTHER, notes=[{"content": "hi"}]))
        self.assertEqual(chat_store.get_turn("c_1", "t_1")["status"], "processing")

    def test_changing_a_turn_that_does_not_exist_reports_false(self):
        self.assertFalse(chat_store.fail_turn("c_1", "t_missing", user_id=USER, error_code="X"))

    def test_the_turns_of_a_chat_come_back_in_order(self):
        start(turn="t_2")
        start(turn="t_1")
        start(chat="c_other", turn="t_0")
        self.assertEqual([t["turn_id"] for t in chat_store.list_turns("c_1")], ["t_1", "t_2"])

    def test_a_turn_left_processing_for_too_long_is_reported_abandoned(self):
        old = (datetime.now(timezone.utc) - chat_store.ABANDON_AFTER - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        self.assertEqual(chat_store._present({"status": "processing", "started_at": old})["status"], "abandoned")
        fresh = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        self.assertEqual(chat_store._present({"status": "processing", "started_at": fresh})["status"], "processing")
        self.assertEqual(chat_store._present({"status": "completed", "started_at": old})["status"], "completed")

    def test_a_storage_failure_is_reported_not_raised(self):
        with mock.patch.object(chat_store, "_write", side_effect=OSError("disk full")):
            self.assertFalse(start())


class FakeDynamo:
    """Just enough of the DynamoDB client for the table's reads and writes, keeping items the way DynamoDB does."""

    class exceptions:
        class ConditionalCheckFailedException(Exception):
            pass

    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}
        self.put_calls = 0
        self.fail_next_conditional_puts = 0

    def get_item(self, TableName, Key, ConsistentRead):
        item = self.items.get((Key["chat_id"]["S"], Key["turn_id"]["S"]))
        return {"Item": item} if item else {}

    def put_item(self, TableName, Item, ConditionExpression, ExpressionAttributeValues=None):
        self.put_calls += 1
        key = (Item["chat_id"]["S"], Item["turn_id"]["S"])
        current = self.items.get(key)
        if ConditionExpression == "attribute_not_exists(turn_id)":
            ok = current is None
        else:
            ok = current is not None and current["updated_at"] == ExpressionAttributeValues[":old"]
        if ok and self.fail_next_conditional_puts and current is not None:
            self.fail_next_conditional_puts -= 1
            ok = False  # somebody else changed the turn between our read and our write
        if not ok:
            raise self.exceptions.ConditionalCheckFailedException()
        self.items[key] = Item

    def query(self, TableName, ConsistentRead, KeyConditionExpression, ExpressionAttributeValues, **_):
        chat = ExpressionAttributeValues[":c"]["S"]
        return {"Items": [item for (c, _t), item in sorted(self.items.items()) if c == chat]}


class DynamoBackendTest(unittest.TestCase):
    def setUp(self):
        self.ddb = FakeDynamo()
        for patch in (
            mock.patch.object(chat_store, "DDB_CHATS", "uda327-chats-test"),
            mock.patch("app.services.common.aws_clients.dynamodb", return_value=self.ddb),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_a_turn_round_trips_with_plain_numbers(self):
        start(session_id="s_1")
        turn = chat_store.get_turn("c_1", "t_1")
        self.assertEqual(turn["session_id"], "s_1")
        self.assertIsInstance(turn["ttl"], int)
        self.assertIsInstance(turn["schema_version"], int)

    def test_items_are_stored_with_native_types_and_no_empty_index_keys(self):
        start()
        raw = self.ddb.items[("c_1", "t_1")]
        self.assertEqual(raw["messages"]["L"][0]["M"]["role"], {"S": "user"})
        self.assertNotIn("session_id", raw)
        self.assertEqual(TypeDeserializer().deserialize(raw["schema_version"]), Decimal(chat_store.SCHEMA_VERSION))

    def test_start_is_conditional_so_a_retry_cannot_overwrite(self):
        self.assertTrue(start())
        self.assertFalse(start(user_text="other"))
        self.assertEqual(chat_store.get_turn("c_1", "t_1")["messages"][0]["content"], "Explain Transit Days.")

    def test_a_change_that_lost_a_race_is_retried_on_fresh_data(self):
        start()
        self.ddb.fail_next_conditional_puts = 1
        with mock.patch.object(chat_store.time, "sleep"):
            self.assertTrue(chat_store.fail_turn("c_1", "t_1", user_id=USER, error_code="LLM_ERROR"))
        self.assertEqual(chat_store.get_turn("c_1", "t_1")["status"], "failed")

    def test_giving_up_after_repeated_conflicts_reports_false(self):
        start()
        self.ddb.fail_next_conditional_puts = 99
        with mock.patch.object(chat_store.time, "sleep"):
            self.assertFalse(chat_store.fail_turn("c_1", "t_1", user_id=USER, error_code="X"))

    def test_the_turns_of_a_chat_are_queried_in_order(self):
        start(turn="t_2")
        start(turn="t_1")
        self.assertEqual([t["turn_id"] for t in chat_store.list_turns("c_1")], ["t_1", "t_2"])


if __name__ == "__main__":
    unittest.main()
