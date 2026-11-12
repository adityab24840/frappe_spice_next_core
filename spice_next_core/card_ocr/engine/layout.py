"""Template layout detection, as Card Studio does it: find the ruled table's cells with OpenCV (adaptive threshold, long horizontal and vertical rules,
connected components of what is left), then turn the cell rectangles into a pack grid by voting for the column and row lines. Port of Studio's
detect.py (detect_layout, unique_names) and gridconv.py (layout_to_grid), unchanged in behaviour; only the indentation and imports differ.

The voting tolerates merged cells, rows split differently per column, and a slightly skewed card (row lines are found per column).
"""
import re
from statistics import median

import cv2
import numpy as np

ROWNAME = re.compile(r"^[A-Za-z0-9_]{1,40}$")
DEFAULT = re.compile(r"^r\d+_c\d+$")
AXES = ("rows", "columns")


def detect_layout(bgr):
	"""Find ruled table lines -> cells -> rows/cols; small square cells -> 'mark' (checkbox).
	Returns {"fields": [...], "stats": {...}}. Field = {id,name,kind,section,x,y,w,h,range,charset}."""
	gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
	H, W = gray.shape
	bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 15)
	hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, W // 25), 1))
	vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, H // 25)))
	lines = cv2.bitwise_or(cv2.morphologyEx(bw, cv2.MORPH_OPEN, hk), cv2.morphologyEx(bw, cv2.MORPH_OPEN, vk))
	lines = cv2.dilate(lines, np.ones((3, 3), np.uint8))
	free = cv2.bitwise_not(lines)
	n, _, st, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
	cells = []
	for i in range(1, n):
		x, y, w, h, a = st[i]
		if w >= W * 0.97 or h >= H * 0.97:  # page background
			continue
		if w < 10 or h < 10 or a < 0.5 * w * h:
			continue
		cells.append((int(x), int(y), int(w), int(h)))
	cells.sort(key=lambda c: (c[1], c[0]))
	# group into rows by y centre, then number columns by x within the row
	rows, tol = [], max(8, int(np.median([c[3] for c in cells]) * 0.5)) if cells else 8
	for c in cells:
		cy = c[1] + c[3] / 2
		for r in rows:
			if abs(r["cy"] - cy) <= tol:
				r["cells"].append(c); r["cy"] = (r["cy"] * (len(r["cells"]) - 1) + cy) / len(r["cells"]); break
		else:
			rows.append({"cy": cy, "cells": [c]})
	rows.sort(key=lambda r: r["cy"])
	fields = []
	for ri, r in enumerate(rows, 1):
		for ci, (x, y, w, h) in enumerate(sorted(r["cells"]), 1):
			box = 0.7 <= w / h <= 1.4 and 12 <= w <= 70
			fields.append({"id": f"f{len(fields) + 1}", "name": f"r{ri}_c{ci}", "kind": "mark" if box else "text",
						   "section": "", "x": x, "y": y, "w": w, "h": h, "range": "", "charset": ""})
	# hollow square outlines inside cells (printed checkboxes): ink with ruled lines removed
	ink = cv2.bitwise_and(bw, free)
	cnts, hier = cv2.findContours(ink, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
	cell_boxes = [(f["x"], f["y"], f["w"], f["h"], f["name"]) for f in fields]
	for i, c in enumerate(cnts):
		if hier[0][i][3] != -1 or hier[0][i][2] == -1:  # need an outer contour that has a hole
			continue
		x, y, w, h = cv2.boundingRect(c)
		if not (0.75 <= w / h <= 1.33 and 14 <= w <= 70) or len(cv2.approxPolyDP(c, 0.06 * cv2.arcLength(c, True), True)) != 4:
			continue
		owner = next((n for cx, cy, cw, ch, n in cell_boxes if cx <= x and cy <= y and x + w <= cx + cw and y + h <= cy + ch and w < cw * 0.8), None)
		if owner:
			fields.append({"id": f"f{len(fields) + 1}", "name": f"{owner}_box", "kind": "mark", "section": "",
						   "x": int(x), "y": int(y), "w": int(w), "h": int(h), "range": "", "charset": "y x -"})
	unique_names(fields)
	return {"fields": fields, "stats": {"cells": len(fields), "rows": len(rows),
										 "marks": sum(f["kind"] == "mark" for f in fields), "image": [W, H]}}


def unique_names(fields):
	"""Give every field a unique name (a cell with two checkboxes would otherwise have two `<cell>_box`). Returns how many were renamed."""
	seen, renamed = set(), 0
	for f in fields:
		n, k = f["name"], 2
		while f["name"] in seen:
			f["name"] = f"{n}_{k}"; k += 1
		if f["name"] != n: renamed += 1
		seen.add(f["name"])
	return renamed


# tolerances as fractions of the image size (6 / 3 / 8 / 5 px on a 1169 x 827 template), so they hold at any resolution (with small floors for tiny images)
X_FRAC, Y_FRAC, EDGE_FRAC, NEAR_FRAC = 6 / 1169, 3 / 827, 8 / 1169, 5 / 827
SLACK_FRAC = 0.0   # extra room for the global vote (0 = tight; looser values pulled stray cells in and merged real lines on the ANC card)
X_VOTE = 0.4     # a column line needs this fraction of the best-supported line's votes
LINE_VOTE = 0.34  # a row line needs votes from this fraction of the columns (tuned on the ANC card only; 0.5 missed its bottom line)


def _cells(layout):
	return [f for f in layout["fields"] if not f["name"].endswith("_box")]


def _cluster(vals, tol):
	"""Group sorted 1-D values whose neighbours are within tol. Returns lists of values."""
	out = []
	for v in sorted(vals):
		if out and v - out[-1][-1] <= tol:
			out[-1].append(v)
		else:
			out.append([v])
	return out


def _near(vals, target, tol):
	close = [v for v in vals if abs(v - target) <= tol]
	return median(close) if close else target


AXES = ("rows", "columns")


def field_names(grid):
	"""The field keys of a grid: its row names, or its column names when the fields run down the columns."""
	return grid["cols"] if grid.get("axis") == "columns" else grid["rows"]


def layout_to_grid(layout, label_cols=0, data_cols=None, scale=1.0, axis="rows", label_rows=0, data_rows=None):
	"""Returns (grid, warnings). Raises ValueError when no table can be found.

	Column lines are the x positions where many cells start or end; row lines are the y positions where cells in the
	chosen columns start or end (a line is the bottom of the cell above and the top of the cell below, so it is voted
	for twice per column). This tolerates merged cells and rows that detect.py split differently per column.
	label_cols: leading columns to skip (printed row labels). data_cols: keep only this many columns after that.
	label_rows / data_rows: the same for rows (printed headings at the top). axis: which way the fields run (see the module text).
	"""
	if axis not in AXES:
		raise ValueError(f"axis must be one of {AXES}")
	cells = _cells(layout)
	if len(cells) < 4:
		raise ValueError("too few cells to form a table")
	warnings = []
	W, H = layout["image"]
	X_TOL, Y_TOL, EDGE_TOL, NEAR_TOL = max(4, W * X_FRAC), max(3, H * Y_FRAC), max(5, W * EDGE_FRAC), max(4, H * NEAR_FRAC)
	xe = _cluster([c["x"] for c in cells] + [c["x"] + c["w"] for c in cells], X_TOL)
	thr = max(3, X_VOTE * max(len(c) for c in xe))
	xl = [median(c) for c in xe if len(c) >= thr]
	if len(xl) < 2:
		raise ValueError("no vertical table lines found")
	cols = list(zip(xl, xl[1:]))[label_cols:]
	if data_cols:
		cols = cols[:data_cols]
	if not cols:
		raise ValueError("no data columns left after label_cols/data_cols")
	x0, x1 = cols[0][0], cols[-1][1]
	slack = max(X_TOL, SLACK_FRAC * median(b - a for a, b in cols))   # a skewed card moves cell edges by tens of px, but never by half a column
	inside = [c for c in cells if c["x"] >= x0 - slack and c["x"] + c["w"] <= x1 + slack]
	ye = _cluster([v for c in inside for v in (c["y"], c["y"] + c["h"])], Y_TOL)
	yl = [median(c) for c in ye if len(c) >= max(2, round(LINE_VOTE * len(cols)))]
	if len(yl) < 3:
		raise ValueError("no horizontal row lines found in the data columns")
	yl = yl[label_rows:]
	if data_rows:
		yl = yl[:data_rows + 1]
	if len(yl) < 2:
		raise ValueError("no data rows left after label_rows/data_rows")
	nrows = len(yl) - 1
	named = [c for c in cells if ROWNAME.match(c["name"]) and not DEFAULT.match(c["name"])]
	names, colnames, seen = [], None, set()
	if axis == "rows":      # row names: a renamed cell to the left of the data columns, else row_01...
		left = [c for c in named if c["x"] + c["w"] / 2 < x0]
		for i in range(nrows):
			hit = [c["name"] for c in left if yl[i] <= c["y"] + c["h"] / 2 <= yl[i + 1] and c["name"] not in seen]
			nm = hit[0] if hit else f"row_{i + 1:02d}"
			names.append(nm); seen.add(nm)
	else:                   # column names: a renamed cell above the data rows (the lowest one, nearest the data), else col_01...
		above = sorted((c for c in named if c["y"] + c["h"] / 2 < yl[0]), key=lambda c: -c["y"])
		names, colnames = [f"r{i + 1}" for i in range(nrows)], []
		for i, (xa, xb) in enumerate(cols):
			hit = [c["name"] for c in above if xa <= c["x"] + c["w"] / 2 <= xb and c["name"] not in seen]
			nm = hit[0] if hit else f"col_{i + 1:02d}"
			colnames.append(nm); seen.add(nm)
	# row lines per column (follows a skewed card): this column's own edges near each global line, within
	# almost half a row so a line is never matched to its neighbour
	NEAR_TOL = max(NEAR_TOL, 0.45 * median(b - a for a, b in zip(yl, yl[1:])))
	rl = []
	for (xa, xb) in cols:
		mine = [c for c in cells if xa <= c["x"] + c["w"] / 2 <= xb and c["w"] <= 1.4 * (xb - xa)]   # by centre, from all cells: skew can push edge cells out of the vote
		edges = [v for c in mine for v in (c["y"], c["y"] + c["h"])]
		col = []
		for i, y in enumerate(yl):
			v = _near(edges, y, NEAR_TOL)
			if col and v <= col[-1] + 1:      # two global lines picked the same edge: use the global line instead
				v = max(y, col[-1] + 1)
			col.append(v)
		rl.append(col)
	# column lines at the top and the bottom of the table (first and last row band)
	xs_all = [cols[0][0]] + [b for _, b in cols]
	def col_lines(i):
		band = [c for c in inside if yl[i] <= c["y"] + c["h"] / 2 <= yl[i + 1]]
		edges = [v for c in band for v in (c["x"], c["x"] + c["w"])]
		return [_near(edges, x, EDGE_TOL) for x in xs_all]
	top, bot = col_lines(0), col_lines(nrows - 1)
	f = lambda v: round(v * scale, 1)
	grid = {"image_size": [round(W * scale), round(H * scale)], "rows": names,
			"y_ref_top": f(rl[0][0]), "y_ref_bot": f(rl[0][-1]),
			"col_lines_top": [f(v) for v in top], "col_lines_bot": [f(v) for v in bot],
			"row_lines_by_col": [[f(v) for v in col] for col in rl]}
	if axis == "columns":
		grid["axis"], grid["cols"] = "columns", colnames
	thin = [i + 1 for i in range(nrows) if yl[i + 1] - yl[i] < 8]
	if thin:
		warnings.append(f"row(s) {thin} are under 8 px tall: probably a spurious line")
	return grid, warnings


