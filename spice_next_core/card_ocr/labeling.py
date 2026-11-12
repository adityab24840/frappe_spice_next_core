"""Labelling API for the OCR Labeling page: what is left to label, and saving what a person says a cell holds.

A suggestion is never a label. A label records how it came to be (typed / accepted / corrected / ai-read / phone) so a person's work can be told
apart from machine reads: the overview counts them separately, and only human-verified labels (typed, accepted, corrected) count as ground truth.
"""
import frappe
from frappe import _

from spice_next_core.card_ocr import rules

ROLES = ("System Manager", "OCR Labeler")
HUMAN = ("typed", "accepted", "corrected")
SHOWS = ("todo", "ai-read", "done", "disagree", "phone", "all")
MAX_LIMIT = 100


def _need_role():
	if not set(ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


@frappe.whitelist(methods=["GET"])
def cards():
	"""Card types a person can label: [{card_key, title, fields: [keys]}]."""
	_need_role()
	out = []
	for c in frappe.get_all("OCR Card Type", fields=["name", "title"], order_by="title asc"):
		keys = [f.key for f in frappe.get_doc("OCR Card Type", c.name).fields if f.kind != "text"]
		out.append({"card_key": c.name, "title": c.title, "fields": keys})
	return out


@frappe.whitelist(methods=["GET"])
def overview(card_type):
	"""Per field: cells with ink, human-verified labels, machine reads still unverified, blank/unreadable, and cells left to label."""
	_need_role()
	rows = frappe.get_all(
		"OCR Cell", filters={"card_type": card_type, "has_ink": 1},
		fields=["field_key", "label", "note", "how", "ai_text", "scan"],
	)
	pages = {s.name: s.page for s in frappe.get_all("OCR Scan", filters={"card_type": card_type}, fields=["name", "page"])}
	labeled_pages = set()
	per = {}
	for f in frappe.get_doc("OCR Card Type", card_type).fields:       # every field of the card, even one with no inked cell yet
		per[f.key] = {"cells": 0, "human": 0, "ai_read": 0, "blank_or_unreadable": 0, "todo": 0, "suggested": 0, "ai_right": 0, "ai_checked": 0,
			"kind": f.kind, "layout": f.layout or "single"}
	for r in rows:
		if r.field_key not in per:
			continue
		p = per[r.field_key]
		p["cells"] += 1
		if r.label and r.how in HUMAN:
			labeled_pages.add(pages.get(r.scan))
			if r.ai_text:                       # the AI suggested something and a person decided: how often it was right
				p["ai_checked"] += 1
				p["ai_right"] += 1 if r.ai_text == r.label else 0
		p["suggested"] += 1 if r.ai_text else 0
		if r.note:
			p["blank_or_unreadable"] += 1
		elif r.label and r.how in HUMAN:
			p["human"] += 1
		elif r.label:
			p["ai_read"] += 1  # an unverified machine read or a phone correction: not ground truth yet
		else:
			p["todo"] += 1
	total = {k: sum(p[k] for p in per.values()) for k in ("cells", "human", "ai_read", "blank_or_unreadable", "todo")}
	total["pages"] = len(labeled_pages - {None})
	return {"fields": per, "total": total}


@frappe.whitelist(methods=["GET"])
def queue(card_type, field=None, show="todo", limit=24, least_sure_first=1):
	"""The next cells to look at. show: todo (no label yet), ai-read (machine reads awaiting a person), done, all.
	Cells with an AI suggestion come with it; least_sure_first puts low-confidence suggestions first (those are the ones a person must really check)."""
	_need_role()
	if show not in SHOWS:
		frappe.throw(_("show must be one of {0}").format(", ".join(SHOWS)))
	limit = max(1, min(int(limit), MAX_LIMIT))
	filters = {"card_type": card_type, "has_ink": 1}
	if field:
		if not rules.KEY.match(field):
			frappe.throw(_("Bad field"))
		filters["field_key"] = field
	rows = frappe.get_all(
		"OCR Cell", filters=filters, order_by="modified asc",
		fields=["name", "scan", "field_key", "visit", "crop", "ai_text", "ai_confidence", "ai_source", "ai_suggestion", "ai_note", "label", "note", "how", "warning"],
	)

	def keep(r):
		if show == "all":
			return True
		if show == "todo":
			return not r.label and not r.note
		if show == "ai-read":
			return bool(r.label) and r.how not in HUMAN
		if show == "disagree":                      # a person decided differently from the AI suggestion
			return bool(r.label and r.ai_text) and r.how in HUMAN and r.label != r.ai_text
		if show == "phone":                         # corrections that came from the phone app, to look over
			return bool(r.label) and r.how == "phone"
		return bool(r.label or r.note) and r.how in HUMAN or bool(r.note)

	rows = [r for r in rows if keep(r)]
	if int(least_sure_first):
		rows.sort(key=lambda r: (r.ai_confidence is None, r.ai_confidence if r.ai_confidence is not None else 1.0))
	units = {}
	for r in rows[:limit]:
		units[r.scan] = units.get(r.scan) or frappe.db.get_value("OCR Scan", r.scan, ["page", "writer"], as_dict=True)
	return {"left": len(rows), "cells": [{**r, "page": units[r.scan].page, "writer": units[r.scan].writer} for r in rows[:limit]]}


@frappe.whitelist(methods=["POST"])
def save(cell, label="", note="", confirm=0):
	"""Record what one cell says. note "blank" / "unreadable" stores no label. A label with a warning (a weight outside its range, a date with no
	month) is not saved until the same call is repeated with confirm=1, because a typo is the usual reason for a warning.
	-> {saved, label, note, warning, how}"""
	_need_role()
	doc = frappe.get_doc("OCR Cell", cell)
	doc.label, doc.note = rules.normalize(label), note or ""
	doc.how = ""  # re-derived from the suggestion: a person's work is never recorded as a machine read
	if doc.note:
		doc.label = ""
	doc.validate()
	if doc.warning and not int(confirm):
		return {"saved": False, "label": doc.label, "note": doc.note, "warning": doc.warning, "how": doc.how}
	if doc.note:
		doc.how = "typed"
	doc.save()
	return {"saved": True, "label": doc.label, "note": doc.note, "warning": doc.warning, "how": doc.how}


@frappe.whitelist(methods=["POST"])
def clear(cell):
	"""Take a label back: the cell returns to the queue."""
	_need_role()
	doc = frappe.get_doc("OCR Cell", cell)
	doc.label = doc.note = doc.how = doc.warning = ""
	doc.save()
	return {"cleared": True}
