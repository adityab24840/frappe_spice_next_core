"""Card OCR training: build a bundle from the labels in Frappe, hand it to the PyTorch backend, and import the finished pack.

Only labels a person gave count as ground truth (typed / accepted / corrected / phone). Unverified machine reads (how = ai-read) are left out unless
OCR Settings allows them, and a pack made with them says so in `trained_on` and cannot be marked Shipped.
"""
import csv
import io
import json
import zipfile

import frappe
import requests
from frappe import _

from spice_next_core.card_ocr import service
from spice_next_core.card_ocr.engine import reader as ocr_reader

HUMAN = ("typed", "accepted", "corrected", "phone")
TIMEOUT = 60


def _settings():
	s = frappe.get_single("OCR Settings")
	url = (s.backend_url or "").rstrip("/")
	if not url:
		frappe.throw(_("Set the training backend URL in OCR Settings first."))
	return s, url, s.get_password("backend_token", raise_exception=False) or ""


def _fields(card):
	out = []
	for f in card.fields:
		spec = {"key": f.key, "kind": f.kind, "layout": f.layout or "single"}
		if f.kind == "number" and f.range_low is not None and f.range_high is not None and f.range_high > f.range_low:
			spec["range"] = [f.range_low, f.range_high]
		out.append(spec)
	return out


def export_bundle(card_type, include_ai_read=False):
	"""-> (zip bytes, stats). stats: human, ai_read, pages, cells (rows written), no_crop (labels left out for lack of a crop)."""
	card = frappe.get_doc("OCR Card Type", card_type)
	if not card.template_image or not card.grid_json:
		frappe.throw(_("{0} needs a template image and a grid first.").format(card_type))
	rows = frappe.get_all("OCR Cell", filters={"card_type": card_type, "label": ["is", "set"]}, fields=["name", "scan", "field_key", "visit", "label", "note", "how", "crop"])
	wanted = HUMAN + (("ai-read",) if include_ai_read else ())
	scans = {s.name: s for s in frappe.get_all("OCR Scan", filters={"card_type": card_type}, fields=["name", "page", "writer"])}
	stats = {"human": 0, "ai_read": 0, "pages": 0, "cells": 0, "no_crop": 0}
	buf, pages, labels = io.BytesIO(), set(), []
	with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
		for r in rows:
			if r.note or r.how not in wanted or r.scan not in scans:
				continue
			if not r.crop:
				stats["no_crop"] += 1
				continue
			page = scans[r.scan].page
			z.writestr(f"crops/{r.field_key}/{r.visit}/{page}.png", service._file_bytes(r.crop))
			labels.append({"page": page, "row": r.field_key, "col": r.visit, "label": r.label})
			pages.add(page)
			stats["human" if r.how in HUMAN else "ai_read"] += 1
		out = io.StringIO()
		w = csv.DictWriter(out, ["page", "row", "col", "label"])
		w.writeheader()
		w.writerows(labels)
		z.writestr("labels.csv", out.getvalue())
		z.writestr("template.png", service._file_bytes(card.template_image))
		z.writestr("grid.json", card.grid_json if isinstance(card.grid_json, str) else json.dumps(card.grid_json))
		z.writestr("manifest.json", json.dumps({"card": card.card_key, "fields": _fields(card),
			"writers": {scans[s].page: scans[s].writer for s in scans if scans[s].writer and scans[s].page in pages}}))
	stats["pages"], stats["cells"] = len(pages), len(labels)
	return buf.getvalue(), stats


def _trained_on(human, ai):
	if human and ai:
		return "mixed"
	return "ai-read (unverified)" if ai else "human-verified"


CONFIGS = ("light_lr3e-4", "light_lr1e-4", "nbaug_lr1e-4")      # Studio trainer presets: learning rate and augmentation strength


def start_run(card_type, pretrained=None, include_ai_read=None, target=None, min_n=None, max_epochs=None, config=None):
	"""Build the bundle and start training on the backend. -> the OCR Training Run name."""
	s, url, token = _settings()
	include = bool(s.allow_ai_read) if include_ai_read is None else bool(int(include_ai_read)) and bool(s.allow_ai_read)
	data, stats = export_bundle(card_type, include)
	if stats["pages"] < (s.min_pages or 10):
		frappe.throw(_("{0} labelled page(s): training needs at least {1}. {2} human-verified label(s) so far.").format(stats["pages"], s.min_pages or 10, stats["human"]))
	pre = pretrained or s.default_pretrained or "auto"
	target, min_n, max_epochs = float(target or 85), int(min_n or 20), int(max_epochs or 300)
	if not (50 <= target <= 99.9 and 5 <= min_n <= 500 and 5 <= max_epochs <= 1000):
		frappe.throw(_("Ship target is 50 to 99.9, minimum held-out cells 5 to 500, maximum epochs 5 to 1000."))
	config = config or "light_lr3e-4"
	if config not in CONFIGS:
		frappe.throw(_("Training preset must be one of {0}.").format(", ".join(CONFIGS)))
	run = frappe.get_doc({"doctype": "OCR Training Run", "card_type": card_type, "status": "Queued", "pretrained": pre, "config": config, "target": target, "min_n": min_n, "max_epochs": max_epochs, "include_ai_read": 1 if include else 0,
		"labels_human": stats["human"], "labels_ai_read": stats["ai_read"], "pages": stats["pages"]}).insert()
	try:
		r = requests.post(f"{url}/train", params={"pretrained": pre, "target": target, "min_n": min_n, "max_epochs": max_epochs, "config": config}, data=data, headers={"X-OCR-Token": token}, timeout=TIMEOUT)
	except requests.RequestException as e:
		run.db_set({"status": "Failed", "detail": f"could not reach the training backend: {e}"[:400]})
		frappe.db.commit()
		frappe.throw(_("Could not reach the training backend at {0}.").format(url))
	if r.status_code != 200:
		why = (r.json().get("error") if r.headers.get("content-type", "").startswith("application/json") else r.text)[:400]
		run.db_set({"status": "Failed", "detail": why})
		frappe.db.commit()
		frappe.throw(_("The training backend refused the run: {0}").format(why))
	run.db_set({"status": "Running", "job_id": r.json()["job"], "stage": "starting"})
	return run.name


def _import_pack(run, results, pack_bytes):
	"""Turn the backend's pack into an OCR Card Pack record (status Draft). The pack id and name are set to this card's, not the backend's prefixed one."""
	card = frappe.get_doc("OCR Card Type", run.card_type)
	zin = zipfile.ZipFile(io.BytesIO(pack_bytes))
	out = io.BytesIO()
	newest = frappe.get_all("OCR Card Pack", filters={"card_type": card.name}, pluck="version", order_by="version desc", limit=1)
	version = (newest[0] if newest else 0) + 1
	with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
		for info in zin.infolist():
			data = zin.read(info)
			if info.filename == "manifest.json":
				m = json.loads(data)
				m["id"], m["name"], m["version"] = card.card_key.lower(), card.title, version
				data = json.dumps(m, indent=1).encode()
			zo.writestr(info.filename, data)
	ocr_reader.read_pack(out.getvalue())          # a pack Frappe cannot open is not imported
	url = service._save_private(f"{card.card_key.lower()}_v{version}.cardpack", out.getvalue())
	cv = (results.get("cv_all") or {}).get("exact")
	shipped = (results.get("pack") or {}).get("shipped") or []
	pack = frappe.get_doc({"doctype": "OCR Card Pack", "card_type": card.name, "version": version, "pack_file": url, "status": "Draft",
		"trained_on": _trained_on(run.labels_human, run.labels_ai_read), "cv_exact": (cv * 100) if cv is not None else None,
		"notes": f"From training run {run.name}. Fields that passed the ship gate: {', '.join(shipped) or 'none'}."}).insert()
	return pack.name


def refresh_run(name):
	"""Ask the backend how a run is going; when it finished, fetch the pack and record the result. -> {status, stage, detail, pack}."""
	run = frappe.get_doc("OCR Training Run", name)
	if run.status in ("Done", "Failed"):
		return {"status": run.status, "stage": run.stage, "detail": run.detail, "pack": run.pack}
	_, url, token = _settings()
	h = {"X-OCR-Token": token}
	try:
		st = requests.get(f"{url}/status/{run.job_id}", headers=h, timeout=TIMEOUT).json()
	except (requests.RequestException, ValueError) as e:
		return {"status": run.status, "stage": run.stage, "detail": f"backend not reachable: {e}"[:300], "pack": None}
	if st.get("state") == "failed":
		run.db_set({"status": "Failed", "stage": st.get("stage") or "", "detail": (st.get("detail") or "")[-1000:]})
	elif st.get("state") == "done":
		pb = requests.get(f"{url}/pack/{run.job_id}", headers=h, timeout=TIMEOUT)
		pack = _import_pack(run, st["results"], pb.content)
		cv = (st["results"].get("cv_all") or {}).get("exact")
		run.db_set({"status": "Done", "stage": "done", "detail": "pack imported as a draft", "pack": pack, "results": json.dumps(st["results"], default=str)[:2_000_000],
			"cv_exact": (cv * 100) if cv is not None else None})
	else:
		run.db_set({"stage": st.get("stage") or "", "detail": (st.get("detail") or "")[-500:]})
	run.reload()
	return {"status": run.status, "stage": run.stage, "detail": run.detail, "pack": run.pack}


def backend_health():
	"""-> {ok, busy} or {ok: False, why}."""
	try:
		_, url, _t = _settings()
		return requests.get(f"{url}/health", timeout=10).json()
	except frappe.ValidationError:
		return {"ok": False, "why": "no backend URL in OCR Settings"}
	except (requests.RequestException, ValueError) as e:
		return {"ok": False, "why": str(e)[:200]}


# ---------------------------------------------------------------- read-only questions to the backend (Studio's own modules)
def _ask(path, params=None):
	"""GET a read-only answer from the backend. -> parsed JSON, or {"error": why} when it cannot answer (not reachable, module missing, nothing trained yet)."""
	try:
		_, url, token = _settings()
		r = requests.get(f"{url}{path}", params=params, headers={"X-OCR-Token": token}, timeout=TIMEOUT)
		return r.json() if r.headers.get("content-type", "").startswith("application/json") else {"error": r.text[:200]}
	except frappe.ValidationError:
		return {"error": "no backend URL in OCR Settings"}
	except (requests.RequestException, ValueError) as e:
		return {"error": f"backend not reachable: {e}"[:200]}


def studio_jobs():
	"""Studio's experiment status (Model quality): [{title, question, state, progress, columns, rows, notes, ...}] or {error}."""
	return _ask("/jobs")


def pretrained_list():
	"""The starting weights a run can begin from: [{name, made, images, epochs, generator, default, ok, problem}] or {error}."""
	return _ask("/pretrained")


def datasize(card_type, target=None):
	"""Is there enough labelled data for this card (Studio's evidence + history + learning curve summary) or {error}. Needs at least one finished run."""
	key = frappe.db.get_value("OCR Card Type", card_type, "card_key")
	if not key:
		frappe.throw(_("No such card type."))
	out = _ask(f"/datasize/{key}", {"target": target} if target else None)
	if isinstance(out, dict) and out.get("error"):
		out["hint"] = _("Train once first: the evidence comes from a finished run.")
	return out


def compare_runs(a, b):
	"""Per-field held-out results of two training runs side by side. -> {a, b, rows: [{field, a, b, delta}]}. a and b are OCR Training Run names."""
	def fields(name):
		doc = frappe.get_doc("OCR Training Run", name)
		try:
			res = json.loads(doc.results) if doc.results else {}
		except ValueError:
			res = {}
		return doc, {f["field"]: f for f in (res.get("fields") or [])}
	da, fa = fields(a)
	db_, fb = fields(b)
	if da.card_type != db_.card_type:
		frappe.throw(_("Compare two runs of the same card."))
	rows = []
	for k in sorted(set(fa) | set(fb)):
		x, y = fa.get(k), fb.get(k)
		px = (x["k"] / x["n"]) if x and x.get("n") else None
		py = (y["k"] / y["n"]) if y and y.get("n") else None
		rows.append({"field": k, "a": {"k": x["k"], "n": x["n"], "exact": px, "status": x.get("status")} if x else None,
			"b": {"k": y["k"], "n": y["n"], "exact": py, "status": y.get("status")} if y else None,
			"delta": (py - px) if px is not None and py is not None else None})
	info = lambda d: {"name": d.name, "cv_exact": d.cv_exact, "labels": d.labels_human, "pages": d.pages, "ai_read": bool(d.include_ai_read), "when": str(d.creation)}   # noqa: E731
	return {"a": info(da), "b": info(db_), "rows": rows}
