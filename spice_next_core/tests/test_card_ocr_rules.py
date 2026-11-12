"""Unit tests for card_ocr/rules.py. No Frappe, no database."""

import unittest

from spice_next_core.card_ocr import rules


class Normalize(unittest.TestCase):
	def test_bangla_digits_become_ascii(self):
		self.assertEqual(rules.normalize("২৬/৮"), "26/8")

	def test_whitespace_is_squeezed(self):
		self.assertEqual(rules.normalize("  12   5 "), "12 5")


class Labels(unittest.TestCase):
	def test_character_the_field_cannot_emit_is_an_error(self):
		err, warn = rules.check_label("number", "12x", "weight_kg")
		self.assertIn("cannot hold", err)

	def test_clean_number_has_no_message(self):
		self.assertEqual(rules.check_label("number", "57", "weight_kg", (30, 150)), (None, None))

	def test_number_outside_range_is_a_warning(self):
		err, warn = rules.check_label("number", "7", "weight_kg", (30, 150))
		self.assertIsNone(err)
		self.assertIn("outside the expected range", warn)

	def test_date_with_impossible_month_warns(self):
		self.assertIn("real day and month", rules.check_label("date", "12/13/26", "visit_date")[1])

	def test_date_without_year_warns_about_shape(self):
		self.assertIn("day, month, year", rules.check_label("date", "12/3", "visit_date")[1])

	def test_bp_shape(self):
		self.assertEqual(rules.check_label("bp", "120/80", "bp"), (None, None))
		self.assertIn("systolic/diastolic", rules.check_label("bp", "120", "bp")[1])

	def test_mark_accepts_tick_cross_dash(self):
		for m in ("y", "x", "-"):
			self.assertEqual(rules.check_label("mark", m, "edema"), (None, None))

	def test_dash_is_allowed_for_non_mark_fields(self):
		self.assertEqual(rules.check_label("number", "-", "weight_kg"), (None, None))


class Cells(unittest.TestCase):
	def test_blank_note_stores_no_label(self):
		self.assertEqual(rules.check_cell("number", "57", "blank"), ("", None, None))

	def test_empty_label_without_note_is_an_error(self):
		self.assertIn("type what the cell says", rules.check_cell("number", "", "")[1])

	def test_bad_note_and_bad_how_are_refused(self):
		self.assertIn("note must be", rules.check_cell("number", "1", "maybe")[1])
		self.assertIn("how must be", rules.check_cell("number", "1", "", how="guess")[1])

	def test_label_too_long(self):
		self.assertIn("longer than", rules.check_cell("text", "x" * 41, "")[1])

	def test_label_is_normalized(self):
		self.assertEqual(rules.check_cell("number", "৫৭", "")[0], "57")


class FieldSpecs(unittest.TestCase):
	def test_valid_spec(self):
		self.assertIsNone(rules.check_field_spec("weight_kg", "number", "single", "grammar", 30, 150))

	def test_stacked_must_be_a_date(self):
		self.assertIn("does not fit", rules.check_field_spec("w", "number", "stacked"))

	def test_diagonal_must_be_bp(self):
		self.assertIn("does not fit", rules.check_field_spec("w", "date", "diagonal"))

	def test_grammar_needs_a_one_line_ranged_number(self):
		self.assertIn("decode grammar", rules.check_field_spec("w", "number", "single", "grammar"))
		self.assertIn("decode grammar", rules.check_field_spec("d", "date", "stacked", "grammar"))

	def test_half_range_is_refused(self):
		self.assertIn("both ends", rules.check_field_spec("w", "number", "single", "greedy", 1, None))

	def test_inverted_range_is_refused(self):
		self.assertIn("above", rules.check_field_spec("w", "number", "single", "greedy", 9, 1))

	def test_bad_key(self):
		self.assertIn("letters, digits", rules.check_field_spec("bad key!", "number"))


class Writers(unittest.TestCase):
	def test_code_ok_name_refused(self):
		self.assertIsNone(rules.writer_problem("W07"))
		self.assertIsNone(rules.writer_problem(""))
		self.assertIn("never a name", rules.writer_problem("Aditya Bhatt"))


if __name__ == "__main__":
	unittest.main()
