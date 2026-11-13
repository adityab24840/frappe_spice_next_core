import frappe
from frappe import _
from frappe.model.document import Document

from spice_next_core.card_ocr.engine import extreader


class OCRExternalModel(Document):
	def validate(self):
		if not extreader.NAME.match(self.model_key or ""):
			frappe.throw(_("Model name: letters, digits, _ or - (at most 40)."))
