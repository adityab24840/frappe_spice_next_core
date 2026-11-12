"""Clean-up lab: one photo, aligned to a card pack, run through every photo clean-up method, each read with the pack's reader. A port of Card Studio's
cleanup.analyze. Nothing is stored except small preview images (private Files named cleanup-*, deleted after a day).

A phone photo differs from the flat scans a reader trained on: shadows, washed-out contrast. The methods (engine/normalize.py) are the phone's options;
this shows how each changes what the reader reads, so the pack's default can be chosen on evidence. There is no ground truth for an uploaded photo.
"""
import time
import uuid

import cv2
import frappe
import numpy as np
from frappe import _
from frappe.utils import add_days, now_datetime

from spice_next_core.card_ocr import service
from spice_next_core.card_ocr.engine import normalize as N
from spice_next_core.card_ocr.engine import reader as ocr_reader
from spice_next_core.card_ocr.engine import vision

PREVIEW_WIDTH = 1000


def _purge_old_previews():
	cutoff = add_days(now_datetime(), -1)
	for f in frappe.get_all("File", filters={"file_name": ["like", "cleanup-%"], "creation": ["<", cutoff]}, pluck="name"):
		frappe.delete_doc("File", f, ignore_permissions=True, force=True)


def _packs(pack_name):
	"""[(record name, Pack, Reader)]: the named pack, or the newest pack of every card type."""
	if pack_name:
		names = [pack_name]
	else:
		newest = {}
		for r in frappe.get_all("OCR Card Pack", fields=["name", "card_type", "version"], order_by="version desc"):
			newest.setdefault(r.card_type, r.name)
		names = list(newest.values())
	out = []
	for n in names:
		rec = frappe.get_doc("OCR Card Pack", n)
		pk = ocr_reader.read_pack(service._file_bytes(rec.pack_file))
		out.append((n, pk, ocr_reader.Reader(pk)))
	return out


def _target(pk):
	tpl = cv2.imdecode(np.frombuffer(pk.template_png, np.uint8), cv2.IMREAD_GRAYSCALE)
	return vision.Target(pk.id, tpl, pk.grid)


def analyze(file_url, pack_name=None, methods=None):
	"""-> {pack, inliers, covered_percent, pack_default, methods: [...], disagreements: [...], cells_total, notes}."""
	_purge_old_previews()
	methods = methods or list(N.METHODS)
	bgr = vision.decode_image(service._file_bytes(file_url))
	if bgr is None:
		frappe.throw(_("That file is not a readable image."))
	loaded = _packs(pack_name)
	if not loaded:
		frappe.throw(_("No pack to read with yet: train one first."))
	targets = {pk.id: (name, pk, rd, _target(pk)) for name, pk, rd in loaded}
	winner, H, tried = vision.identify(bgr, [t[3] for t in targets.values()])
	if winner is None:
		top = tried[0] if tried else None
		frappe.throw(_("Unknown card: this photo matches no installed pack.") + (f" {top['card']}: {top['inliers']} matching features ({top['why']})." if top else ""))
	name, pk, rd, target = targets[winner.card]
	pre = pk.manifest.get("preprocess") or {}
	k = int(pre.get("flatten_kernel", 61))
	nz = pre.get("normalize") or {"default": "flatten"}
	ref = nz.get("reference")
	reference = (ref["mean"], ref["std"]) if ref else None
	default = nz.get("default", "flatten")
	warped, covered = vision.warp_with_mask(bgr, H, target)
	uid = uuid.uuid4().hex[:10]
	g = pk.grid
	rows, ncol = g["rows"], len(g["col_lines_top"]) - 1
	results, all_reads = [], {}
	for method in methods:
		if method == "contrast_match" and reference is None:
			results.append({"method": method, "label": N.LABELS[method], "available": False, "note": _("this pack carries no reference (mean and std of its training scans)")})
			continue
		t0 = time.time()
		page, _used = N.normalize_page(method, warped, covered, k, reference)
		reads, ink = {}, 0
		for ri, c, field, _visit, crop in vision.cut_cells(page, target):
			crop = N.stretch_cell(crop) if method in ("cell_stretch", "flatten_cell_stretch") else crop
			if not vision.has_ink(target, crop):
				reads[(ri, c)] = ("", 0.0, False)
				continue
			ink += 1
			text, conf = rd.read(crop, field)
			spec = rd.spec.get(field) or {}
			reads[(ri, c)] = (text, conf, conf < (spec.get("min_confidence") or 0.0))
		filled = [v for v in reads.values() if v[0]]
		s = PREVIEW_WIDTH / page.shape[1]
		small = cv2.resize(page, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
		url = service._save_private(f"cleanup-{uid}-{method}.png", cv2.imencode(".png", small)[1].tobytes())
		all_reads[method] = reads
		results.append({"method": method, "label": N.LABELS[method], "available": True, "image": url, "is_pack_default": method == default, "seconds": round(time.time() - t0, 1),
			"cells": len(reads), "with_ink": ink, "read": len(filled), "flagged": sum(v[2] for v in filled),
			"mean_confidence": round(float(np.mean([v[1] for v in filled])), 3) if filled else None})
	done = [r["method"] for r in results if r["available"]]
	diff = []
	for ri in range(len(rows)):
		for c in range(ncol):
			vals = {m: all_reads[m][(ri, c)] for m in done}
			if len({v[0] for v in vals.values()}) > 1:
				by_col = g.get("axis") == "columns"
				diff.append({"field": g["cols"][c] if by_col else rows[ri], "visit": (ri if by_col else c) + 1,
					"reads": {m: {"text": v[0], "confidence": round(v[1], 2)} for m, v in vals.items()}})
	return {"pack": name, "pack_default": default, "inliers": tried[0]["inliers"], "covered_percent": round(100.0 * float((covered != 0).mean()), 1), "methods": results,
		"disagreements": diff[:80], "disagreements_total": len(diff), "cells_total": len(rows) * ncol,
		"notes": [_("No ground truth for an uploaded photo: compare the reads with the card by eye."),
			_("Reads use the chosen pack's reader. The phone runs the same steps, but this port has not been compared with it pixel for pixel.")]}
