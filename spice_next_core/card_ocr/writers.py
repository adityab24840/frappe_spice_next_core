"""Who wrote each card. A writer is a code (W07, a clinic id), never a name. Used to keep every page of one writer on one side of a train/test split, so a
reader is tested on people it never trained on. Port of Card Studio's cards.writers / set_writers / writer_status."""
import frappe
from frappe import _

from spice_next_core.card_ocr import rules

MIN_WRITER_UNITS = 5       # a writer-disjoint 5-fold split needs at least this many writers


def pages(card_type):
	"""[{scan, page, writer, labeled}] in page order."""
	labeled = {}
	for r in frappe.get_all("OCR Cell", filters={"card_type": card_type, "label": ["is", "set"]}, fields=["scan"]):
		labeled[r.scan] = labeled.get(r.scan, 0) + 1
	rows = frappe.get_all("OCR Scan", filters={"card_type": card_type}, fields=["name", "page", "writer"], order_by="page asc")
	return [{"scan": r.name, "page": r.page, "writer": r.writer or "", "labeled": labeled.get(r.name, 0)} for r in rows]


def status(card_type):
	"""-> {pages, with_writer, writers, split_by, message}. The split is by writer only when every labelled page has one and there are enough writers."""
	rows = pages(card_type)
	lab = [r for r in rows if r["labeled"]]
	with_w = [r for r in lab if r["writer"]]
	writers = {r["writer"] for r in with_w}
	by_writer = bool(lab) and len(with_w) == len(lab) and len(writers) >= MIN_WRITER_UNITS
	if not lab:
		msg = _("No labelled pages yet.")
	elif by_writer:
		msg = _("All {0} labelled pages have a writer: a train/test split keeps each of the {1} writers on one side.").format(len(lab), len(writers))
	elif with_w:
		msg = _("{0} of {1} labelled pages have a writer ({2} writers). The split is by page until every labelled page has one and there are at least {3} writers.").format(len(with_w), len(lab), len(writers), MIN_WRITER_UNITS)
	else:
		msg = _("No labelled page has a writer, so the split is by page: a writer who appears in both halves makes the held-out numbers optimistic.")
	return {"pages": len(rows), "labeled_pages": len(lab), "with_writer": len(with_w), "writers": sorted(writers), "split_by": "writer" if by_writer else "page", "message": msg, "rows": rows}


def assign(card_type, writer, first=None, last=None, page_list=None):
	"""Say that `writer` wrote the pages from `first` to `last` (page ids, inclusive, in page order) or the listed pages. An empty writer clears them.
	-> {set}."""
	problem = rules.writer_problem(writer or "")
	if problem:
		frappe.throw(_(problem))
	rows = pages(card_type)
	if page_list:
		want = set(page_list)
	else:
		names = [r["page"] for r in rows]
		if first not in names or last not in names:
			frappe.throw(_("First and last must be page ids of this card (for example p-001)."))
		a, b = names.index(first), names.index(last)
		want = set(names[min(a, b): max(a, b) + 1])
	n = 0
	for r in rows:
		if r["page"] in want:
			frappe.db.set_value("OCR Scan", r["scan"], "writer", writer or "", update_modified=False)
			n += 1
	return {"set": n}
