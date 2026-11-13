"""Card OCR services: turn an uploaded photo into scan and cell records, and put AI suggestions beside the cells. Uses the engine and the DocTypes.

Everything patient-derived (photos, crops) is stored as a private File. A suggestion is never a label: it goes in ai_text, and only a person's
answer (labeling.save) becomes a label.
"""
import json

import cv2
import frappe
from frappe import _

from spice_next_core.card_ocr import rules
from spice_next_core.card_ocr.engine import reader as ocr_reader
from spice_next_core.card_ocr.engine import vision

MAX_UPLOAD = 25 * 1024 * 1024
BLANK_MIN, BLANK_SCANS = 5, 25      # scans needed for / used in the blank-card estimate
_targets = {}


def _file_bytes(file_url):
	"""Content of a File the current user may read."""
	name = frappe.db.get_value("File", {"file_url": file_url})
	if not name:
		frappe.throw(_("File not found: {0}").format(file_url))
	doc = frappe.get_doc("File", name)
	doc.check_permission("read")
	data = doc.get_content()
	return data.encode() if isinstance(data, str) else data


def _save_private(name, content):
	return frappe.get_doc({"doctype": "File", "file_name": name, "content": content, "is_private": 1}).insert(ignore_permissions=True).file_url


def card_target(card_type):
	"""A Target for a card type that has a template image and a valid grid. Cached until the card type changes."""
	doc = frappe.get_doc("OCR Card Type", card_type)
	key = (card_type, str(doc.modified))
	if key in _targets:
		return _targets[key]
	if not doc.template_image or not doc.grid_json:
		frappe.throw(_("{0} needs a template image and a grid first.").format(card_type))
	grid = json.loads(doc.grid_json) if isinstance(doc.grid_json, str) else doc.grid_json
	problems = vision.check_grid(grid)
	if problems:
		frappe.throw(_("The grid of {0} is not valid: {1}").format(card_type, "; ".join(problems)))
	import numpy as np

	tpl = cv2.imdecode(np.frombuffer(_file_bytes(doc.template_image), np.uint8), cv2.IMREAD_GRAYSCALE)
	if tpl is None:
		frappe.throw(_("The template image of {0} cannot be read.").format(card_type))
	_targets[key] = vision.Target(card_type, tpl, grid)
	return _targets[key]


def ready_cards():
	"""Card types that can be matched against: they have a template image and a grid."""
	# grid_json is a JSON column: Postgres cannot compare it with '', so it is checked here rather than in the filter
	rows = frappe.get_all("OCR Card Type", filters={"template_image": ["is", "set"]}, fields=["name", "grid_json"])
	return [r.name for r in rows if r.grid_json]


def detect_grid(file_url, axis="rows", label_cols=0, data_cols=None, label_rows=0, data_rows=None):
	"""Propose a grid for a template image from its printed rules. -> {grid, width, height} (grid None when no table was found). Only a starting point."""
	import numpy as np

	from spice_next_core.card_ocr.engine import gridfinder

	if axis not in ("rows", "columns"):
		frappe.throw(_("axis must be rows or columns"))
	img = cv2.imdecode(np.frombuffer(_file_bytes(file_url), np.uint8), cv2.IMREAD_GRAYSCALE)
	if img is None:
		frappe.throw(_("That file is not a readable image."))
	s = 3000 / max(img.shape)
	if s < 1:
		img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
	found = gridfinder.propose(img, axis, int(label_cols or 0), int(data_cols) if data_cols else None, int(label_rows or 0), int(data_rows) if data_rows else None)
	return {"grid": found["grid"], "method": found["method"], "warnings": found["warnings"], "width": img.shape[1], "height": img.shape[0]}


def set_template(card_type, template_file, grid_json, sync_fields=1):
	"""Attach a template image and a grid to a card type, checking the grid. With sync_fields, every field named by the grid that the card type does
	not list yet is added as a text field (set its kind afterwards). Returns {rows, cols, added_fields}."""
	grid = json.loads(grid_json) if isinstance(grid_json, str) else grid_json
	problems = vision.check_grid(grid)
	if problems:
		frappe.throw(_("The grid is not valid: {0}").format("; ".join(problems)))
	doc = frappe.get_doc("OCR Card Type", card_type)
	doc.status = "Gridded" if doc.status == "Draft" else doc.status
	_ensure_versions(card_type)                  # a card made before versions existed keeps its old template as v1
	if (doc.template_image, _jload(doc.grid_json) if doc.grid_json else None) != (template_file, grid) or not frappe.db.exists("OCR Template Version", {"card_type": card_type}):
		last = frappe.get_all("OCR Template Version", filters={"card_type": card_type}, fields=["version"], order_by="version desc", limit=1)
		n = (last[0].version if last else 0) + 1
		frappe.get_doc({"doctype": "OCR Template Version", "card_type": card_type, "version": n, "image": template_file, "grid_json": json.dumps(grid)}).insert(ignore_permissions=True)
		doc.template_version = n
	doc.template_image = template_file
	doc.grid_json = json.dumps(grid)
	added = []
	if int(sync_fields):
		have = {f.key for f in doc.fields}
		for key in (grid["cols"] if grid.get("axis") == "columns" else grid["rows"]):
			if key not in have:
				doc.append("fields", {"key": key, "kind": "text", "layout": "single", "decode": "greedy"})
				added.append(key)
	doc.save()
	return {"rows": len(grid["rows"]), "cols": len(grid["col_lines_top"]) - 1, "added_fields": added}


def add_scan(file_url, card_type="auto", writer="", page=""):
	"""Match an uploaded photo (or every page of an uploaded PDF) to a card, straighten it, cut every cell. A photo -> one result dict
	{scan, card, status, inliers, reason, cells, with_ink, tried, blank_estimate}; a PDF -> {"results": [one such dict per page], "pages": n}.
	A page that matches nothing is rejected and nothing is stored for it."""
	problem = rules.writer_problem(writer)
	if problem:
		frappe.throw(_(problem))
	data = _file_bytes(file_url)
	if len(data) > MAX_UPLOAD:
		frappe.throw(_("The file is larger than {0} MB.").format(MAX_UPLOAD // (1024 * 1024)))
	try:
		pages = list(vision.pages_from(data))
	except ValueError as e:
		frappe.throw(_("{0}. HEIC photos need the pillow-heif package and PDFs need pypdfium2; both are installed with the app's requirements.").format(str(e)))
	names = ready_cards() if card_type in ("", "auto", None) else [card_type]
	if not names:
		frappe.throw(_("No card type has a template and a grid yet."))
	targets = [card_target(n) for n in names]
	out = []
	for i, bgr in enumerate(pages):
		pg = page if page and len(pages) == 1 else (f"{page or 'pdf'}-p{i + 1:03d}" if len(pages) > 1 else "")
		out.append(_add_one(bgr, targets, file_url, writer, pg))
	return out[0] if len(out) == 1 else {"results": out, "pages": len(out)}


def _add_one(bgr, targets, file_url, writer, page):
	res = vision.process(bgr, targets)
	out = {k: res[k] for k in ("card", "status", "inliers", "reason", "tried")}
	if res["status"] == "rejected":
		return {**out, "scan": None, "cells": 0, "with_ink": 0}
	target = card_target(res["card"])
	blank_cells = _blank_cells(target, _blank_image(res["card"], target))
	for c in res["cells"]:                  # what the blank card already shows in a cell (a printed diagonal, shading) is not writing
		c["ink"] = vision.has_ink(target, c["crop"], blank_cells.get((c["field"], c["visit"])))
	page = page or f"p-{frappe.generate_hash(length=6)}"
	scan = frappe.get_doc({"doctype": "OCR Scan", "card_type": res["card"], "page": page, "writer": writer, "source_image": file_url,
		"status": "Cut", "template_version": frappe.db.get_value("OCR Card Type", res["card"], "template_version") or 0, "inliers": res["inliers"], "cells_total": len(res["cells"]), "cells_with_ink": sum(c["ink"] for c in res["cells"])}).insert()
	ok_a, png_a = cv2.imencode(".png", res["aligned"])
	if ok_a:
		scan.db_set("aligned_image", _save_private(f"{scan.name}-aligned.png", png_a.tobytes()))
	for c in res["cells"]:
		ok, png = cv2.imencode(".png", c["crop"])
		crop = _save_private(f"{scan.name}-{c['field']}-{c['visit']}.png", png.tobytes()) if ok else None
		frappe.get_doc({"doctype": "OCR Cell", "scan": scan.name, "card_type": res["card"], "field_key": c["field"], "visit": c["visit"],
			"has_ink": 1 if c["ink"] else 0, "crop": crop}).insert()
	blank = refresh_ink(res["card"]) if BLANK_MIN <= frappe.db.count("OCR Scan", {"card_type": res["card"]}) <= BLANK_SCANS else None
	if blank and blank.get("rebuilt"):
		scan.reload()
	return {**out, "scan": scan.name, "cells": len(res["cells"]), "with_ink": scan.cells_with_ink, "blank_estimate": blank}


def _shipped_pack(card_type, pack=None):
	name = pack or frappe.db.get_value("OCR Card Pack", {"card_type": card_type, "status": "Shipped"}, "name", order_by="version desc")
	if not name:
		name = frappe.db.get_value("OCR Card Pack", {"card_type": card_type}, "name", order_by="version desc")
	if not name:
		frappe.throw(_("{0} has no pack to suggest with yet.").format(card_type))
	return frappe.get_doc("OCR Card Pack", name)


def suggest(card_type, pack=None, limit=500, redo=0):
	"""Put an AI suggestion beside every cell with ink that has none (or all, with redo). Suggestions are never labels. -> {read, skipped, source}."""
	pk = _shipped_pack(card_type, pack)
	reader = ocr_reader.Reader(ocr_reader.read_pack(_file_bytes(pk.pack_file)))
	filters = {"card_type": card_type, "has_ink": 1}
	if not int(redo):
		filters["ai_text"] = ["is", "not set"]
	cells = frappe.get_all("OCR Cell", filters=filters, fields=["name", "scan", "field_key", "crop"], limit=int(limit))
	import numpy as np

	read = skipped = 0
	for c in cells:
		if not c.crop:
			skipped += 1
			continue
		img = cv2.imdecode(np.frombuffer(_file_bytes(c.crop), np.uint8), cv2.IMREAD_GRAYSCALE)
		text, conf = reader.read(img, c.field_key) if img is not None else ("", 0.0)
		frappe.db.set_value("OCR Cell", c.name, {"ai_text": text, "ai_confidence": conf, "ai_source": f"{pk.card_type} v{pk.version}"}, update_modified=False)
		read += 1
	noted = card_checks(card_type, {c.scan for c in cells})
	return {"read": read, "skipped": skipped, "source": f"{pk.card_type} v{pk.version}", "card_checks": noted}


WEAK_BELOW = 0.5          # a read under this confidence is corrected by the card checks but does not vote in them


def card_checks(card_type, scans=None):
	"""Run the card-level checks the card type asks for (engine/cardlogic.py: same date down a visit column, dates that go up) over the AI reads of each scan, and put
	the result beside the cells: ai_suggestion (a date the others agree on) and ai_note. A read is never replaced; a cell that no longer has a doubt is cleared.
	-> number of cells noted."""
	from spice_next_core.card_ocr.engine import cardlogic

	doc = frappe.db.get_value("OCR Card Type", card_type, ["same_day_fields", "increasing_fields"], as_dict=True)
	asked = {k: cardlogic.parse_fields(v) for k, v in (("same_day", doc.same_day_fields), ("increasing", doc.increasing_fields)) if v}
	if not asked:
		return 0
	noted = 0
	for scan in scans or frappe.get_all("OCR Scan", filters={"card_type": card_type}, pluck="name"):
		rows = frappe.get_all("OCR Cell", filters={"scan": scan, "ai_text": ["is", "set"]}, fields=["name", "field_key", "visit", "ai_text", "ai_confidence", "ai_suggestion", "ai_note"])
		num = lambda visit: int(visit[1:])          # noqa: E731  a visit is named c1, c2...; the checks count them
		reads = {(r.field_key, num(r.visit)): r.ai_text for r in rows}
		weak = {(r.field_key, num(r.visit)) for r in rows if r.ai_confidence is not None and r.ai_confidence < WEAK_BELOW}
		found = {(f["field"], f["visit"]): f for f in cardlogic.check(reads, asked, weak)}
		for r in rows:
			f = found.get((r.field_key, num(r.visit)))
			new = {"ai_suggestion": f and f["suggestion"], "ai_note": f and f["note"]}
			if (r.ai_suggestion or None, r.ai_note or None) != (new["ai_suggestion"] or None, new["ai_note"] or None):
				frappe.db.set_value("OCR Cell", r.name, new, update_modified=False)
			noted += 1 if f else 0
	return noted


# ---------------------------------------------------------------- blank-card estimate, ink flags, re-cut
def _gray(file_url):
	import numpy as np

	return cv2.imdecode(np.frombuffer(_file_bytes(file_url), np.uint8), cv2.IMREAD_GRAYSCALE)


def _blank_image(card_type, target):
	"""The estimated blank card, or None when there is none yet or it is for another grid size."""
	url = frappe.db.get_value("OCR Card Type", card_type, "blank_image")
	if not url:
		return None
	im = _gray(url)
	return im if im is not None and [im.shape[1], im.shape[0]] == list(target.grid["image_size"]) else None


def _blank_cells(target, blank):
	return {} if blank is None else {(f, v): crop for _ri, _c, f, v, crop in vision.cut_cells(blank, target)}


def refresh_ink(card_type, force=False):
	"""Rebuild the blank-card estimate from up to BLANK_SCANS aligned scans (their pixel median) and decide again which cells hold ink. -> {rebuilt,
	scans, changed}. With fewer than BLANK_MIN scans there is no estimate and a cell with print in it counts as having ink."""
	import numpy as np

	target = card_target(card_type)
	scans = frappe.get_all("OCR Scan", filters={"card_type": card_type, "aligned_image": ["is", "set"]}, fields=["name", "aligned_image"], order_by="creation asc", limit=BLANK_SCANS)
	if len(scans) < BLANK_MIN:
		return {"rebuilt": False, "scans": len(scans), "changed": 0}
	size = tuple(target.grid["image_size"])
	stack = [im for im in (_gray(s.aligned_image) for s in scans) if im is not None and (im.shape[1], im.shape[0]) == size]
	if len(stack) < BLANK_MIN:
		return {"rebuilt": False, "scans": len(stack), "changed": 0}
	blank = np.median(np.stack(stack), axis=0).astype(np.uint8)
	url = _save_private(f"{card_type}-blank.png", cv2.imencode(".png", blank)[1].tobytes())
	old = frappe.db.get_value("OCR Card Type", card_type, "blank_image")
	frappe.db.set_value("OCR Card Type", card_type, {"blank_image": url, "blank_scans": len(stack)}, update_modified=False)
	if old and old != url:
		name = frappe.db.get_value("File", {"file_url": old})
		if name:
			frappe.delete_doc("File", name, ignore_permissions=True, force=True)
	blank_cells = _blank_cells(target, blank)
	changed = 0
	for c in frappe.get_all("OCR Cell", filters={"card_type": card_type, "crop": ["is", "set"]}, fields=["name", "field_key", "visit", "crop", "has_ink"]):
		crop = _gray(c.crop)
		if crop is None:
			continue
		ink = 1 if vision.has_ink(target, crop, blank_cells.get((c.field_key, c.visit))) else 0
		if ink != int(c.has_ink or 0):
			frappe.db.set_value("OCR Cell", c.name, "has_ink", ink, update_modified=False)
			changed += 1
	for sc in frappe.get_all("OCR Scan", filters={"card_type": card_type}, pluck="name"):
		n = frappe.db.count("OCR Cell", {"scan": sc, "has_ink": 1})
		frappe.db.set_value("OCR Scan", sc, "cells_with_ink", n, update_modified=False)
	return {"rebuilt": True, "scans": len(stack), "changed": changed}


def recut(card_type):
	"""Cut every stored scan again from its aligned image with the card's current grid (after the grid was edited). Crops are replaced; a cell keeps its
	label when its field and visit still exist. Cells whose field left the grid are deleted when unlabeled and kept (unused) when labeled.
	-> {scans, cells, removed, kept_orphans}. Scans whose aligned image is missing are skipped."""
	target = card_target(card_type)
	blank_cells = _blank_cells(target, _blank_image(card_type, target))
	valid = set()
	stats = {"scans": 0, "cells": 0, "removed": 0, "kept_orphans": 0, "skipped": 0}
	for sc in frappe.get_all("OCR Scan", filters={"card_type": card_type}, fields=["name", "aligned_image"]):
		aligned = _gray(sc.aligned_image) if sc.aligned_image else None
		if aligned is None or (aligned.shape[1], aligned.shape[0]) != tuple(target.grid["image_size"]):
			stats["skipped"] += 1
			continue
		stats["scans"] += 1
		have = {(c.field_key, c.visit): c for c in frappe.get_all("OCR Cell", filters={"scan": sc.name}, fields=["name", "field_key", "visit", "crop"])}
		keep = set()
		for _ri, _c, f, v, crop in vision.cut_cells(aligned, target):
			ink = vision.has_ink(target, crop, blank_cells.get((f, v)))
			url = _save_private(f"{sc.name}-{f}-{v}.png", cv2.imencode(".png", crop)[1].tobytes())
			keep.add((f, v))
			if (f, v) in have:
				old = have[(f, v)]
				frappe.db.set_value("OCR Cell", old.name, {"crop": url, "has_ink": 1 if ink else 0}, update_modified=False)
				if old.crop and old.crop != url and (fn := frappe.db.get_value("File", {"file_url": old.crop})):
					frappe.delete_doc("File", fn, ignore_permissions=True, force=True)
			else:
				frappe.get_doc({"doctype": "OCR Cell", "scan": sc.name, "card_type": card_type, "field_key": f, "visit": v, "has_ink": 1 if ink else 0, "crop": url}).insert()
			stats["cells"] += 1
		for key, c in have.items():
			if key in keep:
				continue
			if frappe.db.get_value("OCR Cell", c.name, "label"):
				stats["kept_orphans"] += 1
			else:
				frappe.delete_doc("OCR Cell", c.name, ignore_permissions=True, force=True)
				stats["removed"] += 1
		frappe.db.set_value("OCR Scan", sc.name, {"cells_total": len(keep), "cells_with_ink": frappe.db.count("OCR Cell", {"scan": sc.name, "has_ink": 1})}, update_modified=False)
	return stats


# ---------------------------------------------------------------- templates, versions and the reader grid, the way Card Studio does them
# A card type is a template name. Every Save in the template editor makes a new version (v1, v2...); older versions are kept with their own image, cells and
# grid. New scans are cut with the newest version that has a grid, and each scan records which version that was.
KINDS = ("text", "number", "date", "bp", "mark")
TEMPLATE_MAX_SIDE = 2400          # Studio caps an uploaded template photo at this size
GRID_OPTION_KEYS = ("axis", "label_cols", "data_cols", "label_rows", "data_rows")
HIGH, MID = 0.67, 0.25            # template match score: >= HIGH the photo is a known template, >= MID a similar one, else a new one


def _purge_old_template_work():
	from frappe.utils import add_days, now_datetime

	for f in frappe.get_all("File", filters={"file_name": ["like", "tplwork-%"], "creation": ["<", add_days(now_datetime(), -1)]}, pluck="name"):
		frappe.delete_doc("File", f, ignore_permissions=True, force=True)


def _jload(v):
	return json.loads(v) if isinstance(v, str) else v


def _versions(card_type):
	return frappe.get_all("OCR Template Version", filters={"card_type": card_type}, fields=["name", "version", "image", "cells", "base_version", "creation", "grid_json", "grid_opts"],
		order_by="version asc")


def _ensure_versions(card_type):
	"""A card type made before versions existed has its template on the card itself: make that its v1."""
	if frappe.db.exists("OCR Template Version", {"card_type": card_type}):
		return
	doc = frappe.get_doc("OCR Card Type", card_type)
	if not doc.template_image:
		return
	lay = _jload(doc.layout_json) if doc.layout_json else None
	frappe.get_doc({"doctype": "OCR Template Version", "card_type": card_type, "version": 1, "image": doc.template_image, "cells": len(lay["fields"]) if lay else 0,
		"layout_json": json.dumps(lay) if lay else None, "grid_json": doc.grid_json, "grid_opts": doc.grid_opts}).insert(ignore_permissions=True)
	if doc.grid_json:
		frappe.db.set_value("OCR Card Type", card_type, "template_version", 1, update_modified=False)


def _activate(card_type):
	"""Point the card type at its newest version that has a grid (what scans are cut with). A card with none is not ready."""
	gridded = [v for v in _versions(card_type) if v.grid_json]
	doc = frappe.get_doc("OCR Card Type", card_type)
	if gridded:
		v = gridded[-1]
		doc.template_image, doc.grid_json, doc.template_version = v.image, v.grid_json if isinstance(v.grid_json, str) else json.dumps(v.grid_json), v.version
		doc.grid_opts = json.dumps(_jload(v.grid_opts)) if v.grid_opts else None
	else:
		doc.template_image, doc.grid_json, doc.template_version, doc.grid_opts = None, None, 0, None
	doc.save(ignore_permissions=True)


def match_templates(bgr):
	"""Score a photo against the newest version of every card type that has a template. -> [{name, version, score}] best first, and Studio's verdict."""
	out = []
	for t in frappe.get_all("OCR Card Type", pluck="name"):
		_ensure_versions(t)
		vs = _versions(t)
		if not vs:
			continue
		tpl = _gray(vs[-1].image)
		if tpl is not None:
			out.append({"name": t, "version": vs[-1].version, "score": round(vision.match_score(bgr, tpl), 3)})
	out.sort(key=lambda m: -m["score"])
	best = out[0]["score"] if out else 0.0
	return out, ("known" if best >= HIGH else "similar" if best >= MID else "new")


def analyze_template(file_url, rotate=0, straighten=1):
	"""Step 1 of the template editor. Turn the photo a quarter turn (rotate: 0/90/180/270), level its ruled lines, find its cells, and say whether it is a template
	that exists. -> {image (a private working copy), width, height, tilt, layout: {fields, stats}, matches: [{name, version, score}], verdict: known|similar|new,
	thresholds}. The working copy is deleted after a day unless save_layout makes it a template version."""
	from spice_next_core.card_ocr.engine import deskew, layout

	_purge_old_template_work()
	if int(rotate or 0) not in (0, 90, 180, 270):
		frappe.throw(_("rotate must be 0, 90, 180 or 270"))
	im = vision.decode_image(_file_bytes(file_url))
	if im is None:
		frappe.throw(_("That file is not a readable image."))
	im, info = deskew.straighten(im, int(rotate or 0), bool(int(straighten)))
	s = TEMPLATE_MAX_SIDE / max(im.shape[:2])
	if s < 1:
		im = cv2.resize(im, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
	det = layout.detect_layout(im)
	url = _save_private(f"tplwork-{frappe.generate_hash(length=10)}.png", cv2.imencode(".png", im)[1].tobytes())
	matches, verdict = match_templates(im)
	return {"image": url, "width": im.shape[1], "height": im.shape[0], "tilt": info, "layout": det, "matches": matches, "verdict": verdict,
		"thresholds": {"high": HIGH, "mid": MID}}


def _clean_fields(fields):
	"""Studio's checks: every cell has a name, the names are unique, the box has a size. (The editor renames duplicates itself before it saves.)"""
	if not isinstance(fields, list) or not fields:
		frappe.throw(_("No cells to save."))
	out = []
	for f in fields:
		name = str(f.get("name", "")).strip()
		if not name:
			frappe.throw(_("Every cell needs a name."))
		kind = f.get("kind", "text")
		if kind not in KINDS:
			frappe.throw(_("Cell {0}: unknown kind {1}.").format(name, kind))
		try:
			x, y, w, h = (float(f[k]) for k in ("x", "y", "w", "h"))
		except (KeyError, TypeError, ValueError):
			frappe.throw(_("Cell {0} has no position or size.").format(name))
		if w <= 0 or h <= 0:
			frappe.throw(_("Cell {0} has a bad box.").format(name))
		out.append({"id": str(f.get("id") or f"f{len(out) + 1}"), "name": name, "kind": kind, "section": str(f.get("section", "")), "x": round(x), "y": round(y),
			"w": round(w), "h": round(h), "range": str(f.get("range", "")), "charset": str(f.get("charset", ""))})
	if len({f["name"] for f in out}) != len(out):
		frappe.throw(_("Cell names must be unique."))
	return out


def list_templates():
	"""Every card type as a template with its versions. -> [{name, title, status, in_use, versions: [{version, cells, base_version, created, grid: {rows, cols}|None, scans}]}]"""
	out = []
	for c in frappe.get_all("OCR Card Type", fields=["name", "title", "status", "template_version"], order_by="name asc"):
		_ensure_versions(c.name)
		scans = {r.template_version or 0: r.n for r in frappe.db.sql("select template_version, count(*) n from `tabOCR Scan` where card_type=%s group by template_version", c.name, as_dict=True)}
		vs = []
		for v in _versions(c.name):
			g = _jload(v.grid_json) if v.grid_json else None
			vs.append({"version": v.version, "cells": v.cells, "base_version": v.base_version, "created": str(v.creation)[:16], "image": v.image,
				"grid": {"rows": len(g["rows"]), "cols": len(g["col_lines_top"]) - 1} if g else None, "scans": scans.get(v.version, 0)})
		out.append({"name": c.name, "title": c.title, "status": c.status, "in_use": c.template_version or 0, "versions": vs})
	return out


def get_version(card_type, version):
	"""What the editor opens for a version: its image, cells and grid options. -> {image, layout, grid_opts, grid}"""
	_ensure_versions(card_type)
	v = frappe.db.get_value("OCR Template Version", {"card_type": card_type, "version": int(version)}, ["image", "layout_json", "grid_json", "grid_opts"], as_dict=True)
	if not v:
		frappe.throw(_("{0} has no version {1}.").format(card_type, version))
	return {"image": v.image, "layout": _jload(v.layout_json) if v.layout_json else None, "grid": _jload(v.grid_json) if v.grid_json else None,
		"grid_opts": _jload(v.grid_opts) if v.grid_opts else None}


def save_layout(card_type, image_url, fields, base_version=None, create=0, title=""):
	"""Step 2 of the template editor ("Approve"): the image and the cells become a NEW version of the template. With create the card type is made first
	(card_type is its name: letters, digits, _ or -, at most 40, not taken). base_version says which version the editor started from (update mode).
	The new version has no grid yet: make it in the reader-grid step; until then scans keep using the newest version that has one. -> {card_type, version, cells}."""
	from spice_next_core.card_ocr import rules

	fields = frappe.parse_json(fields) if isinstance(fields, str) else fields
	if int(create or 0):
		if not rules.CARD_KEY.match(card_type or ""):
			frappe.throw(_("Template name: letters, digits, _ or - (max 40)."))
		if frappe.db.exists("OCR Card Type", card_type):
			frappe.throw(_("A template called {0} already exists: update it, or pick another name.").format(card_type))
	elif not frappe.db.exists("OCR Card Type", card_type):
		frappe.throw(_("There is no template called {0}.").format(card_type))
	im = _gray(image_url)
	if im is None:
		frappe.throw(_("The template image cannot be read."))
	height, width = im.shape
	cleaned = _clean_fields(fields)
	if int(create or 0):
		frappe.get_doc({"doctype": "OCR Card Type", "card_key": card_type, "title": title or card_type.replace("_", " ").replace("-", " ").title()}).insert()
	else:
		_ensure_versions(card_type)
	last = frappe.get_all("OCR Template Version", filters={"card_type": card_type}, fields=["version"], order_by="version desc", limit=1)
	n = (last[0].version if last else 0) + 1
	new_url = _save_private(f"{card_type}-template-v{n}.png", cv2.imencode(".png", im)[1].tobytes())
	frappe.get_doc({"doctype": "OCR Template Version", "card_type": card_type, "version": n, "image": new_url, "cells": len(cleaned),
		"base_version": int(base_version) if base_version else None, "layout_json": json.dumps({"image": [width, height], "fields": cleaned})}).insert(ignore_permissions=True)
	if image_url != new_url and (fn := frappe.db.get_value("File", {"file_url": image_url, "file_name": ["like", "tplwork-%"]})):   # Frappe stores identical content once
		frappe.delete_doc("File", fn, ignore_permissions=True, force=True)
	frappe.db.set_value("OCR Card Type", card_type, "layout_json", json.dumps({"image": [width, height], "fields": cleaned}), update_modified=False)
	return {"card_type": card_type, "version": n, "cells": len(cleaned), "image": new_url}


def _grid_options(opts):
	o = frappe.parse_json(opts) if isinstance(opts, str) else dict(opts or {})
	axis = o.get("axis") or "rows"
	if axis not in ("rows", "columns"):
		frappe.throw(_("axis must be rows or columns"))
	num = lambda k, lo=0: max(lo, int(o.get(k) or 0))          # noqa: E731
	return {"axis": axis, "label_cols": num("label_cols"), "data_cols": num("data_cols") or None, "label_rows": num("label_rows"), "data_rows": num("data_rows") or None}


def _version_row(card_type, version):
	_ensure_versions(card_type)
	if version in (None, "", 0, "0"):
		rows = _versions(card_type)
		if not rows:
			frappe.throw(_("Save the template (the cells) first."))
		return rows[-1].name
	name = frappe.db.get_value("OCR Template Version", {"card_type": card_type, "version": int(version)})
	if not name:
		frappe.throw(_("{0} has no version {1}.").format(card_type, version))
	return name


def preview_grid(card_type, opts=None, version=None):
	"""Reader-grid step: turn a version's cells (the newest by default) into the table of fields and visits a pack needs. -> {grid, errors, warnings, image, options,
	version} or {error}. Nothing is saved; the picture of the grid over the card is drawn by the page."""
	from spice_next_core.card_ocr.engine import layout

	row = frappe.get_doc("OCR Template Version", _version_row(card_type, version))
	if not row.layout_json:
		frappe.throw(_("Save the template (the cells) first."))
	lay = _jload(row.layout_json)
	o = _grid_options(opts)
	try:
		grid, warnings = layout.layout_to_grid(lay, **o)
	except ValueError as e:
		return {"error": str(e), "image": lay["image"], "options": o, "version": row.version}
	return {"grid": grid, "errors": vision.check_grid(grid), "warnings": warnings, "image": lay["image"], "options": o, "version": row.version}


def save_grid(card_type, opts=None, version=None):
	"""Save the previewed grid on that version, with the options that made it. A grid that is not valid is refused. The card type then reads with its newest
	gridded version, and fields the grid names that the card type does not list are added as text. -> {rows, cols, added_fields, options, warnings, version, in_use}."""
	pv = preview_grid(card_type, opts, version)
	if pv.get("error") or pv["errors"]:
		frappe.throw(_("The grid is not valid: {0}").format(pv.get("error") or "; ".join(pv["errors"])))
	row = frappe.get_doc("OCR Template Version", _version_row(card_type, version))
	row.grid_json, row.grid_opts = json.dumps(pv["grid"]), json.dumps(pv["options"])
	row.save(ignore_permissions=True)
	_activate(card_type)
	grid = pv["grid"]
	doc = frappe.get_doc("OCR Card Type", card_type)
	have = {f.key for f in doc.fields}
	added = []
	if doc.status == "Draft":
		doc.status = "Gridded"
	for key in (grid["cols"] if grid.get("axis") == "columns" else grid["rows"]):
		if key not in have:
			doc.append("fields", {"key": key, "kind": "text", "layout": "single", "decode": "greedy"})
			added.append(key)
	doc.save(ignore_permissions=True)
	return {"rows": len(grid["rows"]), "cols": len(grid["col_lines_top"]) - 1, "added_fields": added, "options": pv["options"], "warnings": pv["warnings"], "version": row.version,
		"in_use": doc.template_version}


def delete_version(card_type, version):
	"""Delete one template version. Refused when scans were cut with it (they would lose their grid) and when it is the only version of a card type that already
	has scans, cells or packs. Deleting the only version of an unused card type deletes the card type. The card then reads with its newest version that
	still has a grid. -> {deleted_card_type, in_use}."""
	_ensure_versions(card_type)
	name = _version_row(card_type, version)
	row = frappe.get_doc("OCR Template Version", name)
	if frappe.db.count("OCR Scan", {"card_type": card_type, "template_version": row.version}):
		frappe.throw(_("{0} v{1} cannot be deleted: scans were cut with it.").format(card_type, row.version))
	others = [v for v in _versions(card_type) if v.version != row.version]
	if not others:
		if frappe.db.exists("OCR Scan", {"card_type": card_type}) or frappe.db.exists("OCR Card Pack", {"card_type": card_type}):
			frappe.throw(_("{0} has scans or packs, so its only version cannot be deleted.").format(card_type))
		frappe.delete_doc("OCR Template Version", name, ignore_permissions=True)
		frappe.delete_doc("OCR Card Type", card_type, ignore_permissions=True)
		return {"deleted_card_type": 1, "in_use": 0}
	frappe.delete_doc("OCR Template Version", name, ignore_permissions=True)
	_activate(card_type)
	last = _versions(card_type)[-1]
	lay = frappe.db.get_value("OCR Template Version", last.name, "layout_json")
	frappe.db.set_value("OCR Card Type", card_type, "layout_json", json.dumps(_jload(lay)) if lay else None, update_modified=False)
	return {"deleted_card_type": 0, "in_use": frappe.db.get_value("OCR Card Type", card_type, "template_version") or 0}


# ---------------------------------------------------------------- pretrained models from outside (engine/extreader.py)
EXTERNAL_MAX_BYTES = 400 * 1024 * 1024        # a recogniser a phone could run is far smaller than this
_ext_readers = {}


def external_models():
	"""[{name, profile, classes, licence, commercial_use, source, note, ok, benchmarks: [{card, n, exact, cer, when}]}]"""
	out = []
	for m in frappe.get_all("OCR External Model", fields=["name", "profile", "licence", "commercial_use", "source", "note", "spec", "benchmarks", "sha256", "model_file"], order_by="name asc"):
		spec = m.spec if isinstance(m.spec, dict) else json.loads(m.spec or "{}")
		bm = m.benchmarks if isinstance(m.benchmarks, dict) else json.loads(m.benchmarks or "{}")
		ok = bool(m.model_file) and _sha(_file_bytes(m.model_file)) == m.sha256
		out.append({"name": m.name, "profile": m.profile, "classes": len(spec.get("classes", [])), "licence": m.licence, "commercial_use": m.commercial_use, "source": m.source, "note": m.note,
			"ok": ok, "problem": "" if ok else "the model file is missing or does not match its hash", "benchmarks": [{"card": c, **{k: v[k] for k in ("n", "exact", "cer", "when")}} for c, v in bm.items()]})
	return out


def _sha(data):
	import hashlib

	return hashlib.sha256(data).hexdigest()


def external_add(name, onnx_bytes, profile, charset_text, source="", licence="", commercial_use="unknown", note="", digit_map=0, **override):
	"""Register a model: checks the name, builds the spec, runs a blank cell through the model (a wrong class count or channel count is refused), and stores the file privately."""
	from spice_next_core.card_ocr.engine import extreader as X

	if not X.NAME.match(name or ""):
		frappe.throw(_("Model name: letters, digits, _ or - (at most 40)."))
	if frappe.db.exists("OCR External Model", name):
		frappe.throw(_("A model called {0} is already registered.").format(name))
	if commercial_use not in ("unknown", "yes", "no"):
		frappe.throw(_("Commercial use is unknown, yes or no."))
	try:
		spec = X.make_spec(profile, X.parse_charset(charset_text), digit_map=bool(int(digit_map or 0)), **override)
		X.ExternalReader(onnx_bytes, spec).check()
	except ValueError as e:
		frappe.throw(str(e))
	url = _save_private(f"external-{name}.onnx", onnx_bytes)
	frappe.get_doc({"doctype": "OCR External Model", "model_key": name, "profile": profile, "model_file": url, "sha256": _sha(onnx_bytes), "source": source, "licence": licence or "not stated",
		"commercial_use": commercial_use, "digit_map": 1 if spec["digit_map"] else 0, "charset": "\n".join(X.parse_charset(charset_text)),
		"spec": json.dumps(spec), "note": note}).insert()
	return {"name": name, "classes": len(spec["classes"])}


def external_hf_info(repo):
	"""What Hugging Face says about a public model repo before anything is downloaded. -> {repo, licence, gated, url, files}. Gated repos need a login: import those by uploading the files."""
	import re

	import requests

	if not re.fullmatch(r"[\w.-]{1,96}/[\w.-]{1,96}", repo or ""):
		frappe.throw(_("The repository looks like owner/name."))
	r = requests.get(f"https://huggingface.co/api/models/{repo}", params={"blobs": "true"}, timeout=30)
	if r.status_code != 200:
		frappe.throw(_("Hugging Face does not show {0} publicly (status {1}). A private or gated repository has to be imported by uploading its files.").format(repo, r.status_code))
	m = r.json()
	lic = next((t.split(":", 1)[1] for t in m.get("tags", []) if t.startswith("license:")), "")
	return {"repo": repo, "licence": lic, "gated": bool(m.get("gated")), "url": f"https://huggingface.co/{repo}",
		"files": [{"name": s["rfilename"], "bytes": s.get("size") or 0} for s in m.get("siblings", []) if s["rfilename"].lower().endswith((".onnx", ".yml", ".yaml", ".json", ".txt"))]}


def external_import_hf(repo, name, onnx_file, charset_file, profile, accept_licence=0, commercial_use="unknown", note="", digit_map=0):
	"""Download the model and its characters file from a public Hugging Face repo and register them. The licence is read from the repo and recorded; accept_licence says a person saw it."""
	import requests

	if not int(accept_licence or 0):
		frappe.throw(_("Show the licence to a person and accept it first."))
	info = external_hf_info(repo)
	size = {f["name"]: f["bytes"] for f in info["files"]}
	for f in (onnx_file, charset_file):
		if f not in size:
			frappe.throw(_("{0} has no file {1}.").format(repo, f))
	if size[onnx_file] > EXTERNAL_MAX_BYTES:
		frappe.throw(_("{0} is {1} MB: too large for a phone-sized recogniser.").format(onnx_file, size[onnx_file] // 1048576))
	get = lambda f: requests.get(f"https://huggingface.co/{repo}/resolve/main/{f}", timeout=300)          # noqa: E731
	a, b = get(onnx_file), get(charset_file)
	if a.status_code != 200 or b.status_code != 200:
		frappe.throw(_("The download failed (status {0}/{1}).").format(a.status_code, b.status_code))
	return external_add(name, a.content, profile, b.content.decode("utf-8"), info["url"], info["licence"], commercial_use, note, digit_map)


def external_reader(name):
	from spice_next_core.card_ocr.engine import extreader as X

	m = frappe.get_doc("OCR External Model", name)
	key = (name, m.sha256)
	if key not in _ext_readers:
		data = _file_bytes(m.model_file)
		if _sha(data) != m.sha256:
			frappe.throw(_("The file of {0} does not match its hash.").format(name))
		_ext_readers[key] = X.ExternalReader(data, m.spec if isinstance(m.spec, dict) else json.loads(m.spec))
	return _ext_readers[key]


def _single_line_fields(card_type):
	return {f.key for f in frappe.get_doc("OCR Card Type", card_type).fields if (f.layout or "single") == "single" and f.kind != "text"}


def external_benchmark(card_type, name):
	"""Read every labeled single-line cell of a card with the model, no fine-tuning, and score the reads against the labels people gave. -> {cells, overall, by_field, skipped}"""
	import numpy as np

	from spice_next_core.card_ocr.engine import extreader as X

	rd = external_reader(name)
	keep = _single_line_fields(card_type)
	cells = frappe.get_all("OCR Cell", filters={"card_type": card_type, "label": ["is", "set"], "crop": ["is", "set"]}, fields=["field_key", "label", "crop"])
	use = [c for c in cells if c.field_key in keep]
	if not use:
		frappe.throw(_("{0} has no labeled single-line cells to score.").format(card_type))
	rows = []
	for c in use:
		img = cv2.imdecode(np.frombuffer(_file_bytes(c.crop), np.uint8), cv2.IMREAD_GRAYSCALE)
		if img is not None:
			rows.append((c.field_key, c.label.strip(), rd.read(img)[0]))
	res = {**X.score(rows), "cells": len(rows), "skipped": len(cells) - len(use), "when": frappe.utils.now()[:16]}
	doc = frappe.get_doc("OCR External Model", name)
	bm = doc.benchmarks if isinstance(doc.benchmarks, dict) else json.loads(doc.benchmarks or "{}")
	bm[card_type] = {"n": res["overall"]["n"], "exact": res["overall"]["exact"], "cer": res["overall"]["cer"], "when": res["when"]}
	frappe.db.set_value("OCR External Model", name, "benchmarks", json.dumps(bm), update_modified=False)
	return res


def external_suggest(card_type, name, redo=0, limit=2000):
	"""Put the model's reads beside every cell with ink that has no suggestion yet (or all, with redo): ai_text, ai_confidence, ai_source `external:<name>`. Never a label."""
	import numpy as np

	rd = external_reader(name)
	keep = _single_line_fields(card_type)
	filters = {"card_type": card_type, "has_ink": 1, "crop": ["is", "set"]}
	if not int(redo):
		filters["ai_text"] = ["is", "not set"]
	read = 0
	for c in frappe.get_all("OCR Cell", filters=filters, fields=["name", "field_key", "crop"], limit=int(limit)):
		if c.field_key not in keep:
			continue
		img = cv2.imdecode(np.frombuffer(_file_bytes(c.crop), np.uint8), cv2.IMREAD_GRAYSCALE)
		if img is None:
			continue
		text, conf = rd.read(img)
		frappe.db.set_value("OCR Cell", c.name, {"ai_text": text, "ai_confidence": conf, "ai_source": f"external:{name}"}, update_modified=False)
		read += 1
	return {"read": read, "source": f"external:{name}"}


def external_remove(name):
	"""Remove a model and its stored file. Suggestions it already wrote stay (they say where they came from)."""
	doc = frappe.get_doc("OCR External Model", name)
	url = doc.model_file
	frappe.delete_doc("OCR External Model", name)
	if url and (fn := frappe.db.get_value("File", {"file_url": url})):
		frappe.delete_doc("File", fn, ignore_permissions=True, force=True)
	_ext_readers.clear()


def external_import_files(name, onnx_url, charset_url, profile, source="", licence="", commercial_use="unknown", note="", digit_map=0):
	"""Register a model from two files already uploaded to Frappe (for a gated or private repo, or a model that did not come from Hugging Face). The uploads are deleted after."""
	onnx, chars = _file_bytes(onnx_url), _file_bytes(charset_url)
	if len(onnx) > EXTERNAL_MAX_BYTES:
		frappe.throw(_("The model file is {0} MB: too large for a phone-sized recogniser.").format(len(onnx) // 1048576))
	res = external_add(name, onnx, profile, chars.decode("utf-8"), source, licence, commercial_use, note, digit_map)
	for u in (onnx_url, charset_url):
		if fn := frappe.db.get_value("File", {"file_url": u}):
			frappe.delete_doc("File", fn, ignore_permissions=True, force=True)
	return res
