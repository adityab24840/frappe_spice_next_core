"""Card OCR DocTypes against a real site (run with: bench --site <site> run-tests --module spice_next_core.tests.test_card_ocr_doctypes).
Frappe rolls the data back after each test case."""

import frappe
from frappe.tests import IntegrationTestCase


class TestCardOCR(IntegrationTestCase):
	def _card(self, key="smoke_card"):
		return frappe.get_doc({"doctype": "OCR Card Type", "card_key": key, "title": "Smoke card", "fields": [
			{"key": "weight_kg", "kind": "number", "layout": "single", "range_low": 30, "range_high": 150, "decode": "grammar"},
			{"key": "visit_date", "kind": "date", "layout": "stacked"},
		]}).insert(ignore_permissions=True)

	def _scan(self, card, page="p-001", writer="W07"):
		return frappe.get_doc({"doctype": "OCR Scan", "card_type": card, "page": page, "writer": writer}).insert(ignore_permissions=True)

	def _cell(self, scan, visit="c1", **kw):
		return frappe.get_doc({"doctype": "OCR Cell", "scan": scan, "field_key": "weight_kg", "visit": visit, **kw})

	def test_valid_card_type_saves(self):
		self.assertEqual(self._card().name, "smoke_card")

	def test_stacked_number_is_refused(self):
		doc = frappe.get_doc({"doctype": "OCR Card Type", "card_key": "bad", "title": "Bad", "fields": [{"key": "w", "kind": "number", "layout": "stacked"}]})
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_a_writer_name_is_refused(self):
		card = self._card()
		with self.assertRaises(frappe.ValidationError):
			self._scan(card.name, writer="Aditya Bhatt")

	def test_label_is_normalised_and_how_is_derived(self):
		scan = self._scan(self._card().name)
		cell = self._cell(scan.name, label="৫৭", ai_text="57").insert(ignore_permissions=True)
		self.assertEqual((cell.label, cell.how), ("57", "accepted"))

	def test_corrected_when_it_differs_from_the_suggestion(self):
		scan = self._scan(self._card().name)
		cell = self._cell(scan.name, label="58", ai_text="57").insert(ignore_permissions=True)
		self.assertEqual(cell.how, "corrected")

	def test_out_of_range_saves_with_a_warning(self):
		scan = self._scan(self._card().name)
		cell = self._cell(scan.name, label="7").insert(ignore_permissions=True)
		self.assertIn("outside the expected range", cell.warning)

	def test_disallowed_character_is_refused(self):
		scan = self._scan(self._card().name)
		with self.assertRaises(frappe.ValidationError):
			self._cell(scan.name, label="5x").insert(ignore_permissions=True)

	def test_unknown_field_is_refused(self):
		scan = self._scan(self._card().name)
		doc = frappe.get_doc({"doctype": "OCR Cell", "scan": scan.name, "field_key": "nope", "visit": "c1", "label": "1"})
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_pack_trained_on_unverified_reads_cannot_ship(self):
		card = self._card()
		pack = frappe.get_doc({"doctype": "OCR Card Pack", "card_type": card.name, "version": 1, "pack_file": "/private/files/x.cardpack",
			"status": "Shipped", "trained_on": "ai-read (unverified)"})
		with self.assertRaises(frappe.ValidationError):
			pack.insert(ignore_permissions=True)

	def test_pack_file_must_be_a_cardpack(self):
		card = self._card()
		pack = frappe.get_doc({"doctype": "OCR Card Pack", "card_type": card.name, "version": 1, "pack_file": "/private/files/x.zip", "status": "Draft"})
		with self.assertRaises(frappe.ValidationError):
			pack.insert(ignore_permissions=True)
