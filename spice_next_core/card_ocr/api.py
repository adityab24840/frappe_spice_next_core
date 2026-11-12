"""Phone-facing API for Card OCR: which packs exist, and corrections coming back from the phone.

  GET  /api/method/spice_next_core.card_ocr.api.list_packs
  POST /api/method/spice_next_core.card_ocr.api.submit_corrections

Corrections use the record format the Card Reader app writes (corrections.jsonl): pack_id, pack_version, field, col ("c1" = first visit), label,
and optionally card (one id per photographed card), writer (a code, never a name) and crop (a base64 PNG of the cell the person looked at).
Every submitted label is stored as an OCR Cell with how = "phone"; nothing is trained on until a person reviews it.
"""
import base64
import binascii

import frappe
from frappe import _

from spice_next_core.card_ocr import rules

MAX_BATCH = 500
MAX_CROP_BYTES = 300_000
ROLES = ("System Manager", "OCR Labeler")


def _need_role():
	if not set(ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


@frappe.whitelist(methods=["GET"])
def list_packs():
	"""Shipped packs, newest version of each card first: [{card, version, pack_file, trained_on}]."""
	_need_role()
	rows = frappe.get_all(
		"OCR Card Pack",
		filters={"status": "Shipped"},
		fields=["card_type", "version", "pack_file", "trained_on", "modified"],
		order_by="card_type asc, version desc",
	)
	newest = {}
	for r in rows:
		newest.setdefault(r.card_type, r)
	return [{"card": r.card_type, "version": r.version, "pack_file": r.pack_file, "trained_on": r.trained_on} for r in newest.values()]


def _save_crop(data, name):
	try:
		raw = base64.b64decode(data, validate=True)
	except (binascii.Error, ValueError):
		return None
	if not raw.startswith(b"\x89PNG") or len(raw) > MAX_CROP_BYTES:
		return None
	f = frappe.get_doc({"doctype": "File", "file_name": f"{name}.png", "content": raw, "is_private": 1}).insert(ignore_permissions=True)
	return f.file_url


@frappe.whitelist(methods=["POST"])
def submit_corrections(corrections):
	"""Store a batch of phone corrections. -> {saved, refused: [{index, why}]}. A refused record never stops the rest."""
	_need_role()
	items = frappe.parse_json(corrections)
	if not isinstance(items, list) or len(items) > MAX_BATCH:
		frappe.throw(_("Send a list of at most {0} corrections.").format(MAX_BATCH))
	saved, refused = 0, []
	for i, c in enumerate(items):
		try:
			_store_one(c)
			saved += 1
		except Exception as e:  # one bad record must not lose the others
			refused.append({"index": i, "why": str(e)[:200]})
	return {"saved": saved, "refused": refused}


def _store_one(c):
	card = (c.get("pack_id") or "").strip()
	if not rules.CARD_KEY.match(card) or not frappe.db.exists("OCR Card Type", card):
		raise ValueError(f"unknown card {card!r}")
	field, visit = c.get("field") or "", c.get("col") or ""
	if not rules.KEY.match(field) or not rules.VISIT.match(visit):
		raise ValueError("bad field or visit")
	writer = (c.get("writer") or "").strip()
	problem = rules.writer_problem(writer)
	if problem:
		raise ValueError(problem)
	page = f"ph-{c.get('card') or 'x'}"
	scan_name = f"SCAN-{card}-{page}"
	if not frappe.db.exists("OCR Scan", scan_name):
		frappe.get_doc({"doctype": "OCR Scan", "card_type": card, "page": page, "writer": writer, "status": "Cut"}).insert(ignore_permissions=True)
	cell = frappe.get_doc(
		{"doctype": "OCR Cell", "scan": scan_name, "card_type": card, "field_key": field, "visit": visit, "has_ink": 1,
		 "label": c.get("label") or "", "how": "phone"}
	)
	if c.get("crop"):
		cell.crop = _save_crop(c["crop"], f"{card}-{field}-{visit}")
	cell.insert(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def add_scan(file_url, card_type="auto", writer="", page=""):
	"""Match one uploaded photo to a card, straighten it and cut its cells. See service.add_scan."""
	_need_role()
	from spice_next_core.card_ocr import service

	return service.add_scan(file_url, card_type, writer, page)


@frappe.whitelist(methods=["POST"])
def set_template(card_type, template_file, grid_json, sync_fields=1):
	"""Give a card type its template image and grid. See service.set_template."""
	_need_role()
	from spice_next_core.card_ocr import service

	return service.set_template(card_type, template_file, grid_json, sync_fields)


@frappe.whitelist(methods=["POST"])
def detect_grid(file_url, axis="rows", label_cols=0, data_cols=None, label_rows=0, data_rows=None):
	"""Propose a grid from a template image (Card Studio's layout detection). See service.detect_grid."""
	_need_role()
	from spice_next_core.card_ocr import service

	return service.detect_grid(file_url, axis, label_cols, data_cols, label_rows, data_rows)


@frappe.whitelist(methods=["POST"])
def suggest(card_type, pack=None, limit=500, redo=0):
	"""Put AI suggestions (never labels) beside the cells of a card. See service.suggest."""
	_need_role()
	from spice_next_core.card_ocr import service

	return service.suggest(card_type, pack, limit, redo)


@frappe.whitelist(methods=["POST"])
def start_training(card_type, pretrained=None, include_ai_read=None, target=None, min_n=None, max_epochs=None, config=None):
	"""Train a reader for a card on the PyTorch backend, from the human-verified labels. -> the run's name. See training.start_run."""
	_need_role()
	from spice_next_core.card_ocr import training

	return training.start_run(card_type, pretrained, include_ai_read, target, min_n, max_epochs, config)


@frappe.whitelist(methods=["POST"])
def refresh_training(run):
	"""Check on a training run; imports the pack when it has finished. See training.refresh_run."""
	_need_role()
	from spice_next_core.card_ocr import training

	return training.refresh_run(run)


@frappe.whitelist(methods=["GET"])
def backend_health():
	_need_role()
	from spice_next_core.card_ocr import training

	return training.backend_health()


@frappe.whitelist(methods=["POST"])
def refresh_ink(card_type):
	"""Rebuild the blank-card estimate and the ink flags. See service.refresh_ink."""
	_need_role()
	from spice_next_core.card_ocr import service

	return service.refresh_ink(card_type)


@frappe.whitelist(methods=["POST"])
def recut(card_type):
	"""Cut every stored scan again with the card's current grid. See service.recut."""
	_need_role()
	from spice_next_core.card_ocr import service

	return service.recut(card_type)


@frappe.whitelist(methods=["GET"])
def writer_status(card_type):
	_need_role()
	from spice_next_core.card_ocr import writers

	return writers.status(card_type)


@frappe.whitelist(methods=["POST"])
def assign_writer(card_type, writer="", first=None, last=None, pages=None):
	"""Say who wrote a range of pages (a code, never a name). See writers.assign."""
	_need_role()
	from spice_next_core.card_ocr import writers

	return writers.assign(card_type, writer, first, last, frappe.parse_json(pages) if pages else None)


@frappe.whitelist(methods=["GET"])
def id_test():
	"""Does the system tell its cards apart? See idtest.run."""
	_need_role()
	from spice_next_core.card_ocr import idtest

	return idtest.run()


@frappe.whitelist(methods=["POST"])
def cleanup_lab(file_url, pack=None):
	"""Run one photo through every photo clean-up method and read it with a pack. See cleanup_lab.analyze."""
	_need_role()
	from spice_next_core.card_ocr import cleanup_lab

	return cleanup_lab.analyze(file_url, pack)


@frappe.whitelist(methods=["GET"])
def studio_jobs():
	"""Studio's experiment status (Model quality). See training.studio_jobs."""
	_need_role()
	from spice_next_core.card_ocr import training

	return training.studio_jobs()


@frappe.whitelist(methods=["GET"])
def pretrained_list():
	"""Starting weights a run can begin from. See training.pretrained_list."""
	_need_role()
	from spice_next_core.card_ocr import training

	return training.pretrained_list()


@frappe.whitelist(methods=["GET"])
def datasize(card_type, target=None):
	"""Is there enough labelled data? See training.datasize."""
	_need_role()
	from spice_next_core.card_ocr import training

	return training.datasize(card_type, target)


@frappe.whitelist(methods=["GET"])
def compare_runs(a, b):
	"""Two training runs side by side. See training.compare_runs."""
	_need_role()
	from spice_next_core.card_ocr import training

	return training.compare_runs(a, b)


@frappe.whitelist(methods=["POST"])
def analyze_template(file_url, rotate=0, straighten=1):
	"""Template editor, step 1: rotate, level and find the cells of a template photo. See service.analyze_template."""
	_need_role()
	from spice_next_core.card_ocr import service

	return service.analyze_template(file_url, rotate, straighten)


@frappe.whitelist(methods=["POST"])
def save_layout(card_type, image_url, fields, base_version=None, create=0, title=""):
	"""Template editor, step 2 (approve): the image and cells become a new version of the template. See service.save_layout."""
	_need_role()
	from spice_next_core.card_ocr import service

	return service.save_layout(card_type, image_url, fields, base_version, create, title)


@frappe.whitelist(methods=["GET"])
def list_templates():
	"""Every template with its versions. See service.list_templates."""
	_need_role()
	from spice_next_core.card_ocr import service

	return service.list_templates()


@frappe.whitelist(methods=["GET"])
def get_template_version(card_type, version):
	"""A version's image, cells and grid. See service.get_version."""
	_need_role()
	from spice_next_core.card_ocr import service

	return service.get_version(card_type, version)


@frappe.whitelist(methods=["POST"])
def preview_grid(card_type, opts=None, version=None):
	"""Reader grid: preview the table derived from the saved layout. See service.preview_grid."""
	_need_role()
	from spice_next_core.card_ocr import service

	return service.preview_grid(card_type, opts, version)


@frappe.whitelist(methods=["POST"])
def save_grid(card_type, opts=None, version=None):
	"""Reader grid: save the previewed grid. See service.save_grid."""
	_need_role()
	from spice_next_core.card_ocr import service

	return service.save_grid(card_type, opts, version)


@frappe.whitelist(methods=["POST"])
def delete_template_version(card_type, version):
	"""Delete one template version (refused while scans use it). See service.delete_version."""
	_need_role()
	from spice_next_core.card_ocr import service

	return service.delete_version(card_type, version)
