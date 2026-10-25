"""strip_json_fence: every agent reads the model's JSON through it, so it must find the first JSON value
whatever the model wrote around it (fences, a sentence, or a second object after the first)."""
import json
import unittest

from app.services.common.llm import strip_json_fence


def parsed(text):
    return json.loads(strip_json_fence(text))


class StripJsonFenceTest(unittest.TestCase):
    def test_plain_json_is_unchanged(self):
        self.assertEqual(parsed('{"a": 1}'), {"a": 1})

    def test_a_fenced_block(self):
        self.assertEqual(parsed('```json\n{"a": 1}\n```'), {"a": 1})

    def test_prose_before_and_after(self):
        self.assertEqual(parsed('Here is the plan: {"a": 1, "b": [1, 2]} Hope that helps.'), {"a": 1, "b": [1, 2]})

    def test_a_fenced_block_with_prose_around_it(self):
        self.assertEqual(parsed('Sure.\n```json\n{"a": 1}\n```\nLet me know.'), {"a": 1})

    # The failure seen in the analysis designer: "json.decoder.JSONDecodeError: Extra data".
    def test_a_second_object_after_the_first_is_ignored(self):
        self.assertEqual(parsed('{"steps": ["a"]}\n{"note": "second"}'), {"steps": ["a"]})

    def test_a_trailing_sentence_with_braces_is_ignored(self):
        self.assertEqual(parsed('{"a": 1}\nNote: the {value} may differ.'), {"a": 1})

    def test_two_fenced_objects_give_the_first(self):
        self.assertEqual(parsed('```json\n{"a": 1}\n```\n```json\n{"b": 2}\n```'), {"a": 1})

    def test_extra_data_inside_one_fence(self):
        self.assertEqual(parsed('```json\n{"a": 1}\n{"b": 2}\n```'), {"a": 1})

    def test_an_array_is_found(self):
        self.assertEqual(parsed('Result: [1, 2, 3] done'), [1, 2, 3])

    def test_stray_braces_before_the_json_are_skipped(self):
        self.assertEqual(parsed('Use {placeholders} like so: {"a": 1}'), {"a": 1})

    def test_nested_objects_stay_whole(self):
        self.assertEqual(parsed('{"a": {"b": {"c": 1}}} trailing'), {"a": {"b": {"c": 1}}})

    def test_text_with_no_json_is_returned_unchanged(self):
        self.assertEqual(strip_json_fence("no json here"), "no json here")
        self.assertEqual(strip_json_fence(""), "")

    def test_unreadable_json_is_left_for_the_caller_to_report(self):
        broken = '{"a": 1,'
        self.assertEqual(strip_json_fence(broken), broken)
        with self.assertRaises(ValueError):
            json.loads(strip_json_fence(broken))

    def test_a_long_answer_with_many_stray_braces_does_not_scan_forever(self):
        text = "{ " * 5000 + "not json"
        self.assertEqual(strip_json_fence(text), text.strip())


if __name__ == "__main__":
    unittest.main()
