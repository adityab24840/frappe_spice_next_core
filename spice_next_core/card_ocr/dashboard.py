"""Data for the Card Studio dashboard page: stat tiles, the model registry, and the getting-started checklist."""
import json

import frappe
from frappe import _

ROLES = ("System Manager", "OCR Labeler")
HUMAN = ("typed", "accepted", "corrected", "phone")
MIN_PAGES = 10


def _has_tflite(pack_file):
	"""Does the pack carry a TensorFlow Lite reader (the phone's engine choice)? Lists the zip's members only."""
	import io
	import zipfile

	try:
		name = frappe.db.get_value("File", {"file_url": pack_file})
		return "reader.tflite" in zipfile.ZipFile(io.BytesIO(frappe.get_doc("File", name).get_content())).namelist()
	except Exception:
		return False


def _latest_results(card):
	run = frappe.get_all("OCR Training Run", filters={"card_type": card, "status": "Done"}, fields=["name", "results", "cv_exact", "creation"], order_by="creation desc", limit=1)
	if not run:
		return None, None
	try:
		return run[0], json.loads(run[0].results) if run[0].results else {}
	except ValueError:
		return run[0], {}


@frappe.whitelist(methods=["GET"])
def dashboard():
	if not set(ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	cards = frappe.get_all("OCR Card Type", fields=["name", "title", "status", "template_image", "grid_json"], order_by="title asc")
	registry, shipped_total, fields_total, pack_versions = [], 0, 0, 0
	for c in cards:
		doc = frappe.get_doc("OCR Card Type", c.name)
		packs = frappe.get_all("OCR Card Pack", filters={"card_type": c.name}, fields=["name", "version", "status", "trained_on", "cv_exact", "pack_file", "creation"], order_by="version desc")
		for pk in packs:
			pk["tflite"] = _has_tflite(pk.pack_file)
		run, res = _latest_results(c.name)
		shipped = len((res or {}).get("pack", {}).get("shipped") or [])
		shipped_total += shipped
		fields_total += len(doc.fields)
		pack_versions += len(packs)
		registry.append({"card": c.name, "title": c.title, "status": c.status, "fields": len(doc.fields), "shipped": shipped, "packs": packs,
			"has_template": bool(c.template_image), "has_grid": bool(c.grid_json), "last_run": run.name if run else None,
			"cv_exact": run.cv_exact if run else None})
	cells = frappe.get_all("OCR Cell", filters={"label": ["is", "set"]}, fields=["how", "scan"])
	human = [x for x in cells if x.how in HUMAN]
	scans = {s.name: s.page for s in frappe.get_all("OCR Scan", fields=["name", "page"])}
	pages_by_card = {}
	for r in frappe.get_all("OCR Cell", filters={"label": ["is", "set"]}, fields=["card_type", "how", "scan"]):
		if r.how in HUMAN and r.scan in scans:
			pages_by_card.setdefault(r.card_type, set()).add(scans[r.scan])
	best_pages = max((len(v) for v in pages_by_card.values()), default=0)
	runs = frappe.get_all("OCR Training Run", fields=["name", "status", "cv_exact", "creation"], order_by="creation desc")
	done = [r for r in runs if r.status == "Done"]
	n_scans = frappe.db.count("OCR Scan")
	n_cells = frappe.db.count("OCR Cell")
	steps = [
		{"label": "Save a card template", "done": any(r["has_template"] for r in registry), "detail": f"{sum(r['has_template'] for r in registry)} saved", "route": "ocr-grid-editor"},
		{"label": "Save a grid for a template", "done": any(r["has_grid"] for r in registry), "detail": f"{sum(r['has_grid'] for r in registry)} templates with a grid", "route": "ocr-grid-editor"},
		{"label": "Add filled scans", "done": n_scans > 0, "detail": f"{n_scans} scans cut into {n_cells} cells", "route": "ocr-scans"},
		{"label": f"Label cells on {MIN_PAGES} pages of a card", "done": best_pages >= MIN_PAGES, "detail": f"most on one card: {best_pages} pages", "route": "ocr-labeling"},
		{"label": "Train a reader", "done": bool(runs), "detail": f"{len(runs)} runs", "route": "ocr-training"},
		{"label": "Get a field to ship", "done": shipped_total > 0, "detail": f"{shipped_total} of {fields_total} fields", "route": "ocr-training"},
		{"label": "Have a pack ready for the phone", "done": any(p["status"] == "Shipped" for r in registry for p in r["packs"]), "detail": f"{pack_versions} pack versions", "route": "ocr-training"},
	]
	last = done[0] if done else None
	return {"tiles": {"card_types": len(cards), "card_names": [c.title for c in cards], "shipped": shipped_total, "fields_total": fields_total,
			"labeled": len(human), "labeled_pages": sum(len(v) for v in pages_by_card.values()), "unverified": len(cells) - len(human),
			"cv_exact": last.cv_exact if last else None, "last_run": last.name if last else None, "pack_versions": pack_versions},
		"registry": registry, "steps": steps}
