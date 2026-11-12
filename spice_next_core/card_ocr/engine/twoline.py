"""Cells written on two lines, split into two single-line pieces a reader can read. Pure numpy/OpenCV; a port of Card Studio's subcells.py.

  stacked   a date written as day.month over a fraction bar over the year (the EPI card):   top "22.2"   bottom "26"
  diagonal  a blood pressure written either side of a printed diagonal (the NCD card):      top-left "120"   bottom-right "80"

The label stays one string for the whole cell ("22/2/26", "120/80"). For training each labelled cell becomes two pieces labelled with the parts of
that string; for reading the two pieces are read separately and joined. Pieces go through the same line removal as a whole cell.
"""
import re

import cv2
import numpy as np

from spice_next_core.card_ocr.engine import vision

LAYOUTS = ("single", "stacked", "diagonal")
KIND_FOR = {"stacked": "date", "diagonal": "bp"}
STACKED_LABEL = re.compile(r"(\d{1,2}[./]\d{1,2})[./](\d{2}(?:\d{2})?)")
DIAGONAL_LABEL = re.compile(r"(\d{2,3})/(\d{2,3})")
SOFT = 0.10             # how far across the diagonal each piece keeps pixels (fraction of the cell), so strokes that cross it are not cut
PRINT_BELOW = 110
BAR_SLOPE = 0.55        # a fraction bar may rise or fall by this much of its length
MIN_SIDE = 4


def split_label(layout, label):
	"""The two labels a whole-cell label breaks into, or None when it does not have the shape of this layout."""
	if layout not in KIND_FOR:
		return None
	m = (STACKED_LABEL if layout == "stacked" else DIAGONAL_LABEL).fullmatch(label.strip())
	return (m[1], m[2]) if m else None


def join(layout, a, b):
	"""The whole-cell string from the two read pieces; empty unless both pieces read something."""
	if not a or not b:
		return ""
	return (a.replace(".", "/") + "/" + b) if layout == "stacked" else f"{a}/{b}"


def canonical(layout, label):
	"""A label in the form join() produces, so a read can be compared with a label however the date was punctuated."""
	return label.strip().replace(".", "/") if layout == "stacked" else label.strip()


def _find_bar(g):
	"""(y at the left edge, y at the right edge) of the fraction bar, or None: the strongest long, near-level segment crossing the middle third."""
	h, w = g.shape
	ink = ((g < 150) * 255).astype(np.uint8)
	segs = cv2.HoughLinesP(ink, 1, np.pi / 180, threshold=max(20, int(w * 0.25)), minLineLength=int(w * 0.4), maxLineGap=max(4, int(w * 0.06)))
	best = None
	for x1, y1, x2, y2 in ([] if segs is None else np.asarray(segs).reshape(-1, 4)):       # (n, 1, 4) in some OpenCV versions, (n, 4) in others
		if x2 == x1:
			continue
		m = (y2 - y1) / (x2 - x1)
		if abs(m) > BAR_SLOPE:
			continue
		yl, yr = y1 - m * x1, y1 + m * (w - 1 - x1)
		mid = (yl + yr) / 2
		length = float(np.hypot(x2 - x1, y2 - y1))
		if not h * 0.3 <= mid <= h * 0.7:
			continue
		if best is None or length > best[0]:
			best = (length, yl, yr)
	return None if best is None else (best[1], best[2])


def _split_stacked(g):
	h, w = g.shape
	bar = _find_bar(g) or (h / 2, h / 2)
	yy, xx = np.mgrid[0:h, 0:w]
	line = bar[0] + (bar[1] - bar[0]) * xx / max(1, w - 1)
	gap = max(2.0, h * 0.025)
	return np.where(yy < line - gap, g, 255).astype(np.uint8), np.where(yy > line + gap, g, 255).astype(np.uint8)


def _split_diagonal(g, blank=None):
	h, w = g.shape
	if blank is not None and blank.shape == g.shape:
		g = np.where(cv2.dilate((blank < PRINT_BELOW).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0, 255, g).astype(np.uint8)
	yy, xx = np.mgrid[0:h, 0:w]
	s = xx / w + yy / h             # 1 on the diagonal, below 1 above-left of it, above 1 below-right of it
	return np.where(s < 1 + SOFT, g, 255).astype(np.uint8), np.where(s > 1 - SOFT, g, 255).astype(np.uint8)


def parts(crop, layout, blank=None):
	"""The two pieces of one cell crop (gray), each line-cleaned, in reading order (stacked: top, bottom; diagonal: above, below)."""
	if layout not in KIND_FOR:
		raise ValueError(f"{layout!r} has no pieces")
	g = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
	if min(g.shape) < 2 * MIN_SIDE:
		raise ValueError("cell is too small to split")
	a, b = _split_stacked(g) if layout == "stacked" else _split_diagonal(g, blank)
	return vision.remove_lines(a), vision.remove_lines(b)
