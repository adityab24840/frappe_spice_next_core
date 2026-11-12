import frappe
from frappe import _
from frappe.model.document import Document


class OCRCardPack(Document):
	def validate(self):
		if not str(self.pack_file or "").endswith(".cardpack"):
			frappe.throw(_("The pack file must be a .cardpack file."))
		if self.status == "Shipped" and self.trained_on in ("", None, "ai-read (unverified)"):
			frappe.throw(_("A pack trained on unverified machine reads cannot be marked Shipped. Say what it was trained on, from human-verified labels."))
