"""Training backend, part 2: a small HTTP service in front of bridge.py. Standard library only; run it with the Python that has PyTorch.

    OCR_BACKEND_TOKEN=<secret> STUDIO_DIR=/path/to/banglahandwriting/studio python -m spice_next_core.card_ocr.backend.server --port 8790
    (or: python server.py --port 8790, from this folder)

    GET  /health                       {"ok": true, "busy": bool}
    POST /train?pretrained=auto&target=85&min_n=20&max_epochs=300&config=light_lr3e-4   body: the bundle zip           -> {"job": id}        409 while another run is going
    GET  /status/<job>                                               -> bridge.read_status
    GET  /pack/<job>                   the finished .cardpack file
    GET  /jobs                         Studio's experiment status (Model quality)
    GET  /pretrained                   the starting weights a run can begin from
    GET  /datasize/<card>?target=85    is there enough labelled data (Studio's datasize.summary)

Every request except /health must carry the header X-OCR-Token. One training run at a time (the trainer already uses every core). Binds to 127.0.0.1
unless --host says otherwise.
"""
import argparse
import hmac
import json
import os
import re
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

CONFIGS = ("light_lr3e-4", "light_lr1e-4", "nbaug_lr1e-4")      # the presets of Studio's trainer.py (--config)

try:
	from spice_next_core.card_ocr.backend import bridge
except ImportError:                      # run as a plain script next to bridge.py
	sys.path.insert(0, str(Path(__file__).resolve().parent))
	import bridge

MAX_BODY = 1024 ** 3
JOB = re.compile(r"^[0-9a-f]{32}$")
PRETRAINED = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def studio_call(studio_dir, what, *args):
	"""Ask one of Card Studio's own modules a read-only question: jobs (experiments), pretrained (starting weights), datasize (is there enough labelled data).
	Imported lazily from the Studio folder, so the service starts even when a module's own dependencies are missing."""
	studio = Path(studio_dir)
	for sub in ("", "../work_phaseA", "../cardpack"):
		p = str((studio / sub).resolve())
		if p not in sys.path:
			sys.path.insert(0, p)
	if what == "jobs":
		import labruns
		return labruns.jobs()
	if what == "pretrained":
		import pretrained
		return pretrained.list_all()
	if what == "datasize":
		import datasize
		return datasize.summary(args[0], args[1] if len(args) > 1 else None)
	raise KeyError(what)


class State:
	def __init__(self, studio_dir, data_dir, token, runner=None, asker=None):
		self.studio, self.data, self.token = Path(studio_dir), Path(data_dir), token
		self.runner = runner or bridge.start_trainer
		self.ask = asker or (lambda what, *a: studio_call(self.studio, what, *a))
		self.jobs = {}                   # id -> {"card", "proc", "dir"}
		self.lock = threading.Lock()

	def busy(self):
		return any(j["proc"] is not None and j["proc"].poll() is None for j in self.jobs.values())


def make_handler(state):
	class H(BaseHTTPRequestHandler):
		def log_message(self, *a):
			pass

		def _send(self, code, body, ctype="application/json"):
			data = body if isinstance(body, bytes) else json.dumps(body).encode()
			self.send_response(code)
			self.send_header("Content-Type", ctype)
			self.send_header("Content-Length", str(len(data)))
			self.end_headers()
			self.wfile.write(data)

		def _authed(self):
			given = self.headers.get("X-OCR-Token", "")
			return bool(state.token) and hmac.compare_digest(given.encode(), state.token.encode())

		def do_GET(self):
			u = urlparse(self.path)
			if u.path == "/health":
				return self._send(200, {"ok": True, "busy": state.busy()})
			if not self._authed():
				return self._send(401, {"error": "bad or missing X-OCR-Token"})
			if u.path in ("/jobs", "/pretrained"):
				try:
					return self._send(200, state.ask(u.path[1:]))
				except Exception as e:             # a Studio module that cannot be imported or run: say so, do not crash the service
					return self._send(501, {"error": f"{type(e).__name__}: {e}"[:300]})
			m = re.fullmatch(r"/datasize/([A-Za-z0-9_-]{1,40})", u.path)
			if m:
				try:
					card = bridge.studio_name(m[1]) if not m[1].startswith(bridge.PREFIX) else m[1]
					return self._send(200, state.ask("datasize", card, (parse_qs(u.query).get("target") or [None])[0]))
				except bridge.BundleError as e:
					return self._send(400, {"error": str(e)})
				except Exception as e:
					return self._send(501, {"error": f"{type(e).__name__}: {e}"[:300]})
			m = re.fullmatch(r"/(status|pack)/([0-9a-f]{32})", u.path)
			if not m or m[2] not in state.jobs:
				return self._send(404, {"error": "not found"})
			job = state.jobs[m[2]]
			st = bridge.read_status(job["dir"], job["proc"])
			if m[1] == "status":
				return self._send(200, {k: v for k, v in st.items() if k != "results"} | ({"results": st["results"]} if "results" in st else {}))
			if st["state"] != "done":
				return self._send(409, {"error": "the run is not finished"})
			p = bridge.pack_path(st["results"])
			if not p.is_file():
				return self._send(500, {"error": "the pack file is missing"})
			return self._send(200, p.read_bytes(), "application/octet-stream")

		def do_POST(self):
			u = urlparse(self.path)
			if u.path != "/train":
				return self._send(404, {"error": "not found"})
			if not self._authed():
				return self._send(401, {"error": "bad or missing X-OCR-Token"})
			try:
				n = int(self.headers.get("Content-Length", "0"))
			except ValueError:
				return self._send(400, {"error": "bad Content-Length"})
			if not 0 < n <= MAX_BODY:
				return self._send(413, {"error": "the bundle is empty or too large"})
			pre = (parse_qs(u.query).get("pretrained") or ["auto"])[0]
			if pre != "auto" and not PRETRAINED.match(pre):
				return self._send(400, {"error": "bad pretrained name"})
			q = parse_qs(u.query)
			config = (q.get("config") or ["light_lr3e-4"])[0]
			if config not in CONFIGS:
				return self._send(400, {"error": "config is one of " + ", ".join(CONFIGS)})
			try:
				opts = {"config": config, "target": float((q.get("target") or ["85"])[0]), "min_n": int((q.get("min_n") or ["20"])[0]), "max_epochs": int((q.get("max_epochs") or ["300"])[0])}
			except ValueError:
				return self._send(400, {"error": "target, min_n and max_epochs must be numbers"})
			if not (50 <= opts["target"] <= 99.9 and 5 <= opts["min_n"] <= 500 and 5 <= opts["max_epochs"] <= 1000):
				return self._send(400, {"error": "target is 50 to 99.9, min_n 5 to 500, max_epochs 5 to 1000"})
			body = self.rfile.read(n)
			with state.lock:
				if state.busy():
					return self._send(409, {"error": "another training run is in progress"})
				try:
					card, stats = bridge.install(body, state.studio)
				except bridge.BundleError as e:
					return self._send(400, {"error": str(e)})
				job = uuid.uuid4().hex
				run_dir = state.studio / "runs" / f"run-{time.strftime('%Y%m%d-%H%M%S')}-{job[:6]}"
				proc = state.runner(state.studio, card, run_dir, pretrained=pre, **opts)
				state.jobs[job] = {"card": card, "proc": proc, "dir": run_dir}
			return self._send(200, {"job": job, "card": card, **stats})

	return H


def serve(host, port, studio_dir, data_dir, token, runner=None, asker=None):
	state = State(studio_dir, data_dir, token, runner, asker)
	return ThreadingHTTPServer((host, port), make_handler(state)), state


if __name__ == "__main__":
	ap = argparse.ArgumentParser()
	ap.add_argument("--host", default="127.0.0.1")
	ap.add_argument("--port", type=int, default=8790)
	ap.add_argument("--studio", default=os.environ.get("STUDIO_DIR", ""))
	ap.add_argument("--data", default=os.environ.get("OCR_BACKEND_DATA", "./ocr_backend_data"))
	a = ap.parse_args()
	token = os.environ.get("OCR_BACKEND_TOKEN", "")
	if not token or not a.studio or not (Path(a.studio) / "trainer.py").is_file():
		sys.exit("set OCR_BACKEND_TOKEN and STUDIO_DIR (the Card Studio folder that holds trainer.py)")
	httpd, _ = serve(a.host, a.port, a.studio, a.data, token)
	print(f"card ocr training backend on http://{a.host}:{a.port}  (studio: {a.studio})")
	httpd.serve_forever()
