import frappe
from frappe import _
from frappe.model.document import Document

from spice_next_core.card_ocr import rules


class OCRCardType(Document):
	def validate(self):
		if not rules.CARD_KEY.match(self.card_key or ""):
			frappe.throw(_("Card key is letters, digits, _ and - (at most 40)."))
		seen = set()
		for f in self.fields or []:
			low = f.range_low if f.range_high is not None and f.range_low is not None else None
			high = f.range_high if low is not None else None
			err = rules.check_field_spec(f.key, f.kind, f.layout or "single", f.decode or "greedy", low, high)
			if err:
				frappe.throw(err)
			if f.key in seen:
				frappe.throw(_("Field {0} is listed twice.").format(f.key))
			seen.add(f.key)
		from spice_next_core.card_ocr.engine import cardlogic

		for label, name in (("Dates usually written on the same day", "same_day_fields"), ("Dates that must go up", "increasing_fields")):
			names = cardlogic.parse_fields(self.get(name))
			unknown = [n for n in names if n not in seen]
			if unknown and seen:
				frappe.throw(_("{0}: {1} is not a field of this card type.").format(_(label), ", ".join(unknown)))
			if name == "same_day_fields" and names and len(names) < 2:
				frappe.throw(_("{0}: name at least two fields.").format(_(label)))
