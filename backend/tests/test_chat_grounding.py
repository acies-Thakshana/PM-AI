"""The check that the figures in a reply come from the data the assistant was shown."""
import unittest

from app.services.chat.grounding import numbers_in, ungrounded_figures


class NumbersInTest(unittest.TestCase):
    def test_reads_plain_decimal_percent_and_thousands(self):
        self.assertEqual(numbers_in("1,234 trips, 12.5 days, 87% in range, -3.2 C"), [1234.0, 12.5, 87.0, -3.2])

    def test_ignores_digits_inside_words(self):
        self.assertEqual(numbers_in("Carrier A2 and v3.1b"), [])


class UngroundedFiguresTest(unittest.TestCase):
    EVIDENCE = '{"rows": 303, "mean_days": 12.3456, "share": 0.87, "top": [{"carrier": "A", "alarms": 1450}]}'

    def test_a_figure_that_is_in_the_evidence_is_fine(self):
        self.assertEqual(ungrounded_figures("There are 303 trips and 1,450 alarms for carrier A.", self.EVIDENCE), [])

    def test_a_rounded_figure_is_fine(self):
        self.assertEqual(ungrounded_figures("The mean is 12.35 days.", self.EVIDENCE), [])
        self.assertEqual(ungrounded_figures("About 12.3 days.", self.EVIDENCE), [])

    def test_a_share_stored_as_a_fraction_may_be_said_as_a_percent(self):
        self.assertEqual(ungrounded_figures("87% of trips stayed in range.", self.EVIDENCE), [])

    def test_an_invented_figure_is_reported(self):
        self.assertEqual(ungrounded_figures("Carrier A had 2,310 alarms and 45.5% were late.", self.EVIDENCE), ["2,310", "45.5%"])

    def test_small_whole_numbers_are_words_not_results(self):
        self.assertEqual(ungrounded_figures("I added 2 analyses; see step 3 on page 4.", ""), [])

    def test_years_are_not_figures(self):
        self.assertEqual(ungrounded_figures("Shipments from 2025 to 2026.", ""), [])

    def test_a_figure_is_reported_once(self):
        self.assertEqual(ungrounded_figures("It is 99.9% and again 99.9%.", ""), ["99.9%"])

    def test_the_conversation_counts_as_evidence(self):
        self.assertEqual(ungrounded_figures("Here are the top 10 carriers.", "PM: show me the top 10 carriers"), [])
        self.assertEqual(ungrounded_figures("Over 500 trips.", "PM: only look at trips over 500"), [])


if __name__ == "__main__":
    unittest.main()
