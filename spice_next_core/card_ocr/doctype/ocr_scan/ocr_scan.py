import frappe
from frappe import _
from frappe.model.document import Document

from spice_next_core.card_ocr import rules


class OCRScan(Document):
	def validate(self):
		problem = rules.writer_problem(self.writer)
		if problem:
			frappe.throw(_(problem))
		if self.source_image and not self.is_private_file(self.source_image):
			frappe.throw(_("The source photo is patient data: attach it as a private file."))

	@staticmethod
	def is_private_file(file_url):
		return str(file_url).startswith("/private/")
