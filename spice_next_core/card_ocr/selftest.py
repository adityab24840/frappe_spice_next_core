"""End-to-end check of the Card OCR services against the live site, with synthetic data only. Everything it creates is deleted afterwards.

    bench --site <site> execute spice_next_core.card_ocr.selftest.run
"""
import json

import cv2
import numpy as np
import frappe

from spice_next_core.card_ocr import service
from spice_next_core.tests import test_card_ocr_engine as syn

CARD = "selftest_card"


def _png(img):
	return cv2.imencode(".png", img)[1].tobytes()


def _file(name, content):
	return frappe.get_doc({"doctype": "File", "file_name": name, "content": content, "is_private": 1}).insert(ignore_permissions=True)


def run():
	created_files, report = [], []

	def check(label, ok, extra=""):
		report.append((label, bool(ok), extra))

	try:
		template = syn.blank_card()
		filled = template.copy()
		written = {(0, 0), (1, 2), (3, 1)}
		for r, c in written:
			syn.write(filled, r, c)
		tf, pf = _file("selftest-template.png", _png(template)), _file("selftest-photo.png", _png(syn.photograph(filled)))
		created_files += [tf.name, pf.name]
		frappe.get_doc({"doctype": "OCR Card Type", "card_key": CARD, "title": "Self test",
			"fields": [{"key": k, "kind": "number", "layout": "single"} for k in syn.ROWS]}).insert(ignore_permissions=True)
		r = service.set_template(CARD, tf.file_url, json.dumps(syn.grid()))
		check("set_template accepts the grid", (r["rows"], r["cols"]) == (4, 3), r)
		try:
			service.set_template(CARD, tf.file_url, json.dumps({**syn.grid(), "y_ref_bot": 1}))
			check("a bad grid is refused", False)
		except frappe.ValidationError:
			check("a bad grid is refused", True)
		d = service.detect_grid(tf.file_url)
		check("detect_grid finds 4 rows x 3 columns on the template", d["grid"] and (len(d["grid"]["rows"]), len(d["grid"]["col_lines_top"]) - 1) == (4, 3), d["grid"] and len(d["grid"]["rows"]))
		more = {**syn.grid(), "rows": ["weight_kg", "pulse", "bp", "extra_field"]}
		r2 = service.set_template(CARD, tf.file_url, json.dumps(more))
		check("a field named by the grid but not by the card type is added as text", r2["added_fields"] == ["extra_field"], r2["added_fields"])
		service.set_template(CARD, tf.file_url, json.dumps(syn.grid()))
		res = service.add_scan(pf.file_url, "auto", "W07", "p-001")
		check("photo identified as the card", res["card"] == CARD and res["status"] in ("ok", "check"), res["card"])
		check("12 cells cut", res["cells"] == 12, res["cells"])
		check("3 cells with ink", res["with_ink"] == 3, res["with_ink"])
		cells = frappe.get_all("OCR Cell", filters={"scan": res["scan"]}, fields=["field_key", "visit", "has_ink", "crop"])
		check("every cell has a private crop", len(cells) == 12 and all(c.crop and c.crop.startswith("/private/") for c in cells))
		created_files += frappe.get_all("File", filters={"attached_to_doctype": ["is", "not set"], "file_name": ["like", f"{res['scan']}-%"]}, pluck="name")
		try:
			service.add_scan(pf.file_url, "auto", "Aditya Bhatt")
			check("a writer name is refused", False)
		except frappe.ValidationError:
			check("a writer name is refused", True)
		try:
			service.suggest(CARD)
			check("suggest without a pack says so", False)
		except frappe.ValidationError:
			check("suggest without a pack says so", True)
	finally:
		frappe.db.rollback()
		for n in set(created_files):
			if frappe.db.exists("File", n):
				frappe.delete_doc("File", n, ignore_permissions=True, force=True)
		for f in frappe.get_all("File", filters={"file_name": ["like", "SCAN-selftest_card%"]}, pluck="name"):
			frappe.delete_doc("File", f, ignore_permissions=True, force=True)
		frappe.db.commit()
	for label, ok, extra in report:
		print(("PASS " if ok else "FAIL ") + label + (f"  ({extra})" if extra != "" else ""))
	print("RESULT:", "all passed" if all(ok for _, ok, _ in report) else "FAILURES")


FAKE_TRAINER = """
import json, sys, zipfile
from pathlib import Path
run = Path(sys.argv[1]); run.mkdir(parents=True, exist_ok=True)
pack = run / "fr_x_v1.cardpack"
with zipfile.ZipFile(pack, "w") as z:
    z.writestr("manifest.json", json.dumps({"id": "fr_selftest_train", "version": 1, "name": "x", "reader": {"input": {"name": "image"}, "output": {"name": "logits"}}}))
    z.writestr("fields.json", json.dumps({"classes": ["0"], "blank_idx": 0, "fields": []}))
    z.writestr("grid.json", "{}")
    for n in ("template.png", "reader.onnx"):
        z.writestr(n, b"x")
json.dump({"pack": {"path": str(pack), "shipped": ["weight_kg"]}, "cv_all": {"exact": 0.73}, "fields": []}, open(run / "results.json", "w"))
json.dump({"stage": "done", "detail": "pack written", "elapsed": 1}, open(run / "status.json", "w"))
"""


def run_training():
	"""End-to-end check of the training loop: bundle -> real backend server (fake trainer) -> status -> pack import. Synthetic data only; cleaned up after.

	    bench --site <site> execute spice_next_core.card_ocr.selftest.run_training
	"""
	import subprocess
	import sys
	import tempfile
	import threading
	import time
	import zipfile
	from pathlib import Path

	from spice_next_core.card_ocr import training
	from spice_next_core.card_ocr.backend import server

	card_key, report, files = "selftest_train", [], []

	def check(label, ok, extra=""):
		report.append((label, bool(ok), extra))

	def runner(studio, card, run_dir, pretrained="auto", **opts):
		Path(run_dir).mkdir(parents=True, exist_ok=True)
		return subprocess.Popen([sys.executable, "-c", FAKE_TRAINER, str(run_dir)])

	tmp = tempfile.TemporaryDirectory()
	httpd, _state = server.serve("127.0.0.1", 0, tmp.name, tmp.name + "/data", "tok", runner)
	threading.Thread(target=httpd.serve_forever, daemon=True).start()
	from frappe.utils.password import get_decrypted_password, set_encrypted_password

	before = {k: frappe.db.get_single_value("OCR Settings", k) for k in ("backend_url", "default_pretrained", "min_pages", "allow_ai_read")}
	old_token = get_decrypted_password("OCR Settings", "OCR Settings", "backend_token", raise_exception=False)
	try:
		tf = _file("selftest-tpl.png", _png(syn.blank_card()))
		files.append(tf.name)
		frappe.get_doc({"doctype": "OCR Card Type", "card_key": card_key, "title": "Self test train",
			"fields": [{"key": "weight_kg", "kind": "number", "layout": "single", "range_low": 30, "range_high": 150}]}).insert(ignore_permissions=True)
		service.set_template(card_key, tf.file_url, json.dumps({**syn.grid(), "rows": ["weight_kg"], "row_lines_by_col": [[300.0, 500.0]] * 3,
			"col_lines_top": [200.0, 700.0, 1200.0, 1700.0], "col_lines_bot": [200.0, 700.0, 1200.0, 1700.0]}))
		crop = _png(syn.blank_card()[300:500, 200:700])
		for i in range(10):
			cf = _file(f"selftest-crop-{i}.png", crop)
			files.append(cf.name)
			scan = frappe.get_doc({"doctype": "OCR Scan", "card_type": card_key, "page": f"p-{i:02d}", "writer": f"W{i % 6:02d}"}).insert(ignore_permissions=True)
			frappe.get_doc({"doctype": "OCR Cell", "scan": scan.name, "field_key": "weight_kg", "visit": "c1", "has_ink": 1, "crop": cf.file_url,
				"label": str(50 + i), "how": "typed"}).insert(ignore_permissions=True)
		# a machine read that must stay out unless allowed
		scan = frappe.get_doc({"doctype": "OCR Scan", "card_type": card_key, "page": "p-ai", "writer": "W01"}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "OCR Cell", "scan": scan.name, "field_key": "weight_kg", "visit": "c1", "has_ink": 1, "crop": cf.file_url,
			"label": "99", "how": "ai-read"}).insert(ignore_permissions=True)
		data, st = training.export_bundle(card_key, include_ai_read=False)
		check("bundle holds the 10 human labels and no machine read", (st["human"], st["ai_read"], st["pages"]) == (10, 0, 10), st)
		check("bundle is a zip with labels, crops, grid, template", {"labels.csv", "grid.json", "template.png", "manifest.json"} <= set(zipfile.ZipFile(__import__("io").BytesIO(data)).namelist()))
		_, st2 = training.export_bundle(card_key, include_ai_read=True)
		check("machine reads are included only when asked", (st2["human"], st2["ai_read"]) == (10, 1), st2)
		for k, v in {"backend_url": f"http://127.0.0.1:{httpd.server_address[1]}", "default_pretrained": "auto", "min_pages": 10, "allow_ai_read": 0}.items():
			frappe.db.set_single_value("OCR Settings", k, v)
		set_encrypted_password("OCR Settings", "OCR Settings", "tok", "backend_token")
		check("backend health", training.backend_health().get("ok") is True)
		run_name = training.start_run(card_key)
		check("run started", frappe.db.get_value("OCR Training Run", run_name, "status") == "Running")
		res = {}
		for _ in range(100):
			res = training.refresh_run(run_name)
			if res["status"] != "Running":
				break
			time.sleep(0.2)
		check("run finished as Done", res.get("status") == "Done", res)
		pack = frappe.get_doc("OCR Card Pack", res["pack"]) if res.get("pack") else None
		check("pack imported as a draft, trained on human-verified labels", pack and pack.status == "Draft" and pack.trained_on == "human-verified", pack and pack.trained_on)
		check("cross-validation score recorded", pack and abs(pack.cv_exact - 73) < 0.01, pack and pack.cv_exact)
		if pack:
			zf = zipfile.ZipFile(__import__("io").BytesIO(service._file_bytes(pack.pack_file)))
			m = json.loads(zf.read("manifest.json"))
			check("pack id and name are this card's, not the backend's", (m["id"], m["name"]) == (card_key, "Self test train"), (m["id"], m["name"]))
			files += frappe.get_all("File", filters={"file_url": pack.pack_file}, pluck="name")
			try:
				pack.status, pack.trained_on = "Shipped", "ai-read (unverified)"
				pack.save()
				check("an unverified pack cannot be shipped", False)
			except frappe.ValidationError:
				check("an unverified pack cannot be shipped", True)
	finally:
		httpd.shutdown()
		httpd.server_close()
		frappe.db.rollback()
		for k, v in before.items():
			frappe.db.set_single_value("OCR Settings", k, v)
		set_encrypted_password("OCR Settings", "OCR Settings", old_token or "", "backend_token")
		for f in frappe.get_all("File", filters={"file_name": ["like", "selftest%"]}, pluck="name") + frappe.get_all("File", filters={"file_name": ["like", "selftest_train%"]}, pluck="name") + files:
			if frappe.db.exists("File", f):
				frappe.delete_doc("File", f, ignore_permissions=True, force=True)
		frappe.db.commit()
		tmp.cleanup()
	for label, ok, extra in report:
		print(("PASS " if ok else "FAIL ") + label + (f"  ({extra})" if extra != "" else ""))
	print("RESULT:", "all passed" if all(ok for _, ok, _ in report) else "FAILURES")


def run_batch1():
	"""Live check of: aligned scans, blank-card estimate and ink flags, re-cut after a grid change, writers, template ID test, queue views.

	    bench --site <site> execute spice_next_core.card_ocr.selftest.run_batch1
	"""
	import cv2
	import numpy as np

	from spice_next_core.card_ocr import idtest, labeling, writers

	card_key, report, files = "selftest_b1", [], []

	def check(label, ok, extra=""):
		report.append((label, bool(ok), extra))

	try:
		template = syn.blank_card()
		x0, y0 = syn.COL_X[2] + 60, syn.ROW_Y[2] + 60            # a printed mark in cell (row 2, visit 3) of the BLANK card
		cv2.polylines(template, [np.int32([[x0, y0], [x0 + 200, y0 + 70]]).reshape(-1, 1, 2)], False, 0, 8)
		tf = _file("selftest-b1-template.png", _png(template))
		files.append(tf.name)
		frappe.get_doc({"doctype": "OCR Card Type", "card_key": card_key, "title": "Self test b1",
			"fields": [{"key": k, "kind": "number", "layout": "single"} for k in syn.ROWS]}).insert(ignore_permissions=True)
		service.set_template(card_key, tf.file_url, json.dumps(syn.grid()))
		results, first_mark = [], None
		mark = lambda scan: frappe.db.get_value("OCR Cell", {"scan": scan, "field_key": "bp", "visit": "c3"}, "has_ink")   # noqa: E731
		for i in range(6):
			filled = template.copy()
			for r, c in ((i % 4, 0), ((i + 1) % 4, 1)):
				syn.write(filled, r, c)
			pf = _file(f"selftest-b1-photo-{i}.png", _png(syn.photograph(filled)))
			files.append(pf.name)
			results.append(service.add_scan(pf.file_url, card_key, "W07" if i < 3 else "W08", f"p-{i:02d}"))
			if i == 0:
				first_mark = int(mark(results[0]["scan"]))          # read right after the first scan, before any blank estimate exists
		check("every scan stored its aligned image", all(frappe.db.get_value("OCR Scan", r["scan"], "aligned_image") for r in results))
		check("before there is a blank estimate, a printed mark counts as ink", first_mark == 1, first_mark)
		blank = frappe.db.get_value("OCR Card Type", card_key, ["blank_image", "blank_scans"], as_dict=True)
		check("blank-card estimate built from the scans", blank.blank_image and blank.blank_scans >= 5, blank.blank_scans)
		check("after it, the printed mark is no longer ink in any scan", all(int(mark(r["scan"])) == 0 for r in results), [int(mark(r["scan"])) for r in results])
		written = frappe.db.count("OCR Cell", {"card_type": card_key, "has_ink": 1})
		check("handwriting still counts (12 written cells)", written == 12, written)
		# writers
		st = writers.status(card_key)
		check("no labelled pages yet", st["split_by"] == "page" and st["labeled_pages"] == 0, st["message"])
		a = writers.assign(card_key, "W09", "p-01", "p-03")
		check("writers assigned to a page range", a["set"] == 3 and frappe.db.get_value("OCR Scan", results[2]["scan"], "writer") == "W09", a)
		try:
			writers.assign(card_key, "Aditya Bhatt", "p-01", "p-02")
			check("a writer name is refused", False)
		except frappe.ValidationError:
			check("a writer name is refused", True)
		# queue views
		scan = results[0]["scan"]
		cells = frappe.get_all("OCR Cell", filters={"scan": scan, "has_ink": 1}, pluck="name")
		frappe.db.set_value("OCR Cell", cells[0], {"label": "57", "ai_text": "58", "how": "corrected"})
		frappe.db.set_value("OCR Cell", cells[1], {"label": "60", "how": "phone"})
		d = labeling.queue(card_key, show="disagree")
		p = labeling.queue(card_key, show="phone")
		check("'disagree' shows only cells a person changed from the suggestion", [c["name"] for c in d["cells"]] == [cells[0]], d["left"])
		check("'phone' shows the phone corrections", [c["name"] for c in p["cells"]] == [cells[1]], p["left"])
		# re-cut after a grid change: drop the last row
		g = syn.grid()
		g["rows"], g["row_lines_by_col"], g["y_ref_bot"] = syn.ROWS[:3], [[float(y) for y in syn.ROW_Y[:4]]] * 3, float(syn.ROW_Y[3])
		service.set_template(card_key, tf.file_url, json.dumps(g), sync_fields=0)
		before = frappe.db.count("OCR Cell", {"card_type": card_key})
		rc = service.recut(card_key)
		after = frappe.db.count("OCR Cell", {"card_type": card_key})
		check("re-cut touched every scan", rc["scans"] == 6, rc)
		check("cells of the removed row were deleted (6 scans x 3 visits)", rc["removed"] == 18 and before - after == 18, rc)
		check("labels survived the re-cut", frappe.db.get_value("OCR Cell", cells[0], "label") == "57")
		# ID test with one card
		it = idtest.run()
		check("template ID test: the card matches itself", it["cards"] >= 1 and it["self_ok"] == it["cards"] and it["wrongly_accepted"] == 0, it)
	finally:
		frappe.db.rollback()
		for f in frappe.get_all("File", filters=[["file_name", "like", "selftest-b1%"]], pluck="name") + frappe.get_all("File", filters=[["file_name", "like", "SCAN-selftest_b1%"]], pluck="name") + \
				frappe.get_all("File", filters=[["file_name", "like", "selftest_b1-blank%"]], pluck="name") + files:
			if frappe.db.exists("File", f):
				frappe.delete_doc("File", f, ignore_permissions=True, force=True)
		frappe.db.commit()
	for label, ok, extra in report:
		print(("PASS " if ok else "FAIL ") + label + (f"  ({extra})" if extra != "" else ""))
	print("RESULT:", "all passed" if all(ok for _, ok, _ in report) else "FAILURES")


def run_batch2():
	"""Live check with the REAL anc_v7 pack and a real ANC page from ~/Downloads/EPI_ANC_NCD_cards/anc (patient data: only counts are printed, and
	everything stored is deleted afterwards): scan -> cells -> AI suggestions with a real reader -> Clean-up lab.

	    bench --site <site> execute spice_next_core.card_ocr.selftest.run_batch2
	"""
	import os
	import time

	from spice_next_core.card_ocr import cleanup_lab

	pack_path = os.environ.get("CARD_OCR_TEST_PACK", "")           # a real .cardpack and one filled card photo: patient data stays on the machine, never in the repo
	page_path = os.environ.get("CARD_OCR_TEST_PAGE", "")
	report, files = [], []

	def check(label, ok, extra=""):
		report.append((label, bool(ok), extra))

	if not (os.path.exists(pack_path) and os.path.exists(page_path)):
		print("SKIP: the anc_v7 pack or the Downloads ANC page is missing")
		return
	try:
		pf = _file("selftest-b2-pack.cardpack", open(pack_path, "rb").read())
		jf = _file("selftest-b2-page.jpg", open(page_path, "rb").read())
		files += [pf.name, jf.name]
		rec = frappe.get_doc({"doctype": "OCR Card Pack", "card_type": "anc_test", "version": 7, "pack_file": pf.file_url, "status": "Draft", "trained_on": "human-verified"}).insert(ignore_permissions=True)
		t0 = time.time()
		res = service.add_scan(jf.file_url, "anc_test", "", "p-b2")
		check("a real ANC page is matched to anc_test and cut", res["card"] == "anc_test" and res["cells"] == 132, (res["status"], res["inliers"], res["cells"], res["with_ink"]))
		check("handwriting is found (more than 20 cells)", res["with_ink"] > 20, res["with_ink"])
		s = service.suggest("anc_test", pack=rec.name)
		got = frappe.db.count("OCR Cell", {"scan": res["scan"], "ai_text": ["is", "set"], "has_ink": 1})
		check("AI suggestions are written beside the cells with ink", s["read"] == res["with_ink"] and got > 10, {"read": s["read"], "with_text": got, "source": s["source"]})
		check("suggestions are not labels", frappe.db.count("OCR Cell", {"scan": res["scan"], "label": ["is", "set"]}) == 0)
		lab = cleanup_lab.analyze(jf.file_url, rec.name)
		ok = [m for m in lab["methods"] if m["available"]]
		files += frappe.get_all("File", filters=[["file_name", "like", "cleanup-%"]], pluck="name")
		check("Clean-up lab matched the pack and ran the methods", lab["inliers"] > 40 and len(ok) >= 4, {"inliers": lab["inliers"], "methods": [(m["method"], m["with_ink"], m["read"]) for m in ok], "covered%": lab["covered_percent"]})
		check("each method produced a preview image", all(m["image"] for m in ok))
		print("time for the whole check: %.0fs" % (time.time() - t0))
	finally:
		frappe.db.rollback()
		for f in frappe.get_all("File", filters=[["file_name", "like", "selftest-b2%"]], pluck="name") + frappe.get_all("File", filters=[["file_name", "like", "cleanup-%"]], pluck="name") + \
				frappe.get_all("File", filters=[["file_name", "like", "SCAN-anc_test-p-b2%"]], pluck="name") + files + \
				frappe.get_all("File", filters=[["file_name", "like", "anc_test-blank%"]], pluck="name"):
			if frappe.db.exists("File", f):
				frappe.delete_doc("File", f, ignore_permissions=True, force=True)
		frappe.db.commit()
	for label, ok_, extra in report:
		print(("PASS " if ok_ else "FAIL ") + label + (f"  ({extra})" if extra != "" else ""))
	print("RESULT:", "all passed" if all(o for _, o, _ in report) else "FAILURES")


def run_batch3():
	"""Live check of PDF and HEIC upload, synthetic data only.

	    bench --site <site> execute spice_next_core.card_ocr.selftest.run_batch3
	"""
	import io

	import numpy as np
	import pillow_heif
	from PIL import Image

	pillow_heif.register_heif_opener()
	card_key, report, files = "selftest_b3", [], []

	def check(label, ok, extra=""):
		report.append((label, bool(ok), extra))

	try:
		template = syn.blank_card()
		filled = template.copy()
		for r, c in ((0, 0), (1, 2)):
			syn.write(filled, r, c)
		photo = cv2.cvtColor(syn.photograph(filled), cv2.COLOR_BGR2RGB)
		tf = _file("selftest-b3-template.png", _png(template))
		files.append(tf.name)
		frappe.get_doc({"doctype": "OCR Card Type", "card_key": card_key, "title": "Self test b3", "fields": [{"key": k, "kind": "number", "layout": "single"} for k in syn.ROWS]}).insert(ignore_permissions=True)
		service.set_template(card_key, tf.file_url, json.dumps(syn.grid()))
		# a PDF: page 1 is a photo of the card, page 2 is not a card
		buf = io.BytesIO()
		other = np.full((1000, 800, 3), 255, np.uint8)
		for i in range(40):
			cv2.putText(other, f"X{i * 7}", (30 + (i % 5) * 150, 60 + (i // 5) * 110), cv2.FONT_HERSHEY_PLAIN, 3, (0, 0, 0), 2)
		Image.fromarray(photo).save(buf, format="PDF", save_all=True, append_images=[Image.fromarray(other)])
		pdf = _file("selftest-b3-two-pages.pdf", buf.getvalue())
		files.append(pdf.name)
		r = service.add_scan(pdf.file_url, card_key, "W07", "pdf")
		check("a PDF gives one result per page", r.get("pages") == 2 and len(r["results"]) == 2, r.get("pages"))
		check("page 1 (a card photo) was matched and cut", r["results"][0]["card"] == card_key and r["results"][0]["cells"] == 12, (r["results"][0]["status"], r["results"][0]["inliers"]))
		check("page 2 (not a card) was rejected and stored nothing", r["results"][1]["scan"] is None)
		check("pages got their own ids", frappe.db.exists("OCR Scan", f"SCAN-{card_key}-pdf-p001"), "pdf-p001")
		# a HEIC photo named .png (what a phone or a Mac screenshot can produce)
		hb = io.BytesIO()
		Image.fromarray(photo).save(hb, format="HEIF")
		hf = _file("selftest-b3-photo.png", hb.getvalue())
		files.append(hf.name)
		check("the file really is HEIC", hb.getvalue()[4:12] == b"ftypheic" or b"ftyp" in hb.getvalue()[:16])
		h = service.add_scan(hf.file_url, card_key, "", "heic-1")
		check("a HEIC photo is matched and cut", h["card"] == card_key and h["cells"] == 12, (h["status"], h["inliers"]))
		try:
			service.add_scan(_file("selftest-b3-junk.png", b"not an image").file_url, card_key)
			check("junk is refused with a clear message", False)
		except frappe.ValidationError as e:
			check("junk is refused with a clear message", "not a readable image" in str(e) or "pillow-heif" in str(e), str(e)[:60])
	finally:
		frappe.db.rollback()
		for f in frappe.get_all("File", filters=[["file_name", "like", "selftest-b3%"]], pluck="name") + frappe.get_all("File", filters=[["file_name", "like", "SCAN-selftest_b3%"]], pluck="name") + \
				frappe.get_all("File", filters=[["file_name", "like", "selftest_b3-blank%"]], pluck="name") + files:
			if frappe.db.exists("File", f):
				frappe.delete_doc("File", f, ignore_permissions=True, force=True)
		frappe.db.commit()
	for label, ok, extra in report:
		print(("PASS " if ok else "FAIL ") + label + (f"  ({extra})" if extra != "" else ""))
	print("RESULT:", "all passed" if all(o for _, o, _ in report) else "FAILURES")


def run_batch4():
	"""Live check of the template editor and reader grid on the REAL ANC template (blank card, no patient data), against a temporary card type.

	    bench --site <site> execute spice_next_core.card_ocr.selftest.run_batch4
	"""
	card_key, report = "selftest_tpl", []

	def check(label, ok, extra=""):
		report.append((label, bool(ok), extra))

	src = frappe.db.get_value("OCR Card Type", "anc_test", "template_image")
	if not src:
		print("SKIP: anc_test has no template")
		return
	try:
		a = service.analyze_template(src, 0, 1)
		check("analyze: the photo is levelled and its cells found", a["layout"]["stats"]["cells"] > 100, {"cells": a["layout"]["stats"]["cells"], "tilt": a["tilt"]["tilt_deg"], "straightened": a["tilt"]["straightened"]})
		m0 = (a["matches"] or [{}])[0]
		check("analyze: Studio's verdict is known for the card's own template, with a 0-1 score", a["verdict"] == "known" and m0.get("name") == "anc_test" and 0.67 <= m0.get("score", 0) <= 1 and a["thresholds"] == {"high": 0.67, "mid": 0.25}, a["matches"][:1])
		check("analyze: the working copy is private", a["image"].startswith("/private/"))
		r = service.analyze_template(src, 90, 0)
		orig = service._gray(src)
		check("a quarter turn swaps width and height of the original", (r["width"], r["height"]) == (orig.shape[0], orig.shape[1]), (r["width"], r["height"]))
		check("a blank photo scores new", service.match_templates(np.full((900, 700, 3), 255, np.uint8))[1] == "new")
		fields = a["layout"]["fields"]
		for label, bad in (("a cell without a name", [{**fields[0], "name": " "}] + fields[1:5]), ("a cell with no size", [{**fields[0], "w": 0}] + fields[1:5]),
				("duplicate cell names", [dict(fields[0]), {**fields[1], "name": fields[0]["name"]}])):
			try:
				service.save_layout(card_key, a["image"], bad, create=1)
				check(label + " is refused", False)
			except frappe.ValidationError:
				check(label + " is refused", True)
		check("a refused save made no card type", not frappe.db.exists("OCR Card Type", card_key))
		try:
			service.save_layout("bad name!", a["image"], fields, create=1)
			check("a bad template name is refused", False)
		except frappe.ValidationError:
			check("a bad template name is refused", True)
		try:
			service.save_layout("anc_test", a["image"], fields, create=1)
			check("create refuses a name that is taken", False)
		except frappe.ValidationError:
			check("create refuses a name that is taken", True)
		s1 = service.save_layout(card_key, a["image"], fields, create=1, title="Self test template")
		check("create: the card type is made with version 1 and a private image", s1["version"] == 1 and s1["cells"] == len(fields) and s1["image"].startswith("/private/"), s1)
		check("the card is not ready to match until a version has a grid", card_key not in service.ready_cards())
		p = service.preview_grid(card_key, {"axis": "rows", "data_cols": 6})
		g = p.get("grid") or {}
		check("preview on the levelled photo: a valid grid with 6 visit columns", g and len(g["col_lines_top"]) - 1 == 6 and p["errors"] == [], (len(g.get("rows", [])), p.get("errors")))
		check("preview saves nothing", not frappe.db.get_value("OCR Template Version", {"card_type": card_key, "version": 1}, "grid_json"))
		try:
			service.save_grid(card_key, {"axis": "rows", "label_cols": 30})
			check("a grid that cannot be made is refused", False)
		except frappe.ValidationError:
			check("a grid that cannot be made is refused", True)
		sv = service.save_grid(card_key, {"axis": "rows", "data_cols": 6})
		card = frappe.get_doc("OCR Card Type", card_key)
		check("save grid: stored on v1, v1 in use, status Gridded, fields added", sv["version"] == 1 and card.template_version == 1 and card.status == "Gridded" and card.grid_json and len(card.fields) == sv["rows"], {"rows": sv["rows"]})
		check("the saved card can be matched against (a target builds)", service.card_target(card_key).n_cols == 6)
		# update mode: a second Save is version 2, and v1 stays
		edit = [dict(f) for f in fields[:-1]]
		s2 = service.save_layout(card_key, s1["image"], edit, base_version=1)
		check("update: the second save is v2, made from v1, with one cell fewer", s2["version"] == 2 and s2["cells"] == len(fields) - 1, s2)
		card.reload()
		check("v2 has no grid yet, so scans keep using v1", card.template_version == 1 and service.card_target(card_key).n_cols == 6)
		lt = next(t for t in service.list_templates() if t["name"] == card_key)
		check("the list shows both versions, v1 with its grid, v2 without", [v["version"] for v in lt["versions"]] == [1, 2] and lt["versions"][0]["grid"] and not lt["versions"][1]["grid"] and lt["in_use"] == 1, lt["versions"])
		check("v1 is still there with its own cells", len(service.get_version(card_key, 1)["layout"]["fields"]) == len(fields) and len(service.get_version(card_key, 2)["layout"]["fields"]) == len(fields) - 1)
		check("every version keeps a readable image", all(service._gray(service.get_version(card_key, k)["image"]) is not None for k in (1, 2)))
		sv2 = service.save_grid(card_key, {"axis": "rows", "data_cols": 6})
		card.reload()
		check("grid on v2: v2 is now in use", sv2["version"] == 2 and card.template_version == 2)
		sv1 = service.save_grid(card_key, {"axis": "rows", "data_cols": 6}, version=1)
		card.reload()
		check("grid redone on v1 does not move scans back to it", sv1["version"] == 1 and card.template_version == 2)
		# a match on the updated card type still says known and names v2
		best = service.match_templates(service._gray(service.get_version(card_key, 2)["image"]))[0][0]
		check("matching a template photo names the newest version", best["version"] == 2 and best["score"] >= 0.67, best)
		try:
			service.delete_version("nope_none", 1)
			check("deleting a version of a missing card type is refused", False)
		except (frappe.ValidationError, frappe.DoesNotExistError):
			check("deleting a version of a missing card type is refused", True)
		service.delete_version(card_key, 1)
		card.reload()
		check("delete v1: v2 stays, in use", card.template_version == 2 and [v["version"] for v in next(t for t in service.list_templates() if t["name"] == card_key)["versions"]] == [2])
		scan = frappe.get_doc({"doctype": "OCR Scan", "card_type": card_key, "page": "selftest-del", "status": "Cut", "template_version": 2, "inliers": 100}).insert()
		try:
			service.delete_version(card_key, 2)
			check("a version that scans were cut with is not deleted", False)
		except frappe.ValidationError:
			check("a version that scans were cut with is not deleted", True)
		frappe.delete_doc("OCR Scan", scan.name, ignore_permissions=True, force=True)
		r = service.delete_version(card_key, 2)
		check("deleting the only version of an unused card type deletes the card type", r["deleted_card_type"] and not frappe.db.exists("OCR Card Type", card_key))
	finally:
		frappe.db.rollback()
		for f in frappe.get_all("File", filters=[["file_name", "like", "tplwork-%"]], pluck="name") + frappe.get_all("File", filters=[["file_name", "like", "selftest_tpl-template%"]], pluck="name"):
			if frappe.db.exists("File", f):
				frappe.delete_doc("File", f, ignore_permissions=True, force=True)
		frappe.db.commit()
	for label, ok, extra in report:
		print(("PASS " if ok else "FAIL ") + label + (f"  ({extra})" if extra != "" else ""))
	print("RESULT:", "all passed" if all(o for _, o, _ in report) else "FAILURES")


def run_batch5():
	"""Card checks on a real database: the card type's check fields are validated, and card_checks puts a suggestion and a note beside a dissenting date.

	    bench --site <site> execute spice_next_core.card_ocr.selftest.run_batch5
	"""
	card_key, report = "selftest_chk", []

	def check(label, ok, extra=""):
		report.append((label, bool(ok), extra))

	try:
		fields = [{"key": k, "kind": "date", "layout": "stacked", "decode": "greedy"} for k in ("bcg", "penta", "opv")] + [{"key": "visit_date", "kind": "date", "layout": "single", "decode": "greedy"}]
		doc = frappe.get_doc({"doctype": "OCR Card Type", "card_key": card_key, "title": "Self test checks", "fields": fields})
		for label, bad in (("a check naming a field the card does not have", {"same_day_fields": "bcg, nope"}), ("a same-day rule with one field", {"same_day_fields": "bcg"})):
			try:
				frappe.get_doc({**doc.as_dict(), **bad}).insert(ignore_permissions=True)
				check(label + " is refused", False)
			except frappe.ValidationError:
				check(label + " is refused", True)
		doc.same_day_fields, doc.increasing_fields = "bcg, penta, opv", "visit_date"
		doc.insert(ignore_permissions=True)
		scan = frappe.get_doc({"doctype": "OCR Scan", "card_type": card_key, "page": "selftest-chk", "status": "Cut", "inliers": 100}).insert()
		reads = {("bcg", "c1"): "5/3/26", ("penta", "c1"): "5/3/26", ("opv", "c1"): "6/3/26", ("visit_date", "c1"): "9/1/26", ("visit_date", "c2"): "8/1/26"}
		for (f, v), t in reads.items():
			frappe.get_doc({"doctype": "OCR Cell", "scan": scan.name, "card_type": card_key, "field_key": f, "visit": v, "has_ink": 1, "ai_text": t, "ai_confidence": 0.9}).insert()
		n = service.card_checks(card_key)
		cells = {(c.field_key, c.visit): c for c in frappe.get_all("OCR Cell", filters={"scan": scan.name}, fields=["field_key", "visit", "ai_text", "ai_suggestion", "ai_note"])}
		check("two cells agree on a date, the third gets it as a suggestion and keeps its own read", n == 2 and cells["opv", "c1"].ai_suggestion == "5/3/26" and cells["opv", "c1"].ai_text == "6/3/26" and "6/3/26" in cells["opv", "c1"].ai_note, cells["opv", "c1"])
		check("the cells that agree are left alone", not cells["bcg", "c1"].ai_note and not cells["penta", "c1"].ai_note)
		check("an earlier visit date is noted with nothing suggested", cells["visit_date", "c2"].ai_note and not cells["visit_date", "c2"].ai_suggestion, cells["visit_date", "c2"].ai_note)
		frappe.db.set_value("OCR Cell", {"scan": scan.name, "field_key": "opv"}, "ai_text", "5/3/26")
		service.card_checks(card_key)
		check("a doubt that no longer holds is cleared", not frappe.db.get_value("OCR Cell", {"scan": scan.name, "field_key": "opv"}, "ai_note"))
		frappe.db.set_value("OCR Card Type", card_key, {"same_day_fields": "", "increasing_fields": ""})
		check("a card type that asks for no checks does nothing", service.card_checks(card_key) == 0)
	finally:
		frappe.db.rollback()
		frappe.db.commit()
	for label, ok, extra in report:
		print(("PASS " if ok else "FAIL ") + label + (f"  ({extra})" if extra != "" else ""))
	print("RESULT:", "all passed" if all(o for _, o, _ in report) else "FAILURES")
