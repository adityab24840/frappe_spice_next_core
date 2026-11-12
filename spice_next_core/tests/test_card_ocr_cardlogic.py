"""Card-level checks: same-day dose columns (EPI) and increasing visit dates (ANC)."""
import unittest
from unittest import mock

import numpy as np

from spice_next_core.card_ocr.engine import cardlogic as L
from spice_next_core.card_ocr.engine import reader, twoline, vision

EPI = ["bcg", "penta", "opv", "pcv"]


class DateKey(unittest.TestCase):
    def test_real_dates_only(self):
        self.assertEqual(L.date_key("22/2/26"), (22, 2, 2026)); self.assertEqual(L.date_key("02.03.2026"), (2, 3, 2026)); self.assertEqual(L.date_key(" 29/2/24 "), (29, 2, 2024))
        for bad in ("", None, "31/4/26", "29/2/25", "22/13/26", "0/1/26", "22/2", "22/2/2", "12/80"): self.assertIsNone(L.date_key(bad), bad)


class SameDay(unittest.TestCase):
    def test_a_dissenting_cell_gets_the_majority_date_as_a_suggestion_and_keeps_its_read(self):
        reads = {("bcg", 2): "22/2/26", ("penta", 2): "22.2.26", ("opv", 2): "22/2/26", ("pcv", 2): "23/2/26"}
        f = L.same_day(reads, EPI)
        self.assertEqual([(x["field"], x["visit"], x["suggestion"]) for x in f], [("pcv", 2, "22/2/26")])
        self.assertIn("23/2/26", f[0]["note"])

    def test_not_a_date_is_corrected_too_but_a_blank_cell_is_left_alone(self):
        reads = {("bcg", 1): "5/3/26", ("penta", 1): "5/3/26", ("opv", 1): "0/3/26", ("pcv", 1): ""}
        self.assertEqual([x["field"] for x in L.same_day(reads, EPI)], ["opv"])

    def test_a_tie_or_a_single_date_decides_nothing(self):
        self.assertEqual(L.same_day({("bcg", 1): "5/3/26", ("penta", 1): "6/3/26"}, EPI), [])
        self.assertEqual(L.same_day({("bcg", 1): "5/3/26", ("penta", 1): "5/3/26", ("opv", 1): "6/3/26", ("pcv", 1): "6/3/26"}, EPI), [])
        self.assertEqual(L.same_day({("bcg", 1): "5/3/26", ("penta", 1): "garbage"}, EPI), [])

    def test_visits_are_judged_apart_and_weak_cells_do_not_vote(self):
        reads = {("bcg", 1): "5/3/26", ("penta", 1): "5/3/26", ("opv", 1): "9/9/26", ("bcg", 2): "7/4/26", ("penta", 2): "7/4/26", ("opv", 2): "7/4/26"}
        self.assertEqual([(x["field"], x["visit"]) for x in L.same_day(reads, EPI)], [("opv", 1)])
        self.assertEqual(L.same_day(reads, EPI, weak={("penta", 1)}), [])           # only one trusted vote left in visit 1
        self.assertEqual(L.same_day(reads, ["bcg"]), [])                              # a rule needs at least two fields

    def test_fields_the_rule_does_not_name_are_ignored(self):
        self.assertEqual(L.same_day({("bcg", 1): "5/3/26", ("penta", 1): "5/3/26", ("weight", 1): "9/9/26"}, "bcg, penta"), [])


class Increasing(unittest.TestCase):
    def test_an_earlier_visit_date_is_noted_and_nothing_is_suggested(self):
        reads = {("visit_date", 1): "10/1/26", ("visit_date", 2): "2/2/26", ("visit_date", 3): "1/2/26", ("visit_date", 4): "9/3/26"}
        f = L.increasing(reads, ["visit_date"])
        self.assertEqual([(x["visit"], x["suggestion"]) for x in f], [(3, None)]); self.assertIn("visit 2", f[0]["note"])

    def test_year_rolls_over_blank_and_unreadable_visits_are_skipped_equal_dates_pass(self):
        reads = {("visit_date", 1): "20/12/25", ("visit_date", 2): "", ("visit_date", 3): "junk", ("visit_date", 4): "5/1/26", ("visit_date", 5): "5/1/26"}
        self.assertEqual(L.increasing(reads, "visit_date"), [])

    def test_check_runs_both(self):
        reads = {("bcg", 1): "5/3/26", ("penta", 1): "5/3/26", ("opv", 1): "6/3/26", ("visit_date", 1): "9/1/26", ("visit_date", 2): "8/1/26"}
        self.assertEqual([x["rule"] for x in L.check(reads, {"same_day": EPI, "increasing": "visit_date"})], ["same_day", "increasing"])
        self.assertEqual(L.check(reads, None), [])



class StackedDate(unittest.TestCase):
	"""A date written on two lines: the top line is read against the days each month has when the field says grammar, and the two lines must name a real day."""

	def _reader(self, decode):
		r = reader.Reader.__new__(reader.Reader)
		r.classes = ["<b>"] + list("0123456789/.-")
		r.blank = 0
		r.spec = {"bcg": {"kind": "date", "layout": "stacked", "decode": decode, "allowed_idx": list(range(len(r.classes)))}}
		return r

	def _frames(self, classes, text):
		out = []
		for ch in text:
			for hot in (classes.index(ch), 0):
				z = np.full(len(classes), -8.0)
				z[hot] = 6.0
				out.append(z)
		return np.stack(out)

	def _read(self, decode, top, year):
		r = self._reader(decode)
		logits = iter([self._frames(r.classes, top), self._frames(r.classes, year)])
		r.logits = lambda px: next(logits)
		with mock.patch.object(twoline, "parts", lambda crop, layout: (np.zeros((48, 192), np.uint8),) * 2), mock.patch.object(vision, "prepare", lambda p: p):
			return r.read(np.zeros((40, 60), np.uint8), "bcg")

	def test_a_real_day_keeps_its_confidence_and_a_leap_day_without_a_leap_year_is_flagged(self):
		text, conf = self._read("greedy", "22.2", "26")
		self.assertEqual(text, "22/2/26")
		self.assertGreater(conf, 0.5)
		text, conf = self._read("greedy", "29.2", "25")
		self.assertEqual(text, "29/2/25")
		self.assertLessEqual(conf, reader.UNREAL_DATE_CONFIDENCE)

	def test_grammar_pulls_an_impossible_top_line_to_a_real_one(self):
		self.assertEqual(self._read("greedy", "31.4", "26")[0], "31/4/26")      # April has 30 days: greedy keeps what it saw
		text, _ = self._read("grammar", "31.4", "26")
		top = text.rsplit("/", 1)[0]
		self.assertNotEqual(top, "31/4")
		from spice_next_core.card_ocr.engine import grammar

		self.assertTrue(grammar.date_ok(top, "26"), text)
		self.assertEqual(self._read("grammar", "22.2", "26")[0], "22/2/26")


if __name__ == "__main__":
    unittest.main()
