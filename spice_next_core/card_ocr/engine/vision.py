"""Card vision: match a photo to a card's template, straighten it onto the grid, cut every cell, decide which cells hold ink.

A port of Card Studio's cleanup.py / scans.py (which port the phone's anc_reader.dart), rewritten as pure functions over explicit inputs: no folders,
no database, no frappe. The same steps as the phone, so a crop a reader is trained on is cut the way a crop it will read is cut:
SIFT + RANSAC homography with an outline check, warp to the grid's size, cut cells with the margin, remove ruled lines, apply the ink gate.
"""
import math
from dataclasses import dataclass, field

import cv2
import numpy as np

MIN_INLIERS = 40         # floor below which a photo is not this card (the packs' match.min_inliers)
CHECK_BELOW = 100        # a match under this many inliers is usable, but a person should look at it
MARGIN = 2.0             # identifying among several cards: the best must beat the runner-up by this factor
CELL_MARGIN = 12
INK_GATE = {"dark_below": 110, "min_dark_pixels": 40, "min_dark_fraction": 0.006}
PRINT_BELOW = 170        # pixels of a blank card darker than this are printed, not written
DETECT_LONG_SIDE = 1600


@dataclass
class Target:
	"""A card's template and grid, as the matching and cutting functions need them."""
	card: str
	tpl: np.ndarray                       # template, gray
	grid: dict                            # grid.json at reading resolution (image_size, rows, col_lines_top/bot, row_lines_by_col, y_ref_top/bot, axis, cols)
	margin: int = CELL_MARGIN
	ink: dict = field(default_factory=lambda: dict(INK_GATE))
	feats: tuple = None

	def __post_init__(self):
		if self.tpl is None or self.tpl.ndim != 2:
			raise ValueError(f"{self.card}: template must be a gray image")
		self.scale = self.grid["image_size"][0] / self.tpl.shape[1]      # template pixels -> grid pixels
		if self.feats is None:
			self.feats = sift(self.tpl)

	@property
	def n_cols(self):
		return len(self.grid["col_lines_top"]) - 1

	@property
	def by_column(self):
		return self.grid.get("axis") == "columns"


def sift(gray, long_side=DETECT_LONG_SIDE):
	"""-> (points in original pixels [n,2], descriptors, (h, w)). Found on an image shrunk to `long_side`."""
	s = min(1.0, long_side / max(gray.shape))
	g = cv2.resize(gray, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else gray
	kp, des = cv2.SIFT_create(nfeatures=4000).detectAndCompute(g, None)
	pts = np.float32([p.pt for p in kp]) / s if kp else np.zeros((0, 2), np.float32)
	return pts, des, gray.shape[:2]


def homography(q, t):
	"""q, t: sift() results of the photo and the template. -> (H photo->template or None, inliers)."""
	(pq, dq, _), (pt, dt, _) = q, t
	if dq is None or dt is None or len(pq) < 10:
		return None, 0
	good = [m[0] for m in cv2.BFMatcher(cv2.NORM_L2).knnMatch(dq, dt, k=2) if len(m) == 2 and m[0].distance < 0.75 * m[1].distance]
	if len(good) < 10:
		return None, 0
	H, mask = cv2.findHomography(
		pq[[g.queryIdx for g in good]].reshape(-1, 1, 2), pt[[g.trainIdx for g in good]].reshape(-1, 1, 2), cv2.RANSAC, 4.0
	)
	return H, int(mask.sum()) if H is not None else 0


def match_score(bgr, tpl):
	"""0..1 = RANSAC inliers / 150, Card Studio's template match score (the phone needs >=100 inliers to align, so >=0.67 is a usable match)."""
	gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
	q, t = sift(gray), sift(tpl if tpl.ndim == 2 else cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY))
	if q[1] is None or t[1] is None or len(q[0]) < 10 or len(t[0]) < 10:
		return 0.0
	return min(1.0, homography(q, t)[1] / 150)


def align(bgr, target):
	"""-> (H photo->template, inliers, outline problem or None). H maps original photo pixels to template pixels."""
	gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
	H, inl = homography(sift(gray), target.feats)
	if H is None:
		return None, 0, "no homography"
	qh, qw = gray.shape
	th, tw = target.tpl.shape
	quad = cv2.perspectiveTransform(np.float32([[0, 0], [qw, 0], [qw, qh], [0, qh]]).reshape(-1, 1, 2), H).reshape(4, 2)
	e = [quad[(i + 1) % 4] - quad[i] for i in range(4)]
	cr = [float(e[i][0] * e[(i + 1) % 4][1] - e[i][1] * e[(i + 1) % 4][0]) for i in range(4)]       # z of the 2-D cross product
	area = 0.5 * abs(np.dot(quad[:, 0], np.roll(quad[:, 1], -1)) - np.dot(quad[:, 1], np.roll(quad[:, 0], -1))) / (tw * th)
	if not (all(c > 0 for c in cr) or all(c < 0 for c in cr)):
		return H, inl, "not convex"
	if cr[0] < 0:
		return H, inl, "mirrored"
	if not 0.2 <= area <= 10.0:
		return H, inl, f"implausible size ({area:.2f}x the template)"
	return H, inl, None


def identify(bgr, targets):
	"""Score a photo against each target. -> (best target or None, H, tried). `tried` = [{card, inliers, why}] best first; the winner needs
	MIN_INLIERS, a sane outline, and (when there is a runner-up) MARGIN times the runner-up's inliers."""
	res = []
	for t in targets:
		H, inl, bad = align(bgr, t)
		res.append((t, H, inl, bad or (f"only {inl} matching features, needs {MIN_INLIERS}" if inl < MIN_INLIERS else None)))
	res.sort(key=lambda r: -r[2])
	tried = [{"card": t.card, "inliers": inl, "why": why} for t, _, inl, why in res]
	if not res or res[0][3] is not None:
		return None, None, tried
	if len(res) > 1 and res[0][2] < MARGIN * res[1][2]:
		tried[0]["why"] = f"too close to {res[1][0].card} ({res[0][2]} against {res[1][2]} matching features)"
		return None, None, tried
	return res[0][0], res[0][1], tried


def warp(bgr, H, target):
	"""Photo -> upright gray card at the grid's resolution."""
	W, Hh = target.grid["image_size"]
	M = np.diag([target.scale, target.scale, 1.0]) @ H
	gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
	return cv2.warpPerspective(gray, M, (W, Hh), borderValue=255)


def warp_with_mask(bgr, H, target):
	"""warp() plus a mask: nonzero where the photo really covered the card (the rest is white border)."""
	W, Hh = target.grid["image_size"]
	M = np.diag([target.scale, target.scale, 1.0]) @ H
	gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
	warped = cv2.warpPerspective(gray, M, (W, Hh), borderValue=255)
	covered = cv2.warpPerspective(np.ones_like(gray), M, (W, Hh), flags=cv2.INTER_NEAREST, borderValue=0)
	return warped, covered


def _xat(top, bot, y, g):
	return top + (bot - top) * (y - g["y_ref_top"]) / (g["y_ref_bot"] - g["y_ref_top"])


def _rnd(v):
	return int(math.floor(v + 0.5))


def visit_name(target, ri, c):
	"""A visit is a column, or a row when the fields run down the columns. c1 = first."""
	return f"c{(ri if target.by_column else c) + 1}"


def cut_cells(card, target):
	"""Yield (row_index, col_index, field, visit, crop) for every cell of the aligned gray card, in the order the grid lists them.
	The field is the row's name, or the column's when the grid's fields run down the columns."""
	g = target.grid
	m = target.margin
	H, W = card.shape
	for c in range(target.n_cols):
		rl = g["row_lines_by_col"][c]
		for ri, row in enumerate(g["rows"]):
			fld = g["cols"][c] if target.by_column else row
			ymid = (rl[ri] + rl[ri + 1]) / 2.0
			xa = _xat(g["col_lines_top"][c], g["col_lines_bot"][c], ymid, g) - m
			xb = _xat(g["col_lines_top"][c + 1], g["col_lines_bot"][c + 1], ymid, g) + m
			my = min(m, max(2.0, (rl[ri + 1] - rl[ri]) / 6))
			x0 = min(max(_rnd(xa), 0), W - 1)
			x1 = min(max(_rnd(xb), x0 + 1), W)
			y0 = min(max(_rnd(rl[ri] - my), 0), H - 1)
			y1 = min(max(_rnd(rl[ri + 1] + my), y0 + 1), H)
			yield ri, c, fld, visit_name(target, ri, c), card[y0:y1, x0:x1].copy()


def remove_lines(gray):
	"""Whiten the long printed rules (cell borders, neighbouring rows' lines) so a blank cell is really blank."""
	_, ink = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
	kh, kv = max(9, _rnd(gray.shape[1] * 0.6)), max(9, _rnd(gray.shape[0] * 0.6))
	h = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (kh, 1)))
	v = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, kv)))
	lines = cv2.dilate(cv2.bitwise_or(h, v), cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))
	return cv2.bitwise_or(gray, lines)


def prepare(gray, ink=None):
	"""Ink gate, then fit to 48 high keeping aspect and pad white (192 wide). None = blank cell (never reaches a reader)."""
	ink = ink or INK_GATE
	h, w = gray.shape
	ix0 = _rnd(w * 0.12)
	ix1 = w - ix0
	iy0 = _rnd(h * 0.2)
	iy1 = h - iy0
	dark = int((gray[iy0:iy1, ix0:ix1] < ink["dark_below"]).sum())
	inner = max(1, (ix1 - ix0) * (iy1 - iy0))
	if dark < ink["min_dark_pixels"] or dark / inner < ink["min_dark_fraction"]:
		return None
	nw = min(192, max(1, _rnd(w * 48 / h)))
	out = np.full((48, 192), 255, np.uint8)
	out[:, :nw] = cv2.resize(gray, (nw, 48), interpolation=cv2.INTER_AREA)
	return out


def has_ink(target, crop, blank_crop=None):
	"""Does this cell hold writing? What a blank card already shows there (a printed diagonal, shading) is ignored when a blank estimate is given."""
	if blank_crop is not None and blank_crop.shape == crop.shape:
		printed = cv2.dilate((blank_crop < PRINT_BELOW).astype(np.uint8), np.ones((7, 7), np.uint8))
		crop = np.where(printed > 0, 255, crop).astype(np.uint8)
	return prepare(remove_lines(crop), target.ink) is not None


def _decode_with_pillow(data: bytes):
	"""HEIC / HEIF (what phones and macOS screenshots can produce) and anything else Pillow reads. HEIC needs the optional pillow-heif package.
	None when it cannot be read."""
	try:
		import io

		from PIL import Image, ImageOps

		try:
			import pillow_heif

			pillow_heif.register_heif_opener()
		except ImportError:
			pass
		im = Image.open(io.BytesIO(data))
		im.load()
		im = ImageOps.exif_transpose(im).convert("RGB")           # phones store rotation in EXIF
		return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
	except Exception:
		return None


def decode_image(data: bytes):
	"""Image bytes -> BGR image, shrunk to at most 3000 px on the long side. JPEG / PNG / WebP / TIFF through OpenCV; HEIC through Pillow with
	pillow-heif when it is installed (file extensions are not trusted: a screenshot named .png can hold HEIC). None when nothing can read it."""
	im = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
	if im is None:
		im = _decode_with_pillow(data)
	if im is None:
		return None
	s = 3000 / max(im.shape[:2])
	return cv2.resize(im, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else im


MAX_PDF_PAGES, PDF_DPI = 200, 200


def pages_from(data: bytes):
	"""One BGR image per page: an image file is one page, a PDF is every page (rendered at PDF_DPI, at most MAX_PDF_PAGES). Raises ValueError for a
	PDF with too many pages or a file nothing can read."""
	if data[:4] == b"%PDF":
		import pypdfium2 as pdfium

		doc = pdfium.PdfDocument(data)
		if len(doc) > MAX_PDF_PAGES:
			raise ValueError(f"the PDF has {len(doc)} pages (limit {MAX_PDF_PAGES}): split it first")
		for i in range(len(doc)):
			rgb = np.array(doc[i].render(scale=PDF_DPI / 72).to_pil().convert("RGB"))
			im = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
			s = 3000 / max(im.shape[:2])
			yield cv2.resize(im, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else im
		return
	im = decode_image(data)
	if im is None:
		raise ValueError("not a readable image: use JPEG, PNG, WebP, TIFF, HEIC or PDF")
	yield im


def process(bgr, targets):
	"""One call for the whole path: identify the card, warp, cut. -> dict
	{card, inliers, status ('ok' | 'check' | 'rejected'), reason, tried, cells: [{field, visit, row, col, ink, crop (gray ndarray)}]}"""
	t, H, tried = identify(bgr, targets)
	if t is None:
		return {"card": None, "inliers": tried[0]["inliers"] if tried else 0, "status": "rejected", "tried": tried,
			"reason": (tried[0]["why"] if tried else "no card to match against"), "cells": []}
	inl = tried[0]["inliers"]
	aligned = warp(bgr, H, t)
	cells = [{"field": f, "visit": v, "row": ri, "col": c, "crop": crop, "ink": has_ink(t, crop)} for ri, c, f, v, crop in cut_cells(aligned, t)]
	return {"card": t.card, "inliers": inl, "status": "ok" if inl >= CHECK_BELOW else "check", "reason": "", "tried": tried, "cells": cells,
		"aligned": aligned}


ROWNAME = __import__("re").compile(r"^[A-Za-z0-9_]{1,40}$")


def check_grid(grid):
	"""The geometry rules a card's grid must satisfy (the cardpack format's grid.json rules, as Card Studio's gridconv.check_grid). -> [problems]."""
	errs = []
	try:
		inc = lambda a: all(b > c for c, b in zip(a, a[1:]))                    # noqa: E731
		nrows, ncols = len(grid["rows"]), len(grid["col_lines_top"]) - 1
		if nrows < 1 or ncols < 1:
			return ["the grid needs at least one row and one column"]
		if len(set(grid["rows"])) != nrows or not all(isinstance(r, str) and ROWNAME.match(r) for r in grid["rows"]):
			errs.append("row names must be unique (letters, digits, _)")
		axis = grid.get("axis", "rows")
		if axis not in ("rows", "columns"):
			errs.append("axis must be rows or columns")
		if axis == "columns":
			cn = grid.get("cols") or []
			if len(cn) != ncols or len(set(cn)) != ncols or not all(isinstance(c, str) and ROWNAME.match(c) for c in cn):
				errs.append(f"cols must be {ncols} unique field names")
		elif "cols" in grid:
			errs.append("cols is only for axis columns")
		if len(grid["col_lines_bot"]) != ncols + 1:
			errs.append("col_lines_top and col_lines_bot differ in length")
		if not inc(grid["col_lines_top"]) or not inc(grid["col_lines_bot"]):
			errs.append("column lines must increase left to right")
		if len(grid["row_lines_by_col"]) != ncols:
			errs.append("row_lines_by_col has the wrong number of columns")
		for c, rl in enumerate(grid["row_lines_by_col"]):
			if len(rl) != nrows + 1 or not inc(rl):
				errs.append(f"column {c + 1} needs {nrows + 1} increasing row lines")
		if grid["y_ref_bot"] <= grid["y_ref_top"]:
			errs.append("y_ref_bot must be below y_ref_top")
		W, H = grid["image_size"]
		if any(v < 0 or v > H for rl in grid["row_lines_by_col"] for v in rl):
			errs.append("row lines fall outside the image")
		if min(grid["col_lines_top"] + grid["col_lines_bot"]) < 0 or max(grid["col_lines_top"] + grid["col_lines_bot"]) > W:
			errs.append("column lines fall outside the image")
	except (KeyError, TypeError, ValueError) as e:
		errs.append(f"grid is missing or malformed: {e!r}")
	return errs
