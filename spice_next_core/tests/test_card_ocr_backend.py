"""Tests for the training backend (bridge + server): real HTTP on a local port, a fake trainer instead of PyTorch. No Frappe, no database."""

import io
import json
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
import zlib
from pathlib import Path

from spice_next_core.card_ocr.backend import bridge, server

TOKEN = "s3cret"


def png(w, h):
	"""A minimal valid white PNG of w x h."""
	def chunk(t, d):
		c = struct.pack(">I", len(d)) + t + d
		return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
	raw = b"".join(b"\x00" + b"\xff" * w for _ in range(h))
	return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


GRID = {"image_size": [2000, 1400], "rows": ["weight_kg", "pulse"], "y_ref_top": 300.0, "y_ref_bot": 900.0,
	"col_lines_top": [200.0, 700.0, 1200.0], "col_lines_bot": [200.0, 700.0, 1200.0], "row_lines_by_col": [[300.0, 600.0, 900.0], [300.0, 600.0, 900.0]]}


def bundle(card="smoke", fields=None, extra=None, labels=None, writers=None, tpl=(1000, 700)):
	fields = fields or [{"key": "weight_kg", "kind": "number", "range": [30, 150], "layout": "single"}, {"key": "pulse", "kind": "number"}]
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, "w") as z:
		z.writestr("manifest.json", json.dumps({"card": card, "fields": fields, "writers": writers or {"p-1": "W07"}}))
		z.writestr("template.png", png(*tpl))
		z.writestr("grid.json", json.dumps(GRID))
		z.writestr("labels.csv", labels if labels is not None else "page,row,col,label\np-1,weight_kg,c1,57\np-2,pulse,c2,80\n")
		z.writestr("crops/weight_kg/c1/p-1.png", png(20, 10))
		z.writestr("crops/pulse/c2/p-2.png", png(20, 10))
		for name, data in (extra or {}).items():
			z.writestr(name, data)
	return buf.getvalue()


class Install(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.studio = Path(self.tmp.name)

	def tearDown(self):
		self.tmp.cleanup()

	def test_installs_into_studio_layout_under_a_prefix(self):
		name, stats = bridge.install(bundle(), self.studio)
		self.assertEqual(name, "fr_smoke")
		self.assertEqual(stats, {"labels": 2, "pages": 2, "crops": 2})
		self.assertTrue((self.studio / "cards/fr_smoke/crops/weight_kg/c1/p-1.png").is_file())
		self.assertTrue((self.studio / "templates/fr_smoke/v1/template.png").is_file())
		self.assertEqual(json.loads((self.studio / "cards/fr_smoke/fields.json").read_text())["fields"]["weight_kg"], {"kind": "number", "range": [30, 150], "layout": "single"})
		self.assertIn("p-1,W07", (self.studio / "cards/fr_smoke/writers.csv").read_text())

	def test_grid_is_rescaled_to_the_template(self):
		bridge.install(bundle(tpl=(1000, 700)), self.studio)
		g = json.loads((self.studio / "templates/fr_smoke/v1/grid.json").read_text())
		self.assertEqual(g["image_size"], [1000, 700])
		self.assertEqual(g["col_lines_top"], [100.0, 350.0, 600.0])
		self.assertEqual(g["row_lines_by_col"][0], [150.0, 300.0, 450.0])

	def test_a_path_traversal_member_is_refused(self):
		with self.assertRaises(bridge.BundleError):
			bridge.install(bundle(extra={"../../evil.txt": b"x"}), self.studio)
		self.assertFalse((self.studio.parent / "evil.txt").exists())

	def test_unexpected_member_is_refused(self):
		with self.assertRaises(bridge.BundleError):
			bridge.install(bundle(extra={"run.sh": b"rm -rf /"}), self.studio)

	def test_crop_for_a_field_the_card_lacks_is_refused(self):
		with self.assertRaises(bridge.BundleError):
			bridge.install(bundle(extra={"crops/ghost/c1/p-1.png": png(5, 5)}), self.studio)

	def test_a_writer_name_is_refused(self):
		with self.assertRaises(bridge.BundleError):
			bridge.install(bundle(writers={"p-1": "Aditya Bhatt"}), self.studio)

	def test_bad_card_key_and_too_long_a_pack_id(self):
		with self.assertRaises(bridge.BundleError):
			bridge.install(bundle(card="bad key!"), self.studio)
		with self.assertRaises(bridge.BundleError):
			bridge.install(bundle(card="x" * 40), self.studio)

	def test_not_a_zip_and_missing_member(self):
		with self.assertRaises(bridge.BundleError):
			bridge.install(b"hello", self.studio)
		buf = io.BytesIO()
		with zipfile.ZipFile(buf, "w") as z:
			z.writestr("manifest.json", "{}")
		with self.assertRaises(bridge.BundleError):
			bridge.install(buf.getvalue(), self.studio)

	def test_a_bad_label_row_is_refused(self):
		with self.assertRaises(bridge.BundleError):
			bridge.install(bundle(labels="page,row,col,label\n../x,weight_kg,c1,5\n"), self.studio)

	def test_nothing_is_written_outside_the_card(self):
		bridge.install(bundle(), self.studio)
		top = {p.name for p in self.studio.iterdir()}
		self.assertEqual(top, {"cards", "templates"})


FAKE = """
import json, sys, time
from pathlib import Path
run = Path(sys.argv[1]); run.mkdir(parents=True, exist_ok=True)
json.dump({"stage": "cv", "detail": "1 of 5 folds done", "elapsed": 1}, open(run / "status.json", "w"))
time.sleep(float(sys.argv[2]))
pack = run / "fr_smoke_v1.cardpack"; pack.write_bytes(b"PACKBYTES")
json.dump({"pack": {"path": str(pack)}, "fields": []}, open(run / "results.json", "w"))
json.dump({"stage": "done", "detail": "pack written", "elapsed": 2}, open(run / "status.json", "w"))
"""


def fake_runner(delay):
	import subprocess

	def run(studio, card, run_dir, pretrained="auto", **opts):
		Path(run_dir).mkdir(parents=True, exist_ok=True)
		return subprocess.Popen([sys.executable, "-c", FAKE, str(run_dir), str(delay)])
	return run


class Service(unittest.TestCase):
	def start(self, delay=0.2):
		self.tmp = tempfile.TemporaryDirectory()
		self.httpd, self.state = server.serve("127.0.0.1", 0, self.tmp.name, self.tmp.name + "/data", TOKEN, fake_runner(delay))
		self.port = self.httpd.server_address[1]
		threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
		self.addCleanup(self.httpd.server_close)
		self.addCleanup(self.httpd.shutdown)
		self.addCleanup(self.tmp.cleanup)

	def call(self, method, path, body=None, token=TOKEN):
		req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=body, method=method, headers={"X-OCR-Token": token} if token else {})
		try:
			with urllib.request.urlopen(req, timeout=10) as r:
				return r.status, r.read()
		except urllib.error.HTTPError as e:
			return e.code, e.read()

	def test_health_needs_no_token(self):
		self.start()
		code, body = self.call("GET", "/health", token=None)
		self.assertEqual((code, json.loads(body)["ok"]), (200, True))

	def test_every_other_request_needs_the_token(self):
		self.start()
		self.assertEqual(self.call("POST", "/train", bundle(), token="wrong")[0], 401)
		self.assertEqual(self.call("GET", "/status/" + "0" * 32, token=None)[0], 401)

	def test_train_then_status_then_pack(self):
		self.start(delay=0.3)
		code, body = self.call("POST", "/train", bundle())
		self.assertEqual(code, 200)
		job = json.loads(body)["job"]
		self.assertEqual(self.call("GET", f"/pack/{job}")[0], 409)         # not finished yet
		for _ in range(100):
			code, body = self.call("GET", f"/status/{job}")
			st = json.loads(body)
			if st["state"] != "running":
				break
			time.sleep(0.1)
		self.assertEqual(st["state"], "done")
		self.assertEqual(self.call("GET", f"/pack/{job}"), (200, b"PACKBYTES"))

	def test_a_second_run_is_refused_while_one_is_going(self):
		self.start(delay=1.5)
		self.assertEqual(self.call("POST", "/train", bundle())[0], 200)
		code, body = self.call("POST", "/train", bundle(card="other"))
		self.assertEqual(code, 409)

	def test_a_bad_bundle_is_a_400_and_starts_nothing(self):
		self.start()
		code, body = self.call("POST", "/train", bundle(extra={"../x": b"y"}))
		self.assertEqual(code, 400)
		self.assertEqual(self.state.jobs, {})

	def test_unknown_job_is_404(self):
		self.start()
		self.assertEqual(self.call("GET", "/status/" + "a" * 32)[0], 404)
		self.assertEqual(self.call("GET", "/status/notahexid")[0], 404)


class Status(unittest.TestCase):
	def test_a_trainer_that_died_without_finishing_is_failed(self):
		with tempfile.TemporaryDirectory() as d:
			class Dead:
				def poll(self):
					return 1
			(Path(d) / "status.json").write_text(json.dumps({"stage": "cv", "detail": "2 of 5"}))
			self.assertEqual(bridge.read_status(d, Dead())["state"], "failed")

	def test_done_without_results_is_failed(self):
		with tempfile.TemporaryDirectory() as d:
			(Path(d) / "status.json").write_text(json.dumps({"stage": "done"}))
			self.assertEqual(bridge.read_status(d)["state"], "failed")


if __name__ == "__main__":
	unittest.main()


class StudioQuestions(unittest.TestCase):
	def start(self, asker):
		self.tmp = tempfile.TemporaryDirectory()
		self.httpd, self.state = server.serve("127.0.0.1", 0, self.tmp.name, self.tmp.name + "/data", TOKEN, fake_runner(0.1), asker)
		self.port = self.httpd.server_address[1]
		threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
		self.addCleanup(self.httpd.server_close)
		self.addCleanup(self.httpd.shutdown)
		self.addCleanup(self.tmp.cleanup)

	def get(self, path, token=TOKEN):
		req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers={"X-OCR-Token": token} if token else {})
		try:
			with urllib.request.urlopen(req, timeout=10) as r:
				return r.status, json.loads(r.read())
		except urllib.error.HTTPError as e:
			return e.code, json.loads(e.read())

	def test_jobs_and_pretrained_are_passed_through(self):
		self.start(lambda what, *a: {"jobs": [{"id": "capacity"}], "pretrained": [{"name": "v2"}]}[what])
		self.assertEqual(self.get("/jobs"), (200, [{"id": "capacity"}]))
		self.assertEqual(self.get("/pretrained"), (200, [{"name": "v2"}]))

	def test_datasize_asks_for_the_prefixed_studio_card(self):
		seen = []
		self.start(lambda what, *a: seen.append((what, a)) or {"ok": True})
		self.assertEqual(self.get("/datasize/smoke?target=90")[0], 200)
		self.assertEqual(seen, [("datasize", ("fr_smoke", "90"))])

	def test_a_studio_module_that_fails_is_a_501_not_a_crash(self):
		def boom(what, *a):
			raise ImportError("no torch here")
		self.start(boom)
		code, body = self.get("/jobs")
		self.assertEqual(code, 501)
		self.assertIn("no torch", body["error"])
		self.assertEqual(self.get("/health", token=None)[0], 200)             # the service is still up

	def test_these_need_the_token(self):
		self.start(lambda what, *a: {})
		for path in ("/jobs", "/pretrained", "/datasize/smoke"):
			self.assertEqual(self.get(path, token="wrong")[0], 401)

	def test_a_bad_card_key_is_a_400(self):
		self.start(lambda what, *a: {})
		self.assertEqual(self.get("/datasize/" + "x" * 40)[0], 400)

	def test_the_run_directory_is_inside_studios_runs_folder(self):
		self.start(lambda what, *a: {})
		req = urllib.request.Request(f"http://127.0.0.1:{self.port}/train", data=bundle(), method="POST", headers={"X-OCR-Token": TOKEN})
		with urllib.request.urlopen(req, timeout=10) as r:
			job = json.loads(r.read())["job"]
		self.assertTrue(str(self.state.jobs[job]["dir"]).startswith(str(Path(self.tmp.name) / "runs")))
