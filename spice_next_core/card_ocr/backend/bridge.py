"""Training backend, part 1: install a training bundle into Card Studio's folders and run Studio's trainer on it. Standard library only.

The backend runs wherever PyTorch lives (not inside the Frappe bench). It does not re-implement training: it hands the card to Card Studio's
trainer.py (page/writer-split 5-fold cross-validation, the ship gate, ONNX and TFLite export, pack build), then returns the pack it wrote.

Bundle (a zip) from Frappe:
    manifest.json     {"card": key, "fields": [{"key","kind","range","layout"}], "writers": {page: writer}}
    template.png      the blank card
    grid.json         the grid (any resolution: it is rescaled to the template's size)
    labels.csv        page,row,col,label        (row = field key, col = visit c1..cN)
    crops/<field>/<visit>/<page>.png
The card is installed in Studio under the name  <prefix><key lower-cased>  (default prefix fr_) so it can never overwrite one of Studio's own cards.
"""
import csv
import io
import json
import os
import re
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

PREFIX = os.environ.get("OCR_CARD_PREFIX", "fr_")
KEY = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
FIELD = re.compile(r"^[A-Za-z0-9_]{1,40}$")
VISIT = re.compile(r"^c[1-9][0-9]?$")
PAGE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
WRITER = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
PACK_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
CROP_NAME = re.compile(r"^crops/([A-Za-z0-9_]{1,40})/(c[1-9][0-9]?)/([A-Za-z0-9_-]{1,40})\.png$")
MAX_MEMBERS = 200_000
MAX_UNCOMPRESSED = 2 * 1024 ** 3
KINDS = ("number", "date", "bp", "mark", "text")
LAYOUTS = ("single", "stacked", "diagonal")


class BundleError(ValueError):
	pass


def studio_name(card):
	name = (PREFIX + card).lower()
	if not KEY.match(card) or not PACK_ID.match(name):
		raise BundleError(f"card key {card!r} cannot become a pack id ({PREFIX}<key>, lower-case letters, digits, _ or -, at most 32)")
	return name


def png_size(data):
	"""(width, height) from a PNG's header, without decoding it."""
	if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
		raise BundleError("template.png is not a PNG")
	return struct.unpack(">II", data[16:24])


def scale_grid(grid, w, h):
	"""The grid rescaled to a template of w x h pixels. Row lines scale with the height, column lines with the width."""
	gw, gh = grid["image_size"]
	sx, sy = w / gw, h / gh
	f = lambda v, k: round(v * k, 1)  # noqa: E731
	out = {"image_size": [w, h], "rows": grid["rows"], "y_ref_top": f(grid["y_ref_top"], sy), "y_ref_bot": f(grid["y_ref_bot"], sy),
		"col_lines_top": [f(v, sx) for v in grid["col_lines_top"]], "col_lines_bot": [f(v, sx) for v in grid["col_lines_bot"]],
		"row_lines_by_col": [[f(v, sy) for v in col] for col in grid["row_lines_by_col"]]}
	if grid.get("axis") == "columns":
		out["axis"], out["cols"] = "columns", grid["cols"]
	return out


def check_manifest(m):
	if not isinstance(m, dict) or not KEY.match(str(m.get("card", ""))):
		raise BundleError("manifest.card is missing or not a valid key")
	fields = m.get("fields")
	if not isinstance(fields, list) or not fields:
		raise BundleError("manifest.fields must list the card's fields")
	for f in fields:
		if not FIELD.match(str(f.get("key", ""))) or f.get("kind") not in KINDS or f.get("layout", "single") not in LAYOUTS:
			raise BundleError(f"bad field {f!r}")
		r = f.get("range")
		if r is not None and (f["kind"] != "number" or len(r) != 2 or not r[0] < r[1]):
			raise BundleError(f"{f['key']}: range needs kind number and [low, high]")
	for page, w in (m.get("writers") or {}).items():
		if not PAGE.match(page) or not WRITER.match(str(w)):
			raise BundleError("a writer is a code like W07, never a name")


def install(bundle: bytes, studio_dir):
	"""Unpack a bundle into Studio's folders. -> (studio card name, {labels, pages, crops}). Raises BundleError for anything unsafe or malformed:
	nothing outside the card's folders is ever written, member names are matched against exact patterns, sizes are capped."""
	studio = Path(studio_dir)
	try:
		z = zipfile.ZipFile(io.BytesIO(bundle))
	except zipfile.BadZipFile:
		raise BundleError("the bundle is not a zip file")
	infos = z.infolist()
	if len(infos) > MAX_MEMBERS or sum(i.file_size for i in infos) > MAX_UNCOMPRESSED:
		raise BundleError("the bundle is too large")
	names = {i.filename for i in infos}
	for need in ("manifest.json", "template.png", "grid.json", "labels.csv"):
		if need not in names:
			raise BundleError(f"the bundle is missing {need}")
	manifest = json.loads(z.read("manifest.json"))
	check_manifest(manifest)
	name = studio_name(manifest["card"])
	tpl = z.read("template.png")
	w, h = png_size(tpl)
	grid = scale_grid(json.loads(z.read("grid.json")), w, h)
	card_dir, tpl_dir = studio / "cards" / name, studio / "templates" / name / "v1"
	crops_root = card_dir / "crops"
	crops = 0
	for i in infos:
		m = CROP_NAME.match(i.filename)
		if not m:
			if i.filename not in ("manifest.json", "template.png", "grid.json", "labels.csv") and not i.is_dir():
				raise BundleError(f"unexpected file in the bundle: {i.filename!r}")
			continue
		if m[1] not in {f["key"] for f in manifest["fields"]}:
			raise BundleError(f"crop for a field the card does not have: {m[1]}")
		dest = crops_root / m[1] / m[2] / f"{m[3]}.png"
		dest.parent.mkdir(parents=True, exist_ok=True)
		dest.write_bytes(z.read(i))
		crops += 1
	rows = list(csv.DictReader(io.StringIO(z.read("labels.csv").decode("utf-8"))))
	keep = []
	for r in rows:
		if not (PAGE.match(r.get("page", "")) and FIELD.match(r.get("row", "")) and VISIT.match(r.get("col", "")) and str(r.get("label", "")).strip()):
			raise BundleError(f"bad label row {r!r}")
		keep.append({"page": r["page"], "row": r["row"], "col": r["col"], "label": r["label"].strip()})
	tpl_dir.mkdir(parents=True, exist_ok=True)
	card_dir.mkdir(parents=True, exist_ok=True)
	(tpl_dir / "template.png").write_bytes(tpl)
	(tpl_dir / "grid.json").write_text(json.dumps(grid, indent=1))
	(card_dir / "fields.json").write_text(json.dumps({"fields": {f["key"]: {k: v for k, v in
		{"kind": f["kind"], "range": f.get("range"), "layout": f.get("layout", "single")}.items() if v is not None} for f in manifest["fields"]}}, indent=1))
	with open(card_dir / "labels.csv", "w", newline="") as fh:
		w_ = csv.DictWriter(fh, ["page", "row", "col", "label"])
		w_.writeheader()
		w_.writerows(keep)
	if manifest.get("writers"):
		with open(card_dir / "writers.csv", "w", newline="") as fh:
			w_ = csv.writer(fh)
			w_.writerow(["page", "writer"])
			for page, writer in sorted(manifest["writers"].items()):
				w_.writerow([page, writer])
	return name, {"labels": len(keep), "pages": len({r["page"] for r in keep}), "crops": crops}


def start_trainer(studio_dir, card, run_dir, pretrained="auto", target=85.0, min_n=20, max_epochs=300, config="light_lr3e-4", python=None):
	"""Launch Studio's trainer.py as a subprocess. -> Popen. Progress is written to run_dir/status.json, results to run_dir/results.json."""
	studio = Path(studio_dir)
	cmd = [python or sys.executable, str(studio / "trainer.py"), str(run_dir), "--card", card, "--target", str(target), "--min-n", str(min_n), "--max-epochs", str(max_epochs), "--config", config, "--pretrained", pretrained]
	Path(run_dir).mkdir(parents=True, exist_ok=True)
	log = open(Path(run_dir) / "log.txt", "w")
	return subprocess.Popen(cmd, cwd=str(studio), stdout=log, stderr=subprocess.STDOUT)


def read_status(run_dir, proc=None):
	"""-> {state: running | done | failed, stage, detail, results?}. A trainer that exited without writing done is failed, whatever it last said."""
	run = Path(run_dir)
	try:
		st = json.loads((run / "status.json").read_text())
	except (OSError, ValueError):
		st = {"stage": "starting", "detail": ""}
	alive = proc is not None and proc.poll() is None
	if st.get("stage") == "done":
		state = "done"
	elif st.get("stage") == "error" or (proc is not None and not alive):
		state = "failed"
	else:
		state = "running"
	out = {"state": state, "stage": st.get("stage"), "detail": str(st.get("detail", ""))[-1500:], "elapsed": st.get("elapsed")}
	if state == "done":
		try:
			out["results"] = json.loads((run / "results.json").read_text())
		except (OSError, ValueError):
			out["state"] = "failed"
			out["detail"] = "the trainer finished without writing results"
	return out


def pack_path(results):
	"""Path of the pack the trainer wrote, from its results.json."""
	return Path(results["pack"]["path"])
