"""Read prepared cells with a card pack's ONNX reader. Used for AI suggestions: a read is shown to a person, never stored as a label.

A pack (.cardpack) is a zip: manifest.json, template.png, grid.json, fields.json, reader.onnx (+ optional reader.tflite, fallback.json).
Greedy decoding takes the best allowed class at every step; a field set to `decode: grammar` is scored against every value it can hold
(engine/grammar.py), as the phone does.
"""
import io
import json
import zipfile
from dataclasses import dataclass

import numpy as np

from spice_next_core.card_ocr.engine import grammar, twoline, vision

MAX_PACK_BYTES = 120 * 1024 * 1024


@dataclass
class Pack:
	manifest: dict
	fields: dict
	grid: dict
	template_png: bytes
	onnx: bytes

	@property
	def id(self):
		return self.manifest["id"]

	@property
	def version(self):
		return self.manifest["version"]


def read_pack(data: bytes):
	"""Open a .cardpack from bytes. Raises ValueError saying what is wrong."""
	if len(data) > MAX_PACK_BYTES:
		raise ValueError("pack is too large")
	try:
		z = zipfile.ZipFile(io.BytesIO(data))
		names = set(z.namelist())
		need = {"manifest.json", "template.png", "grid.json", "fields.json", "reader.onnx"}
		if need - names:
			raise ValueError(f"pack is missing {', '.join(sorted(need - names))}")
		try:
			parts = [json.loads(z.read(n)) for n in ("manifest.json", "fields.json", "grid.json")]
		except ValueError:
			raise ValueError("pack has a manifest, fields or grid that is not valid JSON")
		return Pack(*parts, z.read("template.png"), z.read("reader.onnx"))
	except zipfile.BadZipFile:
		raise ValueError("not a card pack (not a zip file)")


UNREAL_DATE_CONFIDENCE = 0.1      # confidence given to a two-line date whose lines do not name a real day, so a person looks at it


class Reader:
	def __init__(self, pack: Pack):
		import onnxruntime as ort

		self.pack = pack
		self.session = ort.InferenceSession(pack.onnx, providers=["CPUExecutionProvider"])
		r = pack.manifest["reader"]
		self.in_name, self.out_name = r["input"]["name"], r["output"]["name"]
		self.classes = pack.fields["classes"]
		self.blank = pack.fields["blank_idx"]
		self.spec = {f["key"]: f for f in pack.fields["fields"]}

	def logits(self, px):
		"""px: prepared 48x192 uint8 cell -> [T, classes] raw scores."""
		x = ((px.astype(np.float32) / 255.0 - 0.5) / 0.5).reshape(1, 1, 48, 192)
		return self.session.run([self.out_name], {self.in_name: x})[0].reshape(-1, len(self.classes))

	def _greedy(self, lg, allowed):
		idx = sorted(allowed) if allowed else list(range(len(self.classes)))
		z = lg[:, idx]
		z = z - z.max(1, keepdims=True)
		p = np.exp(z) / np.exp(z).sum(1, keepdims=True)
		best = p.argmax(1)
		out, conf, prev = [], [], -1
		for t, b in enumerate(best):
			if idx[b] != self.blank and b != prev:
				out.append(self.classes[idx[b]])
				conf.append(float(p[t, b]))
			prev = b
		return "".join(out), (min(conf) if conf else 0.0)

	def _grammar(self, lg, spec, kind=None):
		idx = sorted(spec["allowed_idx"])
		chars = [self.classes[i] for i in idx]
		years = (spec.get("date") or {}).get("years")
		text, margin = grammar.decode(lg[:, idx], chars, idx.index(self.blank), kind or spec["kind"], spec.get("range"), years)
		return text, (min(1.0, float(np.exp(margin))) if np.isfinite(margin) else 0.0)

	def _piece_masks(self, layout):
		"""Allowed classes for the two pieces: digits, plus the day-month separators for the top of a date."""
		dig = {self.blank} | {self.classes.index(c) for c in "0123456789"}
		top = dig | {self.classes.index(c) for c in "./-"} if layout == "stacked" else dig
		return sorted(top), sorted(dig)

	def read(self, crop, field):
		"""A cell crop (gray, as cut) -> (text, confidence), or ("", 0.0) for a blank cell or a field with no reader (kind text)."""
		spec = self.spec.get(field)
		if spec is None or spec.get("kind") == "text":
			return "", 0.0
		layout = spec.get("layout", "single")
		if layout in twoline.KIND_FOR:
			try:
				a, b = twoline.parts(crop, layout)
			except ValueError:
				return "", 0.0
			pa, pb = vision.prepare(a), vision.prepare(b)
			if pa is None or pb is None:
				return "", 0.0
			top, bottom = self._piece_masks(layout)
			lga = self.logits(pa)
			ra = None
			if layout == "stacked" and spec.get("kind") == "date" and spec.get("decode") == "grammar":
				ra = self._grammar(lga, {**spec, "allowed_idx": top}, "daymonth")      # the top line is read against the days each month has
			ra = ra if ra and ra[0] else self._greedy(lga, top)
			rb = self._greedy(self.logits(pb), bottom)
			text, conf = twoline.join(layout, ra[0], rb[0]), min(ra[1], rb[1])
			if text and layout == "stacked" and spec.get("kind") == "date" and not grammar.date_ok(ra[0], rb[0]):
				conf = min(conf, UNREAL_DATE_CONFIDENCE)      # the two lines do not name a real day (a leap day in a year without one, a year line that is not a year)
			return text, conf
		px = vision.prepare(vision.remove_lines(crop))
		if px is None:
			return "", 0.0
		lg = self.logits(px)
		if spec.get("decode") == "grammar":
			text, conf = self._grammar(lg, spec)
			if text:
				return text, conf
		return self._greedy(lg, spec.get("allowed_idx"))
