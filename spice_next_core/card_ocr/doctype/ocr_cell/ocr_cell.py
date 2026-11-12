import frappe
from frappe import _
from frappe.model.document import Document

from spice_next_core.card_ocr import rules


class OCRCell(Document):
	def validate(self):
		if not rules.KEY.match(self.field_key or "") or not rules.VISIT.match(self.visit or ""):
			frappe.throw(_("Field is letters, digits and _; visit looks like c1."))
		spec = self._field_spec()
		if not (self.label or "").strip() and not self.note:
			self.label, self.warning = "", ""          # a cell nobody has labelled yet: nothing to check
			return
		label, err, warn = rules.check_cell(
			spec.kind if spec else "text", self.label, self.note or "", self.field_key, self._range(spec), self.how or ""
		)
		if err:
			frappe.throw(err)
		self.label = label
		self.warning = warn or ""
		if self.label and not self.how:
			self.how = "typed" if not self.ai_text else ("accepted" if self.ai_text == self.label else "corrected")

	def _field_spec(self):
		card = self.card_type or frappe.db.get_value("OCR Scan", self.scan, "card_type")
		if not card:
			return None
		for f in frappe.get_doc("OCR Card Type", card).fields:
			if f.key == self.field_key:
				return f
		frappe.throw(_("{0} is not a field of card {1}.").format(self.field_key, card))

	@staticmethod
	def _range(spec):
		if spec and spec.range_low is not None and spec.range_high is not None and (spec.range_low or spec.range_high):
			return (spec.range_low, spec.range_high)
		return None
