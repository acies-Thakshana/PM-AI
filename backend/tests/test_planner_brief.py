"""Which client brief the Planner plans from: the one the PM gave in the chat, otherwise the Configure page's."""
import unittest
from unittest import mock

from app.services.planner import planner


def _with_interview(record):
    return mock.patch.object(planner.doc_store, "get", return_value=record)


class ChatBriefTests(unittest.TestCase):
    def test_a_brief_given_in_the_chat_is_used(self):
        with _with_interview({"brief": "  Carrier compliance for Q3.  ", "brief_source": "chat"}):
            self.assertEqual(planner._chat_brief("s1"), "Carrier compliance for Q3.")

    def test_the_configure_page_brief_is_left_to_the_brief_document(self):
        with _with_interview({"brief": "From the Configure page.", "brief_source": "upload"}):
            self.assertEqual(planner._chat_brief("s1"), "")

    def test_no_interview_or_an_old_record_means_no_chat_brief(self):
        with _with_interview(None):
            self.assertEqual(planner._chat_brief("s1"), "")
        with _with_interview({"brief": "Old record without a source."}):
            self.assertEqual(planner._chat_brief("s1"), "")


if __name__ == "__main__":
    unittest.main()
